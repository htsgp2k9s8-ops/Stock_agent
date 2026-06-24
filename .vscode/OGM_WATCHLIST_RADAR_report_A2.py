import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import json
import webbrowser
import os
import time

print("=========================================================")
print("🎯 OGM WATCHLIST RADAR: VEČKRATNA DIAGNOSTIKA (MEGA-CAP V3)")
print("=========================================================")

# ==============================================================================
# STRATEŠKI INSTITUCIONALNI FILTRI
# ==============================================================================
MIN_MARKET_CAP = 20_000_000_000      # 20 milijard $ 
MEGA_CAP_THRESHOLD = 200_000_000_000 # 200 milijard $ (Za Mega-Cap/Mag7 pravilo 50w MA)
MIN_REVENUE_GROWTH = 0.10            
SUPER_GROWTH_THRESHOLD = 0.50        

def formatiraj_mcap(mcap):
    if mcap == 0 or pd.isna(mcap) or mcap is None: return "N/A"
    if mcap >= 1e12: return f"${mcap/1e12:.2f}T"
    if mcap >= 1e9: return f"${mcap/1e9:.2f}B"
    if mcap >= 1e6: return f"${mcap/1e6:.2f}M"
    return f"${mcap}"

def safe_float(val, default=0.0):
    try:
        if val is None or pd.isna(val): return default
        return float(val)
    except: return default

def zagon_watchlist_skenerja():
    vnos = input("\nVpiši tikerje delnic, ločene z vejico (npr. AAPL, TSLA, NVDA, SAP.DE): ")
    tickerji = [t.strip().upper() for t in vnos.split(',') if t.strip()]
    
    if not tickerji:
        print("Nisi vpisal nobenega tikerja. Izhod.")
        return
        
    print(f"\n[START] Analiziram podjetja: {', '.join(tickerji)}...")
    print("        -> V3 Mega-Cap pravilo (Strogi Pullback pogoji) AKTIVIRANO.")
    print("---------------------------------------------------------")
    
    trenutno_leto = datetime.now().year
    rezultati = []
    graf_podatki_vsi = {}
    
    for ticker in tickerji:
        print(f"Obdelujem: {ticker}")
        try:
            delnica = yf.Ticker(ticker)
            
            try:
                info_podatki = delnica.info
                mcap = info_podatki.get('marketCap')
                rev_growth = info_podatki.get('revenueGrowth')
                ime_podjetja = info_podatki.get('shortName') or info_podatki.get('longName') or ticker
                
                sektor = info_podatki.get('sector', 'Neznano')
                target_price = safe_float(info_podatki.get('targetMeanPrice'))
                if target_price == 0.0:
                    target_price = safe_float(info_podatki.get('targetMedianPrice'))
                    
                pe_ratio = safe_float(info_podatki.get('trailingPE'))
                if pe_ratio == 0.0:
                    pe_ratio = safe_float(info_podatki.get('forwardPE'))
                
                eps_growth = info_podatki.get('earningsQuarterlyGrowth') or info_podatki.get('earningsGrowth')
                peg_ratio = info_podatki.get('pegRatio')
                gross_margin = info_podatki.get('grossMargins')
                
            except Exception as e:
                print(f"    [!] Yahoo API blokada ali napaka pri {ticker}. Hladim (1s)...")
                time.sleep(1)
                continue
                
            razlogi = []
            if mcap is None or pd.isna(mcap) or mcap < MIN_MARKET_CAP:
                razlogi.append(f"Market Cap je premajhen ({formatiraj_mcap(mcap)} < 20B$).")
                
            rev_growth_val = safe_float(rev_growth)
            if rev_growth_val < MIN_REVENUE_GROWTH:
                razlogi.append(f"Pričakovana rast prihodkov je prenizka ({(rev_growth_val*100):.1f}% < 10%).")
                
            mcap_prikaz = formatiraj_mcap(mcap)
            is_mega_cap = mcap >= MEGA_CAP_THRESHOLD if mcap else False
            
            data = delnica.history(start="2014-01-01", interval="1wk", actions=False)
            if data is None or data.empty or len(data) < 205:
                razlogi.append("Podjetje nima dovolj dolge zgodovine na borzi (min 4 leta).")
            
            if razlogi and data is None:
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
            # TEHNIČNI TAJMING (V3 Mega-Cap pravila)
            # ==================================================================
            ma200 = close_series.rolling(window=200).mean()
            ma50 = close_series.rolling(window=50).mean()
            ma20 = close_series.rolling(window=4).mean()
            
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
                # V3 STROGI POGOJ (0 točk nad 15%)
                tocke_ma[pos_mask] = np.interp(oddaljenost_arr[pos_mask], [0, 2, 8, 15], [W_MA*(32/35), W_MA, W_MA*(15/35), 0.0])
                tocke_ma[neg_mask] = np.interp(oddaljenost_arr[neg_mask], [-40, -15, -2, 0], [W_MA, W_MA, W_MA*(34/35), W_MA*(32/35)])
            else:
                tocke_ma[pos_mask] = np.interp(oddaljenost_arr[pos_mask], [0, 2, 10, 25, 50], [W_MA*(33/35), W_MA, W_MA*(22/35), W_MA*(8/35), 0.0])
                tocke_ma[neg_mask] = np.interp(oddaljenost_arr[neg_mask], [-20, -10, -5, 0], [0.0, W_MA*(12/35), W_MA*(25/35), W_MA*(33/35)])
                
            tocke_rsi = np.interp(rsi_arr, [30, 45, 60, 70, 80], [W_RSI, W_RSI*0.8, W_RSI*0.5, W_RSI*0.2, 0.0])
            
            # TRDI ZAKLEP ZA MAKSIMALNIH 100 TOČK
            ogm_zgodovina = np.clip(tocke_ma + tocke_rsi + base_fundament_score, 0, 100.0)
            
            trenutna_cena = float(close_series.iloc[-1])
            oddaljenost_ma_trenutna = float(oddaljenost_arr[-1])
            trenutni_ogm = min(100.0, float(ogm_zgodovina[-1])) 
            
            if trenutni_ogm < 65.0:
                razlogi.append(f"OGM Score je prenizek ({trenutni_ogm:.1f} < 65).")
            
            status_barva = "#15803d" if not razlogi else "#dc2626"
            status_tekst = "SPREJETO (USTREZA FILTROM)" if not razlogi else "ZAVRNJENO (NE USTREZA FILTROM)"
            razlogi_html = "".join([f"<li>{r}</li>" for r in razlogi]) if razlogi else "<li>Vsi strateški in OGM filtri so uspešno prestani.</li>"
            
            # ==================================================================
            # IZRACUN SEZONSKOSTI IN TRENDOV
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
            
            graf_podatki_vsi[ticker] = {
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
                    "total_score": float(trenutni_ogm),
                    "ma_type": tip_ma
                }
            }
                
            rezultati.append({
                "Ticker": ticker, 
                "Ime": ime_podjetja, 
                "Sektor": sektor, 
                "TargetPrice": target_price,
                "Cena": trenutna_cena, 
                "OGM": trenutni_ogm,
                "Status": status, 
                "StatusBarva": status_barva,
                "StatusTekst": status_tekst,
                "RazlogiHtml": razlogi_html,
                "MarketCap": mcap_prikaz, 
                "RevGrowth": rev_growth_val * 100,
                "DistMA": oddaljenost_ma_trenutna,
                "MaType": tip_ma,
                "RSI": float(rsi_arr[-1])
            })
            
            time.sleep(0.04)
        except Exception as e:
            continue

    if rezultati:
        generiraj_html_porocilo(rezultati, graf_podatki_vsi)
    else:
        print("Ni bilo uspešno prenesenih nobenih delnic.")

# ==============================================================================
# HTML GENERATOR POROČILA
# ==============================================================================
def generiraj_html_porocilo(podatki, graf_podatki_vsi):
    datum_danes = datetime.now().strftime("%d.%m.%Y")
    
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>OGM Watchlist Radar</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f8fafc; color: #1e293b; margin: 40px auto; max-width: 1400px; padding: 0 20px; }}
    .header {{ background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 100%); color: #ffffff; padding: 30px; border-radius: 8px; margin-bottom: 30px; position: relative; }}
    .header h1 {{ margin: 0; font-size: 24pt; }}
    .header p {{ margin: 5px 0 0 0; color: #bfdbfe; font-size: 11pt; }}
    
    .btn-pdf {{ position: absolute; right: 30px; top: 35px; background-color: #ef4444; color: white; border: none; padding: 12px 20px; border-radius: 6px; font-weight: 700; font-size: 10pt; cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: 0.2s; }}
    .btn-pdf:hover {{ background-color: #dc2626; transform: translateY(-1px); }}
    
    .card {{ background: white; border-radius: 12px; padding: 25px; margin-bottom: 30px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; }}
    .card-header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #e2e8f0; padding-bottom: 15px; margin-bottom: 20px; }}
    .card-title {{ font-size: 18pt; font-weight: bold; color: #0f172a; margin: 0; }}
    .card-subtitle {{ font-size: 11pt; color: #64748b; margin-top: 5px; }}
    
    .status-badge {{ padding: 8px 16px; border-radius: 6px; font-weight: bold; font-size: 10pt; color: white; }}
    
    .grid-metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }}
    .metric-box {{ background: #f8fafc; padding: 15px; border-radius: 8px; border: 1px solid #e2e8f0; text-align: center; }}
    .metric-box.highlight {{ background: #eff6ff; border-color: #bfdbfe; }}
    .metric-label {{ font-size: 9pt; color: #64748b; text-transform: uppercase; margin-bottom: 5px; }}
    .metric-val {{ font-size: 16pt; font-weight: bold; color: #0f172a; }}
    .val-green {{ color: #16a34a; }}
    .val-red {{ color: #dc2626; }}
    
    .filter-box {{ background: #f1f5f9; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #94a3b8; }}
    .filter-box h4 {{ margin: 0 0 10px 0; color: #334155; font-size: 10pt; text-transform: uppercase; }}
    .filter-box ul {{ margin: 0; padding-left: 20px; font-size: 9.5pt; color: #475569; }}
    
    .chart-container {{ position: relative; height: 350px; width: 100%; margin-bottom: 25px; }}
    
    .grid-2col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
    
    table {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; }}
    th {{ background-color: #f1f5f9; color: #475569; padding: 10px; text-align: left; border-bottom: 2px solid #e2e8f0; }}
    td {{ padding: 10px; border-bottom: 1px solid #e2e8f0; }}
    
    .heatmap-table th, .heatmap-table td {{ text-align: center; padding: 6px; font-size: 8.5pt; }}
    
    @media print {{
        body {{ background-color: white; margin: 0; padding: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
        .btn-pdf {{ display: none !important; }}
        .card {{ box-shadow: none; border: 1px solid #cbd5e1; page-break-inside: avoid; margin-bottom: 20px; }}
        .chart-container {{ page-break-inside: avoid; }}
    }}
    </style>
    </head>
    <body>

    <div class="header">
        <h1>🎯 OGM Watchlist Radar: Diagnostika Izbranih Delnic</h1>
        <p>Preverjanje po Mega-Cap V3 pravilih (Strogi Pullback Odklep) | Generirano: {datum_danes}</p>
        <button class="btn-pdf" onclick="window.print()">📥 Izvozi v PDF</button>
    </div>
    """
    
    for row in podatki:
        dist_class = "val-green" if 0 <= row['DistMA'] <= 5 else ("val-red" if row['DistMA'] < 0 else "")
        
        html_template += f"""
        <div class="card">
            <div class="card-header">
                <div>
                    <h2 class="card-title">{row['Ticker']} - {row['Ime']}</h2>
                    <div class="card-subtitle">{row['Sektor']} | Ciljna cena: ${row['TargetPrice']:.2f}</div>
                </div>
                <div class="status-badge" style="background-color: {row['StatusBarva']};">{row['StatusTekst']}</div>
            </div>
            
            <div class="filter-box" style="border-left-color: {row['StatusBarva']};">
                <h4>Status OGM Filtrov:</h4>
                <ul>
                    {row['RazlogiHtml']}
                </ul>
            </div>
            
            <div class="grid-metrics">
                <div class="metric-box highlight">
                    <div class="metric-label">Trenutni OGM Score</div>
                    <div class="metric-val" style="color: #1d4ed8;">{row['OGM']:.1f} / 100</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Trenutna Cena</div>
                    <div class="metric-val">${row['Cena']:.2f}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Oddaljenost od {row['MaType']}</div>
                    <div class="metric-val {dist_class}">{row['DistMA']:+.1f} %</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Market Cap</div>
                    <div class="metric-val">{row['MarketCap']}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">RSI (14w)</div>
                    <div class="metric-val">{row['RSI']:.1f}</div>
                </div>
            </div>
            
            <div class="chart-container">
                <canvas id="chart_{row['Ticker']}"></canvas>
            </div>
            
            <div class="grid-2col">
                <div>
                    <h3 style="font-size: 11pt; border-bottom: 1px solid #e2e8f0; padding-bottom: 5px;">OGM Komponente (Struktura Točk)</h3>
                    <table id="comp_{row['Ticker']}">
                        </table>
                </div>
                <div>
                    <h3 style="font-size: 11pt; border-bottom: 1px solid #e2e8f0; padding-bottom: 5px;">Mesečna Sezonskost (Heatmap)</h3>
                    <div id="heatmap_{row['Ticker']}" style="overflow-x: auto;">
                        </div>
                </div>
            </div>
        </div>
        """
        
    js_template = """
    <script>
    const chartData = GRAF_DATA_PLACEHOLDER;
    
    Object.keys(chartData).forEach(ticker => {
        const data = chartData[ticker];
        
        // Nariši graf
        const ctx = document.getElementById('chart_' + ticker).getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.dates,
                datasets: [
                    { label: 'Cena ($)', data: data.prices, yAxisID: 'y', borderColor: '#2563eb', backgroundColor: 'rgba(37, 99, 235, 0.1)', borderWidth: 2, pointRadius: 0, tension: 0.1, fill: true },
                    { label: 'OGM Score', data: data.ogm, yAxisID: 'y1', borderColor: '#16a34a', borderWidth: 1.5, pointRadius: 0, tension: 0.3, borderDash: [5, 5] }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
                scales: {
                    x: { ticks: { maxTicksLimit: 12 } },
                    y: { type: 'linear', display: true, position: 'left' },
                    y1: { type: 'linear', display: true, position: 'right', min: 0, max: 100, grid: { drawOnChartArea: false } }
                }
            }
        });
        
        // Zgradi tabelo komponent
        let compHTML = `
            <tr><th>Faktor</th><th>Vrednost</th><th>Dodeljene točke</th></tr>
            <tr><td>Rast EPS</td><td>${data.components.eps_growth_raw.toFixed(1)} %</td><td style="font-weight:bold;">${data.components.eps_growth_score.toFixed(1)} / 20</td></tr>
            <tr><td>PEG Ratio</td><td>${data.components.peg_raw.toFixed(2)}</td><td style="font-weight:bold;">${data.components.peg_score.toFixed(1)} / 15</td></tr>
            <tr><td>Bruto Marža</td><td>${data.components.margin_raw.toFixed(1)} %</td><td style="font-weight:bold;">${data.components.margin_score.toFixed(1)} / 10</td></tr>
            <tr><td>RSI (14w)</td><td>${data.components.rsi_raw.toFixed(1)}</td><td style="font-weight:bold;">${data.components.rsi_score.toFixed(1)} / 15</td></tr>
            <tr><td>Oddaljenost od ${data.components.ma_type}</td><td>${data.components.ma_dist_raw.toFixed(1)} %</td><td style="font-weight:bold;">${data.components.ma_dist_score.toFixed(1)} / 40</td></tr>
            <tr style="background-color: #f8fafc; font-weight: bold; font-size: 10.5pt; color: #0f172a;"><td>SKUPAJ OGM</td><td>-</td><td>${data.components.total_score.toFixed(1)} / 100</td></tr>
        `;
        document.getElementById('comp_' + ticker).innerHTML = compHTML;
        
        // Zgradi heatmap
        let monthlyHTML = '<table class="heatmap-table"><tr><th>Leto</th>';
        const meseci = ['Jan', 'Feb', 'Mar', 'Apr', 'Maj', 'Jun', 'Jul', 'Avg', 'Sep', 'Okt', 'Nov', 'Dec'];
        meseci.forEach(m => monthlyHTML += `<th>${m}</th>`);
        monthlyHTML += '</tr>';
        
        let years = Object.keys(data.monthly).map(Number).sort((a,b) => b - a);
        years.slice(0, 8).forEach(y => {
            monthlyHTML += `<tr><td style="font-weight:bold; color:#475569;">${y}</td>`;
            for(let m=1; m<=12; m++) {
                let val = data.monthly[y][m];
                if (val !== undefined) {
                    let color = val >= 0 ? '#15803d' : '#b91c1c';
                    let bg = val >= 0 ? 'rgba(22, 163, 74, 0.1)' : 'rgba(220, 38, 38, 0.1)';
                    monthlyHTML += `<td style="color: ${color}; background-color: ${bg};">${val>0?'+':''}${val.toFixed(1)}%</td>`;
                } else {
                    monthlyHTML += `<td style="color:#cbd5e1;">-</td>`;
                }
            }
            monthlyHTML += '</tr>';
        });
        monthlyHTML += '</table>';
        document.getElementById('heatmap_' + ticker).innerHTML = monthlyHTML;
    });
    </script>
    </body>
    </html>
    """
    
    js_template = js_template.replace("GRAF_DATA_PLACEHOLDER", json.dumps(graf_podatki_vsi))
    html_content = html_template + js_template
    
    ime_datoteke = "OGM_WATCHLIST_REPORT_ADVANCED.html"
    with open(ime_datoteke, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"\n[USPEH] Watchlist diagnostika ustvarjena: '{ime_datoteke}'")
    webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

if __name__ == "__main__":
    zagon_watchlist_skenerja()