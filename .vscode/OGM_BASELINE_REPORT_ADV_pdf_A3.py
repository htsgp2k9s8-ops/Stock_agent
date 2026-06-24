import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime
import webbrowser
import os
import json

print("=========================================================")
print("AI OGM LIVE DASHBOARD - MASTER CSV SKENER Z ANALITIKO")
print("=========================================================")

CSV_DATOTEKA = "moje_globalne_delnice.csv"

# ==============================================================================
# STRATEŠKI INSTITUCIONALNI FILTRI
# ==============================================================================
MIN_MARKET_CAP = 20_000_000_000      # 20 milijard $ (Stroga Large-Cap elita)
MIN_REVENUE_GROWTH = 0.1            # Minimalno 10 % pričakovana rast prihodkov
SUPER_GROWTH_THRESHOLD = 0.50        # Izpostavljena super-rast > 50 %

def formatiraj_mcap(mcap):
    if mcap == 0 or pd.isna(mcap) or mcap is None: return "N/A"
    if mcap >= 1e12: return f"${mcap/1e12:.2f}T"
    if mcap >= 1e9: return f"${mcap/1e9:.2f}B"
    if mcap >= 1e6: return f"${mcap/1e6:.2f}M"
    return f"${mcap}"

# ==============================================================================
# 1. NALAGANJE BAZE IZ CSV
# ==============================================================================
if not os.path.exists(CSV_DATOTEKA):
    print(f"[NAPAKA] Datoteka '{CSV_DATOTEKA}' ne obstaja! Najprej zaženi Korak 1.")
    os._exit(0)

df_baza = pd.read_csv(CSV_DATOTEKA)
vsi_izbrani_tickerji = df_baza['Ticker'].dropna().astype(str).str.strip().tolist()

tickerji_v_obdelavi = vsi_izbrani_tickerji
strong_buy_podatki_za_graf = {}

# ==============================================================================
# 2. ŽIVI SKENER
# ==============================================================================
def skeniraj_trg():
    print(f"\n[START] Začenjam skeniranje za {len(tickerji_v_obdelavi)} delnic...")
    print(f"        -> Kriterij 1: Market Cap > {MIN_MARKET_CAP/1e9:.0f}B")
    print(f"        -> Kriterij 2: Ocenjena rast prihodkov > {MIN_REVENUE_GROWTH*100:.0f}%")
    print(f"        -> Kriterij 3: Samo OGM > 65 (Super-Growth tudi mora izpolniti OGM > 65)")
    print(f"        -> Kriterij 4: Zaščita pred padanjem (20-day MA vs 200-week MA)")
    print("---------------------------------------------------------")
    
    trenutno_leto = datetime.now().year
    rezultati = []
    
    for krog, ticker in enumerate(tickerji_v_obdelavi, 1):
        if krog % 20 == 0:
            print(f"    ... obdelano {krog} / {len(tickerji_v_obdelavi)} delnic ...")
            
        try:
            delnica = yf.Ticker(ticker)
            
            try:
                info_podatki = delnica.info
                mcap = info_podatki.get('marketCap', None)
                rev_growth = info_podatki.get('revenueGrowth', None)
                ime_podjetja = info_podatki.get('shortName') or info_podatki.get('longName') or ticker
            except Exception:
                continue
                
            if mcap is None or pd.isna(mcap) or mcap < MIN_MARKET_CAP:
                continue
                
            rev_growth_val = float(rev_growth) if rev_growth is not None and not pd.isna(rev_growth) else 0.0
            mcap_prikaz = formatiraj_mcap(mcap)
            
            data = delnica.history(start="2014-01-01", interval="1wk", actions=False)
            
            if data is None or data.empty or len(data) < 205:
                continue
            
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
                
            close_series = data['Close'].dropna()
            if close_series.empty or len(close_series) < 205:
                continue
                
            # --- TEHNIČNI IZRAČUNI ---
            ma200 = close_series.rolling(window=200).mean()
            # Hitrejši obrat: 4 tedne je natančno 20 trgovalnih dni
            ma20 = close_series.rolling(window=4).mean()
            
            zadnji_ma200_weekly = float(ma200.iloc[-1])
            zadnji_ma20_weekly = float(ma20.iloc[-1])
            
            if zadnji_ma200_weekly == 0:
                continue
                
            pct_ma = ((close_series - ma200) / ma200) * 100

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
            
            tocke_ma[pos_mask] = np.interp(oddaljenost_arr[pos_mask], [0, 2, 10, 25, 50], [33.0, 35.0, 22.0, 8.0, 0.0])
            tocke_ma[neg_mask] = np.interp(oddaljenost_arr[neg_mask], [-20, -10, -5, 0], [0.0, 12.0, 25.0, 33.0])
            
            tocke_rsi = np.interp(rsi_arr, [30, 45, 60, 70, 80], [10.0, 8.0, 5.0, 2.0, 0.0])
            ogm_zgodovina = np.clip(tocke_ma + tocke_rsi + 45.0, 0, 100)
            
            trenutna_cena = float(close_series.iloc[-1])
            oddaljenost_ma_trenutna = float(oddaljenost_arr[-1])
            trenutni_ogm = float(ogm_zgodovina[-1])
            
            if pd.isna(oddaljenost_ma_trenutna) or pd.isna(trenutni_ogm): 
                continue
                
            trend_ok = oddaljenost_ma_trenutna >= 0
            
            is_falling_phase = zadnji_ma20_weekly < zadnji_ma200_weekly
            razmerje_trend = zadnji_ma20_weekly / zadnji_ma200_weekly
            
            donos_1m = ((trenutna_cena - float(close_series.iloc[-5])) / float(close_series.iloc[-5])) * 100
            
            vsi_datumi = close_series.index
            datumi_trenutnega_leta = vsi_datumi[vsi_datumi.year == trenutno_leto]
            try:
                if len(datumi_trenutnega_leta) > 0: cena_zacetek_leta = float(close_series.loc[datumi_trenutnega_leta[0]])
                else: cena_zacetek_leta = float(close_series.iloc[-22])
                donos_ytd = ((trenutna_cena - cena_zacetek_leta) / cena_zacetek_leta) * 100
            except Exception:
                donos_ytd = 0.0
            
            # --- STRATEŠKA KATEGORIZACIJA IN NOVI FILTRI ---
            # 1. Popolnoma izločimo vse, kar ima OGM pod 65 ali slabo rast
            if trenutni_ogm < 65.0 or rev_growth_val < MIN_REVENUE_GROWTH:
                continue 
                
            # 2. Določanje statusa za preživele (Warningi ohranijo svojo oznako)
            if is_falling_phase:
                status = "WARNING (FALLING PHASE)"
            elif not trend_ok:
                status = "WARNING (POD 200-MA)"
            elif trenutni_ogm >= 80.0:
                status = "STRONG BUY"
            elif rev_growth_val >= SUPER_GROWTH_THRESHOLD:
                status = "SUPER-GROWTH TARGET"
            else:
                status = "BUY"
            
            # --- ZGODOVINSKI BACKTEST IN PRIPRAVA GRAFA ZA VSE DELNICE ---
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
                        zgodovina_tabela.append({
                            "datum": datumi_str[i],
                            "cena": round(cena_ob_signalu, 2),
                            "max_cena": round(max_cena_12m, 2),
                            "max_donos": round(donos, 1)
                        })
                    zadnji_indeks_signala = i
            
            strong_buy_podatki_za_graf[ticker] = {
                "ime": ime_podjetja,
                "dates": datumi_str,
                "prices": np.round(close_series.values, 2).tolist(),
                "ogm": np.round(ogm_zgodovina, 1).tolist(),
                "history": zgodovina_tabela
            }
                
            rezultati.append({
                "Ticker": ticker, "Ime": ime_podjetja, "Cena": trenutna_cena, "OGM": trenutni_ogm,
                "Status": status, "1M_Donos": donos_1m, "YTD_Donos": donos_ytd,
                "MarketCap": mcap_prikaz, "Mcap_Raw": mcap, "RevGrowth": rev_growth_val * 100,
                "Ratio20_200": float(razmerje_trend)
            })
            
            time.sleep(0.04)
        except Exception:
            continue

    generiraj_html_porocilo(rezultati)

# ==============================================================================
# 3. GENERIRANJE HTML POROČILA
# ==============================================================================
def generiraj_html_porocilo(podatki):
    df_html = pd.DataFrame(podatki)
    if not df_html.empty:
        # ABSOLUTNA PRIORITETA: Tabela se sedaj razvrsti strogo po OGM od najvišjega navzdol.
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
    body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #1e293b; background-color: #f8fafc; margin: 40px auto; max-width: 1300px; padding: 0 20px; }}
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
    
    .modal {{ display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; overflow: auto; background-color: rgba(0,0,0,0.6); backdrop-filter: blur(4px); }}
    .modal-content {{ background-color: #fff; margin: 3% auto; padding: 25px; border-radius: 12px; width: 85%; max-width: 950px; box-shadow: 0 10px 25px rgba(0,0,0,0.2); position: relative; max-height: 85vh; overflow-y: auto; }}
    .close {{ color: #94a3b8; position: absolute; right: 20px; top: 15px; font-size: 28px; font-weight: bold; cursor: pointer; }}
    .close:hover {{ color: #0f172a; }}
    .chart-container {{ position: relative; height: 320px; width: 100%; margin-top: 20px; }}
    
    .history-table {{ margin-top: 25px; font-size: 8.5pt; width: 100%; border: 1px solid #e2e8f0; border-collapse: collapse; }}
    .history-table th {{ background-color: #f1f5f9; color: #475569; padding: 8px; }}
    .history-table td {{ padding: 8px; border-bottom: 1px solid #e2e8f0; }}
    
    .clickable-ticker {{ cursor: pointer; color: #1d4ed8; text-decoration: underline; font-weight: bold; }}
    .clickable-ticker:hover {{ color: #1e40af; }}
    .ime-podjetja {{ max-width: 180px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #475569; font-size: 8.5pt; }}
    
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
        <h1>OVNICEK GROWTH MATRIX &mdash; NASDAQ NAKUPNI RADAR</h1>
        <p>Filtri: Market Cap > 20B | Ocenjena rast prihodkov > 10% | Samo OGM > 65 | Osveženo: {datum_danes}</p>
        <p id="navodilo-klik" style="font-size: 9pt; color: #93c5fd; margin-top: 5px;">* Klikni na katerikoli tiker za grafično analizo in 10-letni zgodovinski backtest.</p>
        <button class="btn-pdf" onclick="window.print()">📥 Izvozi v PDF</button>
    </div>

    <table>
        <thead>
            <tr>
                <th>Ticker</th>
                <th>Ime podjetja</th>
                <th>Velikost (Market Cap)</th>
                <th>Pričakovana Rast</th>
                <th>Trend (20MA / 200MA)</th>
                <th>Trenutna cena</th>
                <th>Trenutni OGM Score</th>
                <th>Uradni status</th>
                <th>Performance (1M)</th>
                <th>Performance (YTD)</th>
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
            
            class_1m = "pos-return" if row['1M_Donos'] >= 0 else "neg-return"
            class_ytd = "pos-return" if row['YTD_Donos'] >= 0 else "neg-return"
            
            ticker_display = f'<span class="clickable-ticker" onclick="openAnalysis(\'{row['Ticker']}\')">{row['Ticker']} 📊</span>'
                
            html_content += f"""
                <tr>
                    <td>{ticker_display}</td>
                    <td><div class="ime-podjetja" title="{row['Ime']}">{row['Ime']}</div></td>
                    <td class="mcap-text">{row['MarketCap']}</td>
                    <td class="growth-text">{row['RevGrowth']:.1f} %</td>
                    <td style="font-weight:600; color:#475569;">{row['Ratio20_200']:.2f}x</td>
                    <td style="font-weight: 600;">${row['Cena']:.2f}</td>
                    <td style="font-weight: 700; font-size: 10pt; color: #0f172a;">{row['OGM']:.1f} / 100</td>
                    <td><span class="badge {badge_class}">{row['Status']}</span></td>
                    <td class="{class_1m}">{row['1M_Donos']:+.1f} %</td>
                    <td class="{class_ytd}">{row['YTD_Donos']:+.1f} %</td>
                </tr>
            """
    else:
        html_content += """<tr><td colspan="10" style="text-align:center;">Trenutno ni delnic, ki ustrezajo rigoroznim kriterijem filtra.</td></tr>"""
        
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
            
            <h3 style="margin-top: 25px; font-size: 10.5pt; color: #1e293b;">Zgodovina 10 let: Uspešnost preteklih prebojev OGM > 80</h3>
            <table class="history-table">
                <thead>
                    <tr>
                        <th>Datum preboja</th>
                        <th>Cena ob signalu</th>
                        <th>Maksimalna cena v 12m</th>
                        <th>Maksimalen 12m donos</th>
                    </tr>
                </thead>
                <tbody id="historyBody">
                </tbody>
            </table>
        </div>
    </div>

    <script>
    const chartData = {graf_json};
    let currentChart = null;

    function openAnalysis(ticker) {{
        const data = chartData[ticker];
        if (!data) return;
        
        document.getElementById('modalTitle').innerText = "OGM Analiza: " + ticker;
        document.getElementById('modalSubtitle').innerText = data.ime + " (Zadnjih 10 let)";
        
        const ctx = document.getElementById('ogmChart').getContext('2d');
        if (currentChart) {{ currentChart.destroy(); }}
        
        currentChart = new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: data.dates,
                datasets: [
                    {{
                        label: 'Cena Delnice ($)',
                        data: data.prices,
                        yAxisID: 'y',
                        borderColor: '#2563eb',
                        backgroundColor: 'rgba(37, 99, 235, 0.1)',
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: 0.1,
                        fill: true
                    }},
                    {{
                        label: 'OGM Score (0-100)',
                        data: data.ogm,
                        yAxisID: 'y1',
                        borderColor: '#16a34a',
                        borderWidth: 1.5,
                        pointRadius: 0,
                        tension: 0.3,
                        borderDash: [5, 5]
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{ mode: 'index', intersect: false }},
                scales: {{
                    x: {{ ticks: {{ maxTicksLimit: 12 }} }},
                    y: {{ type: 'linear', display: true, position: 'left', title: {{ display: true, text: 'Cena ($)' }} }},
                    y1: {{ type: 'linear', display: true, position: 'right', min: 0, max: 100, title: {{ display: true, text: 'OGM Točke' }}, grid: {{ drawOnChartArea: false }} }}
                }}
            }}
        }});

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

    function closeModal() {{
        document.getElementById('analysisModal').style.display = "none";
    }}

    window.onclick = function(event) {{
        const modal = document.getElementById('analysisModal');
        if (event.target == modal) {{
            modal.style.display = "none";
        }}
    }}
    </script>
    </body>
    </html>
    """
    
    html_content = html_content.replace("NaN", "0.0")
    
    ime_datoteke = "OGM_NASDAQ_EXPERT.html"
    with open(ime_datoteke, "w", encoding="utf-8") as f: 
        f.write(html_content)
    print(f"\n[USPEH] Profesionalno poročilo je ustvarjeno: '{ime_datoteke}'")
    webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

# Zagon skenerja
skeniraj_trg()