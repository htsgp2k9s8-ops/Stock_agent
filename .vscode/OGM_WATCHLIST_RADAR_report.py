import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import json
import webbrowser
import os

print("=========================================================")
print("🎯 OGM WATCHLIST RADAR: VEČKRATNA DIAGNOSTIKA")
print("=========================================================")

# Strategijski filtri
MIN_MARKET_CAP = 20_000_000_000
MIN_REVENUE_GROWTH = 0.10

def formatiraj_mcap(mcap):
    if mcap == 0 or pd.isna(mcap) or mcap is None: return "N/A"
    if mcap >= 1e12: return f"${mcap/1e12:.2f}T"
    if mcap >= 1e9: return f"${mcap/1e9:.2f}B"
    if mcap >= 1e6: return f"${mcap/1e6:.2f}M"
    return f"${mcap}"

def zagon_watchlist_skenerja():
    vnos = input("\nVpiši tikerje delnic, ločene z vejico (npr. AAPL, TSLA, NVDA, SAP.DE): ")
    tickerji = [t.strip().upper() for t in vnos.split(',') if t.strip()]
    
    if not tickerji:
        print("Nisi vpisal nobenega tikerja. Izhod.")
        return
        
    print(f"\nZačenjam obsežno analizo za {len(tickerji)} delnic(e)...")
    print("-" * 60)
    
    vsi_rezultati = []
    graf_podatki_vsi = {}
    
    for ticker in tickerji:
        print(f"Analiziram: {ticker} ... ", end="")
        try:
            delnica = yf.Ticker(ticker)
            razlogi = []
            
            # 1. Fundamenti
            info = delnica.info
            mcap = info.get('marketCap', None)
            rev_growth = info.get('revenueGrowth', None)
            ime = info.get('shortName') or info.get('longName') or ticker
            
            mcap_val = 0 if mcap is None else float(mcap)
            mcap_str = formatiraj_mcap(mcap_val)
            if mcap_val < MIN_MARKET_CAP:
                razlogi.append("Premajhna tržna kapitalizacija (Market Cap < 20B$).")
                
            rev_growth_val = 0.0 if rev_growth is None else float(rev_growth)
            if rev_growth_val < MIN_REVENUE_GROWTH:
                razlogi.append("Pričakovana rast prihodkov je pod 10 % (ali pa podatka ni).")
                
            # 2. Zgodovina
            data = delnica.history(start="2014-01-01", interval="1wk", actions=False)
            if data is None or data.empty or len(data) < 205:
                razlogi.append("Ni dovolj dolge zgodovine za izračun 200-tedenskega povprečja.")
                vsi_rezultati.append({
                    "ticker": ticker, "ime": ime, "mcap_str": mcap_str, "rev_growth": rev_growth_val,
                    "razlogi": razlogi, "diag": None, "ima_zgodovino": False
                })
                print("[PREKRATEK GRAF]")
                continue
                
            # 3. Tehnični izračuni
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            close_series = data['Close'].dropna()
            
            ma200 = close_series.rolling(window=200).mean()
            ma20 = close_series.rolling(window=4).mean()
            
            zadnji_ma200 = float(ma200.iloc[-1])
            zadnji_ma20 = float(ma20.iloc[-1])
            trenutna_cena = float(close_series.iloc[-1])
            
            pct_ma = ((close_series - ma200) / ma200) * 100
            delta = close_series.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            tocke_ma = np.zeros_like(pct_ma.values)
            pos_mask = pct_ma.values >= 0
            neg_mask = pct_ma.values < 0
            tocke_ma[pos_mask] = np.interp(pct_ma.values[pos_mask], [0, 2, 10, 25, 50], [33.0, 35.0, 22.0, 8.0, 0.0])
            tocke_ma[neg_mask] = np.interp(pct_ma.values[neg_mask], [-20, -10, -5, 0], [0.0, 12.0, 25.0, 33.0])
            tocke_rsi = np.interp(rsi.values, [30, 45, 60, 70, 80], [10.0, 8.0, 5.0, 2.0, 0.0])
            ogm = np.clip(tocke_ma + tocke_rsi + 45.0, 0, 100)
            
            trenutni_ogm = float(ogm[-1])
            trenutni_pct_ma = float(pct_ma.iloc[-1])
            trenutni_rsi = float(rsi.iloc[-1])
            
            trend_ok = (trenutna_cena >= zadnji_ma200)
            is_falling_phase = (zadnji_ma20 < zadnji_ma200)
            
            # Analiza
            if trenutni_pct_ma < 0: ma_razlaga = "Cena je POD 200-tedenskim povprečjem. Trend je negativen."
            elif trenutni_pct_ma > 50: ma_razlaga = "Delnica je preveč oddaljena od povprečja (>50%). Je 'pregreta'."
            elif trenutni_pct_ma > 25: ma_razlaga = "Delnica je v močnem trendu, a nekoliko preveč oddaljena od idealne točke nakupa."
            else: ma_razlaga = "Delnica se nahaja v idealnem območju blizu 200-tedenskega povprečja."
                
            if trenutni_rsi > 70: rsi_razlaga = "RSI je visok (prekupljenost). Zagon morda pojenja."
            elif trenutni_rsi < 40: rsi_razlaga = "RSI je prenizek (šibek momentum). Delnica nima moči."
            else: rsi_razlaga = "RSI kaže na zdrav in stabilen momentum brez pregrevanja."

            if trenutni_ogm < 65.0:
                razlogi.append(f"Skupni OGM Score ({trenutni_ogm:.1f}) je pod mejo 65 točk.")
                
            diag = {
                "ogm_skupaj": trenutni_ogm, "tocke_ma": float(tocke_ma[-1]), "pct_ma": trenutni_pct_ma, "ma_razlaga": ma_razlaga,
                "tocke_rsi": float(tocke_rsi[-1]), "rsi": trenutni_rsi, "rsi_razlaga": rsi_razlaga,
                "is_falling": is_falling_phase, "trend_ok": trend_ok, "cena": trenutna_cena,
                "ma20": zadnji_ma20, "ma200": zadnji_ma200
            }
            
            # Backtest zgodovina
            datumi_str = [d.strftime("%Y-%m-%d") for d in close_series.index]
            zgodovina_tabela = []
            zadnji_indeks = -999
            for i in range(len(ogm)):
                if ogm[i] >= 80.0 and (i - zadnji_indeks) > 26:
                    cena_ob = close_series.iloc[i]
                    if i + 52 < len(close_series): max_c = close_series.iloc[i:i+52].max()
                    else: max_c = close_series.iloc[i:].max() if i + 1 < len(close_series) else cena_ob
                    donos = ((max_c - cena_ob) / cena_ob) * 100
                    if i + 52 < len(close_series):
                        zgodovina_tabela.append({
                            "datum": datumi_str[i], "cena": round(cena_ob, 2),
                            "max_cena": round(max_c, 2), "max_donos": round(donos, 1)
                        })
                    zadnji_indeks = i
                    
            graf_podatki_vsi[ticker] = {
                "dates": datumi_str,
                "prices": np.round(close_series.values, 2).tolist(),
                "ma200": np.round(ma200.values, 2).tolist(),
                "ma20": np.round(ma20.values, 2).tolist(),
                "ogm": np.round(ogm, 1).tolist(),
                "history": zgodovina_tabela,
                "has_data": True
            }
            
            vsi_rezultati.append({
                "ticker": ticker, "ime": ime, "mcap_str": mcap_str, "rev_growth": rev_growth_val,
                "razlogi": razlogi, "diag": diag, "ima_zgodovino": True
            })
            print("[OK]")
            
        except Exception as e:
            print(f"[NAPAKA: {e}]")
            
    # ZDRUŽITEV V HTML
    generiraj_html_watchlist(vsi_rezultati, graf_podatki_vsi)

def generiraj_html_watchlist(rezultati, graf_podatki_vsi):
    if not rezultati:
        print("Ni bilo uspešno prenesenih podatkov. Izhod.")
        return
        
    print("\nGeneriram zbirno HTML in PDF poročilo...")
    datum_danes = datetime.now().strftime("%d.%m.%Y ob %H:%M")
    
    html_sections = ""
    for res in rezultati:
        ticker = res['ticker']
        ime = res['ime']
        razlogi = res['razlogi']
        diag = res['diag']
        
        status_barva = "#16a34a" if not razlogi else "#dc2626"
        status_tekst = "SPREJETO (USTREZA FILTROM)" if not razlogi else "ZAVRNJENO (NE USTREZA FILTROM)"
        razlogi_html = "".join([f"<li>{r}</li>" for r in razlogi]) if razlogi else "<li>✓ Nobenih prekrškov. Delnica ustreza vsem kriterijem.</li>"
        
        html_sections += f"""
        <div class="stock-wrapper">
            <div class="header-stock">
                <h2>{ime} ({ticker})</h2>
                <div class="status-badge" style="background-color: {status_barva};">{status_tekst}</div>
            </div>
        """
        
        if res['ima_zgodovino'] and diag:
            warn_padanje = 'DA ⚠️' if diag['is_falling'] else 'NE ✓'
            warn_trend = 'DA ⚠️' if not diag['trend_ok'] else 'NE ✓'
            
            html_sections += f"""
            <div class="grid-container">
                <div class="card">
                    <h3>1. Temeljni Filtri & Diagnoza</h3>
                    <p><strong>Market Cap:</strong> {res['mcap_str']} <em>(Pogoj: > 20B)</em></p>
                    <p><strong>Rast prihodkov:</strong> {res['rev_growth']*100:.1f} % <em>(Pogoj: > 10%)</em></p>
                    <h4 style="margin-top: 15px;">Zakaj delnica NI na glavnem radarju?</h4>
                    <ul class="razlogi">{razlogi_html}</ul>
                    <h4 style="margin-top: 15px;">Tehnični opozorilni znaki:</h4>
                    <p>Faza padanja (20MA &lt; 200MA): <strong>{warn_padanje}</strong></p>
                    <p>Zlomljen dolgoročni trend: <strong>{warn_trend}</strong></p>
                </div>

                <div class="card">
                    <h3>2. Anatomija OGM Faktorja</h3>
                    <div class="ogm-velik">{diag['ogm_skupaj']:.1f} / 100</div>
                    <p><strong>Osnova (Fundamenti):</strong> 45.0 točk</p>
                    <p><strong>Trend (Oddaljenost od 200-MA):</strong> {diag['tocke_ma']:.1f} / 35.0 točk</p>
                    <div class="razlaga-box">
                        <em>Oddaljenost: {diag['pct_ma']:+.1f}%</em><br>
                        <strong>Diagnoza:</strong> {diag['ma_razlaga']}
                    </div>
                    <p><strong>Momentum (RSI 14-tedenski):</strong> {diag['tocke_rsi']:.1f} / 10.0 točk</p>
                    <div class="razlaga-box">
                        <em>RSI: {diag['rsi']:.1f}</em><br>
                        <strong>Diagnoza:</strong> {diag['rsi_razlaga']}
                    </div>
                </div>
            </div>
            
            <div class="chart-container">
                <canvas id="chart_{ticker}"></canvas>
            </div>

            <div class="card" style="margin-bottom: 0;">
                <h3>3. Uspešnost preteklih prebojev OGM > 80 (Backtest)</h3>
                <table class="history-table">
                    <thead>
                        <tr>
                            <th>Datum preboja</th>
                            <th>Cena ob signalu</th>
                            <th>Maks. cena v 12m</th>
                            <th>Maks. 12m donos</th>
                        </tr>
                    </thead>
                    <tbody id="historyBody_{ticker}"></tbody>
                </table>
            </div>
            """
        else:
            html_sections += f"""
            <div class="card">
                <h3>Napaka pri pridobivanju tehničnih podatkov</h3>
                <p>Podjetje ima prekratko zgodovino ali manjkajoče podatke.</p>
                <ul class="razlogi">{razlogi_html}</ul>
            </div>
            """
            
        html_sections += "</div>" # Konec stock-wrapperja

    # HTML TEMPLATE
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>OGM Watchlist Poročilo</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #e2e8f0; color: #1e293b; padding: 20px; max-width: 1200px; margin: 0 auto; }}
    .main-header {{ background: linear-gradient(135deg, #1e1b4b 0%, #4338ca 100%); color: white; padding: 30px; border-radius: 8px; margin-bottom: 30px; position: relative; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
    .main-header h1 {{ margin: 0; font-size: 26pt; }}
    .main-header p {{ margin: 5px 0 0 0; color: #c7d2fe; }}
    
    .btn-pdf {{ position: absolute; right: 30px; top: 35px; background-color: #ef4444; color: white; border: none; padding: 12px 20px; border-radius: 6px; font-weight: 700; font-size: 10pt; cursor: pointer; transition: 0.2s; }}
    .btn-pdf:hover {{ background-color: #dc2626; }}
    
    .stock-wrapper {{ background-color: #ffffff; padding: 30px; border-radius: 12px; margin-bottom: 40px; box-shadow: 0 10px 20px rgba(0,0,0,0.05); }}
    .header-stock {{ border-bottom: 2px solid #e2e8f0; padding-bottom: 15px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }}
    .header-stock h2 {{ margin: 0; color: #0f172a; font-size: 20pt; }}
    .status-badge {{ color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 10pt; }}
    
    .grid-container {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 25px; }}
    .card {{ background-color: #f8fafc; padding: 20px; border-radius: 8px; border: 1px solid #e2e8f0; }}
    .card h3 {{ margin-top: 0; color: #334155; border-bottom: 1px solid #cbd5e1; padding-bottom: 8px; font-size: 12pt; }}
    
    .ogm-velik {{ font-size: 28pt; font-weight: bold; color: #1d4ed8; text-align: center; margin: 10px 0; }}
    .razlaga-box {{ background-color: #ffffff; padding: 10px; border-left: 4px solid #3b82f6; border-radius: 4px; margin-bottom: 10px; font-size: 9pt; border: 1px solid #e2e8f0; }}
    
    ul.razlogi {{ color: #dc2626; font-weight: 600; font-size: 9.5pt; padding-left: 20px; }}
    
    .chart-container {{ background-color: white; padding: 15px; border-radius: 8px; border: 1px solid #e2e8f0; height: 380px; margin-bottom: 25px; }}
    
    .history-table {{ font-size: 8.5pt; width: 100%; border: 1px solid #cbd5e1; border-collapse: collapse; background-color: white; }}
    .history-table th {{ background-color: #e2e8f0; color: #334155; padding: 8px; text-align: left; }}
    .history-table td {{ padding: 8px; border-bottom: 1px solid #e2e8f0; }}
    
    @media print {{
        body {{ background-color: white; padding: 0; margin: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
        .main-header {{ border-radius: 0; box-shadow: none; margin-bottom: 20px; }}
        .btn-pdf {{ display: none !important; }}
        .stock-wrapper {{ box-shadow: none; border: 1px solid #cbd5e1; margin-bottom: 20px; page-break-after: always; }}
        .grid-container {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }}
        .card, .chart-container {{ page-break-inside: avoid; border: 1px solid #cbd5e1; }}
    }}
    </style>
    </head>
    <body>

    <div class="main-header">
        <h1>OGM Osebni Watchlist Radar</h1>
        <p>Poglobljena diagnostika za tvoje izbrane delnice | Generirano: {datum_danes}</p>
        <button class="btn-pdf" onclick="window.print()">📥 Izvozi poročilo v PDF</button>
    </div>

    {html_sections}

    """

    js_template = """
    <script>
    const allData = GRAF_DATA_PLACEHOLDER;
    
    Object.keys(allData).forEach(ticker => {
        const data = allData[ticker];
        if (data.has_data) {
            // Risanje grafa
            const ctx = document.getElementById('chart_' + ticker).getContext('2d');
            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: data.dates,
                    datasets: [
                        { label: 'Cena ($)', data: data.prices, yAxisID: 'y', borderColor: '#0f172a', borderWidth: 2, pointRadius: 0, tension: 0.1 },
                        { label: '200-Week MA', data: data.ma200, yAxisID: 'y', borderColor: '#dc2626', borderWidth: 2, borderDash: [5, 5], pointRadius: 0 },
                        { label: '20-Day MA', data: data.ma20, yAxisID: 'y', borderColor: '#f59e0b', borderWidth: 1.5, pointRadius: 0 },
                        { label: 'OGM Score', data: data.ogm, yAxisID: 'y1', borderColor: '#16a34a', backgroundColor: 'rgba(22, 163, 74, 0.1)', borderWidth: 1.5, pointRadius: 0, fill: true }
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

            // Polnjenje backtest tabele
            const tbody = document.getElementById('historyBody_' + ticker);
            if (!data.history || data.history.length === 0) {
                tbody.innerHTML = "<tr><td colspan='4' style='text-align:center; color:#64748b;'>Ni signalov preboja (>80) v zadnjih 10 letih.</td></tr>";
            } else {
                data.history.forEach(row => {
                    const colorClass = row.max_donos >= 0 ? "color: #16a34a; font-weight:bold;" : "color: #dc2626; font-weight:bold;";
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td>${row.datum}</td>
                        <td>$${row.cena.toFixed(2)}</td>
                        <td>$${row.max_cena.toFixed(2)}</td>
                        <td style="${colorClass}">+${row.max_donos.toFixed(1)} %</td>
                    `;
                    tbody.appendChild(tr);
                });
            }
        }
    });
    </script>
    </body>
    </html>
    """
    
    js_template = js_template.replace("GRAF_DATA_PLACEHOLDER", json.dumps(graf_podatki_vsi))
    html_content = html_template + js_template
    
    ime_datoteke = "OGM_WATCHLIST_REPORT.html"
    with open(ime_datoteke, "w", encoding="utf-8") as f: 
        f.write(html_content)
    print(f"\n[USPEH] Watchlist poročilo je ustvarjeno: '{ime_datoteke}'")
    webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

if __name__ == "__main__":
    zagon_watchlist_skenerja()