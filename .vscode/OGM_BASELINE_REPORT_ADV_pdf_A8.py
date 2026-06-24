import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime
import webbrowser
import os
import json

print("=========================================================")
print("AI OGM LIVE DASHBOARD - MASTER VALUE-GROWTH SKENER")
print("=========================================================")

CSV_DATOTEKA = "moje_globalne_delnice.csv"

# ==============================================================================
# STRATEŠKI INSTITUCIONALNI FILTRI
# ==============================================================================
MIN_MARKET_CAP = 20_000_000_000      # 20 milijard $ (Vstopni filter za Large-Cap elito)
MEGA_CAP_THRESHOLD = 200_000_000_000 # 200 milijard $ (Za Mega-Cap/Mag7 pravilo 50w MA)
MIN_REVENUE_GROWTH = 0.1             # Minimalno 10 % pričakovana rast prihodkov
SUPER_GROWTH_THRESHOLD = 0.50        # Izpostavljena super-rast > 50 %

def formatiraj_mcap(mcap):
    if mcap == 0 or pd.isna(mcap) or mcap is None: return "N/A"
    if mcap >= 1e12: return f"${mcap/1e12:.2f}T"
    if mcap >= 1e9: return f"${mcap/1e9:.2f}B"
    if mcap >= 1e6: return f"${mcap/1e6:.2f}M"
    return f"${mcap}"

def safe_float(val, default=0.0):
    try:
        if val is None or pd.isna(val):
            return default
        return float(val)
    except:
        return default

if not os.path.exists(CSV_DATOTEKA):
    print(f"[NAPAKA] Datoteka '{CSV_DATOTEKA}' ne obstaja! Najprej zaženi Korak 1.")
    os._exit(0)

df_baza = pd.read_csv(CSV_DATOTEKA)
tickerji_v_obdelavi = df_baza['Ticker'].dropna().astype(str).str.strip().tolist()

strong_buy_podatki_za_graf = {}

# ==============================================================================
# 2. ŽIVI SKENER
# ==============================================================================
def skeniraj_trg():
    print(f"\n[START] Začenjam skeniranje za {len(tickerji_v_obdelavi)} delnic...")
    print("        -> Filtri kakovosti aktivirani.")
    print("        -> V2 Mega-Cap pravilo (Razširjena toleranca na rast) AKTIVIRANO.")
    print("---------------------------------------------------------")
    
    trenutno_leto = datetime.now().year
    rezultati = []
    
    for krog, ticker in enumerate(tickerji_v_obdelavi, 1):
        if krog % 20 == 0:
            print(f"    ... obdelano {krog} / {len(tickerji_v_obdelavi)} delnic ...")
            
        try:
            delnica = yf.Ticker(ticker)
            
            # 1. ZDRUŽENO PRIDOBIVANJE VSEH PODATKOV NA ZACETKU
            try:
                info_podatki = delnica.info
                mcap = info_podatki.get('marketCap')
                rev_growth = info_podatki.get('revenueGrowth')
                ime_podjetja = info_podatki.get('shortName') or info_podatki.get('longName') or ticker
                
                # Dodatni podatki
                sektor = info_podatki.get('sector', 'Neznano')
                target_price = safe_float(info_podatki.get('targetMeanPrice'))
                if target_price == 0.0:
                    target_price = safe_float(info_podatki.get('targetMedianPrice'))
                    
                pe_ratio = safe_float(info_podatki.get('trailingPE'))
                if pe_ratio == 0.0:
                    pe_ratio = safe_float(info_podatki.get('forwardPE'))
                
                # Zbrani OGM Fundamenti
                eps_growth = info_podatki.get('earningsQuarterlyGrowth') or info_podatki.get('earningsGrowth')
                peg_ratio = info_podatki.get('pegRatio')
                gross_margin = info_podatki.get('grossMargins')
                
            except Exception as e:
                # VIDNO OPOZORILO ČE YAHOO BLOKIRA IP NASLOV!
                print(f"    [!] Yahoo API blokada ali manjkajoči podatki pri {ticker}. Hladim (1s)...")
                time.sleep(1)
                continue
                
            # Začetni filter elita
            if mcap is None or pd.isna(mcap) or mcap < MIN_MARKET_CAP:
                continue
                
            rev_growth_val = safe_float(rev_growth)
            mcap_prikaz = formatiraj_mcap(mcap)
            is_mega_cap = mcap >= MEGA_CAP_THRESHOLD
            
            data = delnica.history(start="2014-01-01", interval="1wk", actions=False)
            if data is None or data.empty or len(data) < 205:
                continue
            
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
                
            close_series = data['Close'].dropna()
            if close_series.empty or len(close_series) < 205:
                continue
                
            # ==================================================================
            # ŽIVA FUNDAMENTALNA INTERPOLACIJA (Max 45 Točk)
            # ==================================================================
            eps_growth_pct = safe_float(eps_growth) * 100
            gross_margin_pct = safe_float(gross_margin) * 100
            peg_ratio_val = safe_float(peg_ratio, default=2.0)
            if peg_ratio_val == 0.0: peg_ratio_val = 2.0
            
            tocke_eps = np.interp(eps_growth_pct, [0.0, 8.0, 16.5, 22.0, 30.0], [0.0, 5.0, 14.0, 20.0, 20.0])
            tocke_peg = np.interp(peg_ratio_val, [0.4, 0.8, 1.2, 1.6, 2.0], [15.0, 13.0, 10.0, 5.0, 0.0])
            tocke_margin = np.interp(gross_margin_pct, [25, 35, 45, 55, 65], [0.0, 4.0, 10.0, 14.0, 15.0])
            
            base_fundament_score = min(45.0, tocke_eps + tocke_peg + tocke_margin)
                
            # ==================================================================
            # TEHNIČNI TAJMING (Max 55 Točk z Mega-Cap pravilom)
            # ==================================================================
            ma200 = close_series.rolling(window=200).mean()
            ma50 = close_series.rolling(window=50).mean()
            ma20 = close_series.rolling(window=4).mean()
            
            # Dinamična določitev tarčnega povprečja
            ma_target = ma50 if is_mega_cap else ma200
            tip_ma = "50w MA (Mega-Cap)" if is_mega_cap else "200w MA"
            
            zadnji_ma_target = float(ma_target.iloc[-1])
            zadnji_ma20_weekly = float(ma20.iloc[-1])
            
            if zadnji_ma_target == 0 or pd.isna(zadnji_ma_target): continue
                
            pct_ma = ((close_series - ma_target) / ma_target) * 100

            delta = close_series.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            oddaljenost_arr = pct_ma.values
            rsi_arr = rsi.values
            
            tocke_ma = np.zeros_like(oddaljenost_arr)
            pos_mask = oddaljenost_arr >= 0
            neg_mask = oddaljenost_arr < 0
            
            W_MA = 40.0  
            W_RSI = 15.0 
            
            if is_mega_cap:
                # MEGA-CAP PRAVILO V2: Popravljena toleranca na rast (sedaj do 30% namesto 15%)
                tocke_ma[pos_mask] = np.interp(oddaljenost_arr[pos_mask], [0, 2, 12, 30], [W_MA*(33/35), W_MA, W_MA*(22/35), 0.0])
                tocke_ma[neg_mask] = np.interp(oddaljenost_arr[neg_mask], [-40, -15, -2, 0], [W_MA, W_MA, W_MA*(34/35), W_MA*(33/35)])
            else:
                # KLASIČNA krivulja (širša, za 200w MA)
                tocke_ma[pos_mask] = np.interp(oddaljenost_arr[pos_mask], [0, 2, 10, 25, 50], [W_MA*(33/35), W_MA, W_MA*(22/35), W_MA*(8/35), 0.0])
                tocke_ma[neg_mask] = np.interp(oddaljenost_arr[neg_mask], [-20, -10, -5, 0], [0.0, W_MA*(12/35), W_MA*(25/35), W_MA*(33/35)])
                
            tocke_rsi = np.interp(rsi_arr, [30, 45, 60, 70, 80], [W_RSI, W_RSI*0.8, W_RSI*0.5, W_RSI*0.2, 0.0])
            
            ogm_zgodovina = np.clip(tocke_ma + tocke_rsi + base_fundament_score, 0, 100)
            
            trenutna_cena = float(close_series.iloc[-1])
            oddaljenost_ma_trenutna = float(oddaljenost_arr[-1])
            trenutni_ogm = float(ogm_zgodovina[-1])
            
            if pd.isna(oddaljenost_ma_trenutna) or pd.isna(trenutni_ogm): 
                continue
                
            # Glavni Filter
            if trenutni_ogm < 65.0 or rev_growth_val < MIN_REVENUE_GROWTH:
                continue 
                
            # ==================================================================
            # IZRACUN SEZONSKOSTI IN TRENDOV ZA KVALIFICIRANE DELNICE
            # ==================================================================
            close_series.index = pd.to_datetime(close_series.index)
            
            monthly_prices = close_series.groupby([close_series.index.year, close_series.index.month]).last()
            monthly_returns = monthly_prices.pct_change() * 100
            
            yearly_prices = close_series.groupby(close_series.index.year).last()
            yearly_returns = yearly_prices.pct_change() * 100
            
            yearly_data = [{"leto": int(y), "donos": float(val)} for y, val in yearly_returns.dropna().items()]
            monthly_data = {}
            for (y, m), val in monthly_returns.dropna().items():
                y, m = int(y), int(m)
                if y not in monthly_data: monthly_data[y] = {}
                monthly_data[y][m] = float(val)

            trend_ok = oddaljenost_ma_trenutna >= 0
            is_falling_phase = zadnji_ma20_weekly < zadnji_ma_target
            donos_1m = ((trenutna_cena - float(close_series.iloc[-5])) / float(close_series.iloc[-5])) * 100
            
            vsi_datumi = close_series.index
            datumi_trenutnega_leta = vsi_datumi[vsi_datumi.year == trenutno_leto]
            try:
                if len(datumi_trenutnega_leta) > 0: cena_zacetek_leta = float(close_series.loc[datumi_trenutnega_leta[0]])
                else: cena_zacetek_leta = float(close_series.iloc[-22])
                donos_ytd = ((trenutna_cena - cena_zacetek_leta) / cena_zacetek_leta) * 100
            except Exception: donos_ytd = 0.0
            
            # Prioriteta: STRONG BUY povozijo opozorilo o padanju (pomembno za Mega-Caps!)
            if trenutni_ogm >= 80.0: status = "STRONG BUY"
            elif is_falling_phase: status = "WARNING (FALLING PHASE)"
            elif not trend_ok: status = "WARNING (POD MA)"
            elif rev_growth_val >= SUPER_GROWTH_THRESHOLD: status = "SUPER-GROWTH TARGET"
            else: status = "BUY"
            
            datumi_str = [d.strftime("%Y-%m-%d") for d in close_series.index]
            zgodovina_tabela = []
            zadnji_indeks_signala = -999
            
            for i in range(len(ogm_zgodovina)):
                if ogm_zgodovina[i] >= 80.0 and (i - zadnji_indeks_signala) > 26:
                    cena_ob_signalu = close_series.iloc[i]
                    if i + 52 < len(close_series): max_cena_12m = close_series.iloc[i:i+52].max()
                    else: max_cena_12m = close_series.iloc[i:].max() if i + 1 < len(close_series) else cena_ob_signalu
                    donos = ((max_cena_12m - cena_ob_signalu) / cena_ob_signalu) * 100
                    if i + 52 < len(close_series):
                        zgodovina_tabela.append({"datum": datumi_str[i], "cena": round(cena_ob_signalu, 2), "max_cena": round(max_cena_12m, 2), "max_donos": round(donos, 1)})
                    zadnji_indeks_signala = i
            
            strong_buy_podatki_za_graf[ticker] = {
                "ime": ime_podjetja,
                "dates": datumi_str,
                "prices": np.round(close_series.values, 2).tolist(),
                "ogm": np.round(ogm_zgodovina, 1).tolist(),
                "history": zgodovina_tabela,
                "yearly": yearly_data[-10:], 
                "monthly": monthly_data,
                "components": {
                    "eps_growth_raw": eps_growth_pct, "eps_growth_score": float(tocke_eps),
                    "peg_raw": peg_ratio_val, "peg_score": float(tocke_peg),
                    "pe_raw": pe_ratio, 
                    "margin_raw": gross_margin_pct, "margin_score": float(tocke_margin),
                    "rsi_raw": float(rsi_arr[-1]), "rsi_score": float(tocke_rsi[-1]),
                    "ma_dist_raw": oddaljenost_ma_trenutna, "ma_dist_score": float(tocke_ma[-1]),
                    "total_score": trenutni_ogm,
                    "ma_type": tip_ma
                }
            }
                
            rezultati.append({
                "Ticker": ticker, "Ime": ime_podjetja, "Sektor": sektor, "TargetPrice": target_price,
                "Cena": trenutna_cena, "OGM": trenutni_ogm,
                "Status": status, "1M_Donos": donos_1m, "YTD_Donos": donos_ytd,
                "MarketCap": mcap_prikaz, "Mcap_Raw": mcap, "RevGrowth": rev_growth_val * 100,
                "Dist200w": oddaljenost_ma_trenutna,
                "MaType": tip_ma
            })
            
            time.sleep(0.04)
        except Exception as e:
            continue

    generiraj_html_porocilo(rezultati)

# ==============================================================================
# 3. HTML GENERATOR POROČILA
# ==============================================================================
def generiraj_html_porocilo(podatki):
    df_html = pd.DataFrame(podatki)
    if not df_html.empty:
        df_html = df_html.sort_values(by=["OGM"], ascending=[False])
        
    datum_danes = datetime.now().strftime("%d.%m.%Y")
    graf_json = json.dumps(strong_buy_podatki_za_graf)
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>OGM Živi Radar</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #1e293b; background-color: #f8fafc; margin: 40px auto; max-width: 1450px; padding: 0 20px; }}
    .header {{ background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 100%); color: #ffffff; padding: 30px; border-radius: 8px; border-bottom: 4px solid #2563eb; position: relative; }}
    .header h1 {{ margin: 0; font-size: 22pt; font-weight: 700; }}
    .header p {{ margin: 5px 0 0 0; color: #bfdbfe; font-size: 11pt; }}
    
    .btn-pdf {{ position: absolute; right: 30px; top: 35px; background-color: #ef4444; color: white; border: none; padding: 12px 20px; border-radius: 6px; font-weight: 700; font-size: 10pt; cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: 0.2s; }}
    .btn-pdf:hover {{ background-color: #dc2626; transform: translateY(-1px); }}
    
    table {{ width: 100%; border-collapse: collapse; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-top: 25px; table-layout: auto;}}
    th {{ background-color: #1e293b; color: #ffffff; text-align: left; padding: 12px 10px; font-size: 9.5pt; font-weight: 600; }}
    td {{ padding: 11px 10px; border-bottom: 1px solid #e2e8f0; font-size: 9.5pt; }}
    tr:nth-child(even) {{ background-color: #f8fafc; }}
    tr:hover {{ background-color: #f1f5f9; }}
    
    .badge {{ padding: 4px 8px; border-radius: 4px; font-weight: 700; font-size: 8.5pt; display: inline-block; }}
    .super-growth {{ background-color: #fae8ff; color: #a21caf; border: 1px solid #d946ef; }}
    .strong-buy {{ background-color: #dcfce7; color: #15803d; }}
    .buy {{ background-color: #e0f2fe; color: #0369a1; }}
    .warning-falling {{ background-color: #ffedd5; color: #ea580c; border: 1px solid #f97316; }}
    .warning-ma {{ background-color: #fee2e2; color: #dc2626; border: 1px solid #f87171; }}
    
    .pos-return {{ color: #16a34a; font-weight: 600; }}
    .neg-return {{ color: #dc2626; font-weight: 600; }}
    .mcap-text {{ color: #475569; font-weight: 600; font-size: 9pt; }}
    .growth-text {{ font-weight: 700; color: #1d4ed8; }}
    .dist-green {{ color: #16a34a; background-color: #f0fdf4; font-weight: bold; padding: 4px 6px; border-radius: 4px; }}
    .dist-orange {{ color: #ea580c; background-color: #fff7ed; font-weight: bold; padding: 4px 6px; border-radius: 4px; }}
    .dist-normal {{ color: #475569; font-weight: 500; }}
    
    .modal {{ display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; overflow: auto; background-color: rgba(0,0,0,0.6); backdrop-filter: blur(4px); }}
    .modal-content {{ background-color: #fff; margin: 3% auto; padding: 25px; border-radius: 12px; width: 90%; max-width: 1050px; box-shadow: 0 10px 25px rgba(0,0,0,0.2); position: relative; max-height: 85vh; overflow-y: auto; }}
    .close {{ color: #94a3b8; position: absolute; right: 20px; top: 15px; font-size: 28px; font-weight: bold; cursor: pointer; }}
    .close:hover {{ color: #0f172a; }}
    .chart-container {{ position: relative; height: 320px; width: 100%; margin-top: 20px; }}
    
    .history-table {{ margin-top: 15px; font-size: 9pt; width: 100%; border: 1px solid #e2e8f0; border-collapse: collapse; }}
    .history-table th {{ background-color: #f1f5f9; color: #475569; padding: 8px; text-align: left; }}
    .history-table td {{ padding: 8px; border-bottom: 1px solid #e2e8f0; }}
    
    .clickable-ticker {{ cursor: pointer; color: #1d4ed8; text-decoration: underline; font-weight: bold; }}
    .clickable-ticker:hover {{ color: #1e40af; }}
    .ime-podjetja {{ max-width: 160px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #475569; font-size: 8.5pt; }}
    
    .grid-container {{ display: grid; grid-template-columns: 1fr 2fr; gap: 20px; margin-top: 25px; }}
    
    @media print {{
        body {{ background-color: white; margin: 0; padding: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
        .btn-pdf, #navodilo-klik {{ display: none !important; }}
        table {{ box-shadow: none; page-break-inside: auto; border: 1px solid #cbd5e1; }}
        tr {{ page-break-inside: avoid; page-break-after: auto; }}
        thead {{ display: table-header-group; }}
        .modal {{ display: none !important; }}
    }}
    </style>
    </head>
    <body>

    <div class="header">
        <h1>OVNICEK GROWTH MATRIX &mdash; VALUE-GROWTH RADAR</h1>
        <p>Začetni filtri: Market Cap > 20B | Rast prihodkov > 10% | Osveženo: {datum_danes}</p>
        <p id="navodilo-klik" style="font-size: 9pt; color: #93c5fd; margin-top: 5px;">* Sistem uporablja 200w MA za klasična podjetja in 50w MA za Mega-Cap gigante (>200B$). Klikni na ticker za analizo.</p>
        <button class="btn-pdf" onclick="window.print()">📥 Izvozi v PDF</button>
    </div>

    <table>
        <thead>
            <tr>
                <th>Ticker</th>
                <th>Ime podjetja</th>
                <th>Sektor</th>
                <th>Market Cap</th>
                <th>Rast Prihodkov</th>
                <th>Razdalja do tarčnega MA</th>
                <th>Cena</th>
                <th>Ciljna Cena (12m)</th>
                <th>Trenutni OGM</th>
                <th>Uradni status</th>
                <th>1M Donos</th>
                <th>YTD Donos</th>
            </tr>
        </thead>
        <tbody>
    """
    
    if not df_html.empty:
        for _, row in df_html.iterrows():
            if row['Status'] == "SUPER-GROWTH TARGET": badge_class = "super-growth"
            elif row['Status'] == "STRONG BUY": badge_class = "strong-buy"
            elif row['Status'] == "BUY": badge_class = "buy"
            elif row['Status'] == "WARNING (FALLING PHASE)": badge_class = "warning-falling"
            else: badge_class = "warning-ma"
            
            dist_val = row['Dist200w']
            if 0.0 <= dist_val <= 5.0: dist_class = "dist-green" 
            elif dist_val < 0.0: dist_class = "dist-orange" 
            else: dist_class = "dist-normal" 
            
            class_1m = "pos-return" if row['1M_Donos'] >= 0 else "neg-return"
            class_ytd = "pos-return" if row['YTD_Donos'] >= 0 else "neg-return"
            
            ticker_display = f'<span class="clickable-ticker" onclick="openAnalysis(\'{row["Ticker"]}\')">{row["Ticker"]} 📊</span>'
            
            tp_display = f"${row['TargetPrice']:.2f}" if row['TargetPrice'] > 0 else "N/A"
                
            html_content += f"""
                <tr>
                    <td>{ticker_display}</td>
                    <td><div class="ime-podjetja" title="{row['Ime']}">{row['Ime']}</div></td>
                    <td style="color:#64748b; font-size:8.5pt;">{row['Sektor']}</td>
                    <td class="mcap-text">{row['MarketCap']}</td>
                    <td class="growth-text">{row['RevGrowth']:.1f} %</td>
                    <td><span class="{dist_class}">{row['Dist200w']:+.1f} %</span><br><span style="font-size:7pt; color:#94a3b8;">({row['MaType']})</span></td>
                    <td style="font-weight: 600;">${row['Cena']:.2f}</td>
                    <td style="font-weight: 600; color:#0f172a;">{tp_display}</td>
                    <td style="font-weight: 700; font-size: 10pt; color: #0f172a;">{row['OGM']:.1f} / 100</td>
                    <td><span class="badge {badge_class}">{row['Status']}</span></td>
                    <td class="{class_1m}">{row['1M_Donos']:+.1f} %</td>
                    <td class="{class_ytd}">{row['YTD_Donos']:+.1f} %</td>
                </tr>
            """
    else:
        html_content += """<tr><td colspan="12" style="text-align:center;">Trenutno ni delnic, ki ustrezajo kriterijem.</td></tr>"""
        
    html_content += f"""
        </tbody>
    </table>

    <div id="analysisModal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeModal()">&times;</span>
            <h2 id="modalTitle" style="margin-top:0; color:#0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;">Detajlna OGM Analiza</h2>
            <p id="modalSubtitle" style="font-size: 10pt; color: #64748b; margin-top: -5px; margin-bottom: 20px;"></p>
            
            <div class="chart-container">
                <canvas id="ogmChart"></canvas>
            </div>
            
            <div class="grid-container">
                <div>
                    <h3 style="font-size: 10.5pt; color: #1e293b; margin-bottom: 5px;">Sestava trenutnega OGM koeficienta</h3>
                    <div id="componentsBody"></div>
                    
                    <h3 style="font-size: 10.5pt; color: #1e293b; margin-top: 20px; margin-bottom: 5px;">Letni donosi (Zadnjih 10 let)</h3>
                    <div id="yearlyBody" style="margin-top: 10px;"></div>
                </div>
                
                <div>
                    <h3 style="font-size: 10.5pt; color: #1e293b; margin-bottom: 5px;">Mesečna sezonskost (Heatmap)</h3>
                    <div id="monthlyBody" style="overflow-x: auto;"></div>
                    
                    <h3 style="font-size: 10.5pt; color: #1e293b; margin-top: 20px; margin-bottom: 5px;">Zgodovina uspešnosti preteklih prebojev OGM > 80</h3>
                    <table class="history-table">
                        <thead>
                            <tr>
                                <th>Datum preboja</th>
                                <th>Cena ob signalu</th>
                                <th>Maks cena v 12m</th>
                                <th>Maks 12m donos</th>
                            </tr>
                        </thead>
                        <tbody id="historyBody"></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
    const chartData = {graf_json};
    let currentChart = null;

    function openAnalysis(ticker) {{
        const data = chartData[ticker];
        if (!data) return;
        
        document.getElementById('modalTitle').innerText = "OGM Analiza: " + ticker;
        document.getElementById('modalSubtitle').innerText = data.ime;
        
        // 1. GRAF
        const ctx = document.getElementById('ogmChart').getContext('2d');
        if (currentChart) {{ currentChart.destroy(); }}
        currentChart = new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: data.dates,
                datasets: [
                    {{ label: 'Cena ($)', data: data.prices, yAxisID: 'y', borderColor: '#2563eb', backgroundColor: 'rgba(37, 99, 235, 0.1)', borderWidth: 2, pointRadius: 0, tension: 0.1, fill: true }},
                    {{ label: 'OGM Score', data: data.ogm, yAxisID: 'y1', borderColor: '#16a34a', borderWidth: 1.5, pointRadius: 0, tension: 0.3, borderDash: [5, 5] }}
                ]
            }},
            options: {{
                responsive: true, maintainAspectRatio: false, interaction: {{ mode: 'index', intersect: false }},
                scales: {{
                    x: {{ ticks: {{ maxTicksLimit: 12 }} }},
                    y: {{ type: 'linear', display: true, position: 'left', title: {{ display: true, text: 'Cena ($)' }} }},
                    y1: {{ type: 'linear', display: true, position: 'right', min: 0, max: 100, title: {{ display: true, text: 'OGM Točke' }}, grid: {{ drawOnChartArea: false }} }}
                }}
            }}
        }});

        // 2. OGM KOMPONENTE
        let compHTML = `
            <table class="history-table">
                <tr><th>Faktor</th><th>Vrednost</th><th>Dodeljene točke</th></tr>
                <tr><td>Rast EPS</td><td>${{data.components.eps_growth_raw.toFixed(1)}} %</td><td style="font-weight:bold;">${{data.components.eps_growth_score.toFixed(1)}} / 20</td></tr>
                <tr><td>PEG Ratio</td><td>${{data.components.peg_raw.toFixed(2)}}</td><td style="font-weight:bold;">${{data.components.peg_score.toFixed(1)}} / 15</td></tr>
                <tr><td>Bruto Marža</td><td>${{data.components.margin_raw.toFixed(1)}} %</td><td style="font-weight:bold;">${{data.components.margin_score.toFixed(1)}} / 10</td></tr>
                <tr><td>RSI (14w)</td><td>${{data.components.rsi_raw.toFixed(1)}}</td><td style="font-weight:bold;">${{data.components.rsi_score.toFixed(1)}} / 15</td></tr>
                <tr><td>Oddaljenost od ${{data.components.ma_type}}</td><td>${{data.components.ma_dist_raw.toFixed(1)}} %</td><td style="font-weight:bold;">${{data.components.ma_dist_score.toFixed(1)}} / 40</td></tr>
                <tr><td style="color:#64748b;">Trenutni P/E</td><td style="color:#64748b;">${{data.components.pe_raw.toFixed(1)}}</td><td style="color:#cbd5e1; font-size:8pt;">(Informativno)</td></tr>
                <tr style="background-color: #f1f5f9; font-weight: bold; font-size: 10pt; color: #0f172a;"><td>SKUPAJ OGM</td><td>-</td><td>${{data.components.total_score.toFixed(1)}} / 100</td></tr>
            </table>
        `;
        document.getElementById('componentsBody').innerHTML = compHTML;

        // 3. LETNI DONOSI
        let yearlyHTML = '<div style="display:flex; flex-wrap:wrap; gap:8px;">';
        data.yearly.forEach(y => {{
            let color = y.donos >= 0 ? '#16a34a' : '#dc2626';
            let bg = y.donos >= 0 ? '#f0fdf4' : '#fef2f2';
            yearlyHTML += `<div style="border: 1px solid #e2e8f0; background-color: ${{bg}}; padding: 8px; border-radius: 6px; text-align: center; min-width: 60px;">
                <div style="font-size: 8pt; color: #64748b;">${{y.leto}}</div>
                <div style="font-weight: bold; color: ${{color}};">${{y.donos > 0 ? '+':''}}${{y.donos.toFixed(1)}}%</div>
            </div>`;
        }});
        yearlyHTML += '</div>';
        document.getElementById('yearlyBody').innerHTML = yearlyHTML;

        // 4. MESEČNI DONOSI (HEATMAP)
        let monthlyHTML = '<table class="history-table" style="text-align:center;"><tr><th>Leto</th>';
        const meseci = ['Jan', 'Feb', 'Mar', 'Apr', 'Maj', 'Jun', 'Jul', 'Avg', 'Sep', 'Okt', 'Nov', 'Dec'];
        meseci.forEach(m => monthlyHTML += `<th>${{m}}</th>`);
        monthlyHTML += '</tr>';
        
        let years = Object.keys(data.monthly).map(Number).sort((a,b) => b - a);
        years.slice(0, 10).forEach(y => {{ // Pokaži samo zadnjih 10 let v heatmapu
            monthlyHTML += `<tr><td style="font-weight:bold; color:#475569;">${{y}}</td>`;
            for(let m=1; m<=12; m++) {{
                let val = data.monthly[y][m];
                if (val !== undefined) {{
                    let color = val >= 0 ? '#15803d' : '#b91c1c';
                    let bg = val >= 0 ? 'rgba(22, 163, 74, 0.1)' : 'rgba(220, 38, 38, 0.1)';
                    monthlyHTML += `<td style="color: ${{color}}; background-color: ${{bg}}; font-size:8pt; font-weight: 500;">${{val>0?'+':''}}${{val.toFixed(1)}}%</td>`;
                }} else {{
                    monthlyHTML += `<td style="color:#cbd5e1; font-size:8pt;">-</td>`;
                }}
            }}
            monthlyHTML += '</tr>';
        }});
        monthlyHTML += '</table>';
        document.getElementById('monthlyBody').innerHTML = monthlyHTML;

        // 5. ZGODOVINA SIGNALOV
        const tbody = document.getElementById('historyBody');
        tbody.innerHTML = "";
        if (!data.history || data.history.length === 0) {{
            tbody.innerHTML = "<tr><td colspan='4' style='text-align:center; color:#64748b;'>Ni zabeleženih preteklih signalov v zadnjih 10 letih.</td></tr>";
        }} else {{
            data.history.forEach(row => {{
                const colorClass = row.max_donos >= 0 ? "color: #16a34a; font-weight:bold;" : "color: #dc2626; font-weight:bold;";
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${{row.datum}}</td>
                    <td>$${{row.cena.toFixed(2)}}</td>
                    <td>$${{row.max_cena.toFixed(2)}}</td>
                    <td style="${{colorClass}}">+${{row.max_donos.toFixed(1)}} %</td>
                `;
                tbody.appendChild(tr);
            }});
        }}

        document.getElementById('analysisModal').style.display = "block";
    }}

    function closeModal() {{ document.getElementById('analysisModal').style.display = "none"; }}
    window.onclick = function(event) {{
        const modal = document.getElementById('analysisModal');
        if (event.target == modal) {{ modal.style.display = "none"; }}
    }}
    </script>
    </body>
    </html>
    """
    
    html_content = html_content.replace("NaN", "0.0")
    ime_datoteke = "OGM_NASDAQ_EXPERT.html"
    with open(ime_datoteke, "w", encoding="utf-8") as f: f.write(html_content)
    print(f"\n[USPEH] Analitično poročilo je ustvarjeno: '{ime_datoteke}'")
    webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

skeniraj_trg()