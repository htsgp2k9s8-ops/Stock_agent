import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import json
import webbrowser
import os

print("=========================================================")
print("🔍 OGM DIAGNOSTIKA: RAZČLENITEV, VIZUALIZACIJA IN PDF")
print("=========================================================")

# Strategijski filtri iz glavnega radarja
MIN_MARKET_CAP = 20_000_000_000
MIN_REVENUE_GROWTH = 0.10

def formatiraj_mcap(mcap):
    if mcap == 0 or pd.isna(mcap) or mcap is None: return "N/A"
    if mcap >= 1e12: return f"${mcap/1e12:.2f}T"
    if mcap >= 1e9: return f"${mcap/1e9:.2f}B"
    if mcap >= 1e6: return f"${mcap/1e6:.2f}M"
    return f"${mcap}"

def diagnosticiraj_delnico():
    ticker = input("\nVpiši tiker delnice za analizo (npr. SAP.DE, TSLA, NVDA): ").strip().upper()
    print(f"\nPridobivam žive podatke za {ticker}... Prosim počakaj.\n")
    print("-" * 60)
    
    delnica = yf.Ticker(ticker)
    razlogi_za_zavrnitev = []
    
    # 1. OSNOVNI PODATKI IN FUNDAMENTI
    try:
        info = delnica.info
        mcap = info.get('marketCap', None)
        rev_growth = info.get('revenueGrowth', None)
        ime = info.get('shortName') or info.get('longName') or ticker
    except Exception as e:
        print(f"❌ KRITIČNA NAPAKA: Ni mogoče pridobiti osnovnih podatkov z Yahoo Finance ({e}).")
        return

    print(f"🏢 PODJETJE: {ime} ({ticker})")
    
    # Preverjanje Market Cap
    mcap_val = 0 if mcap is None else float(mcap)
    mcap_str = formatiraj_mcap(mcap_val)
    if mcap_val >= MIN_MARKET_CAP:
        print(f"✅ MARKET CAP: {mcap_str} (Ustreza pogoju > 20B $)")
    else:
        print(f"❌ MARKET CAP: {mcap_str} (PREMAJHNO! Zahtevano je > 20B $)")
        razlogi_za_zavrnitev.append("Premajhna tržna kapitalizacija (Market Cap < 20B$).")

    # Preverjanje Revenue Growth
    rev_growth_val = 0.0 if rev_growth is None else float(rev_growth)
    if rev_growth_val >= MIN_REVENUE_GROWTH:
        print(f"✅ RAST PRIHODKOV: {rev_growth_val*100:.1f} % (Ustreza pogoju > 10 %)")
    else:
        print(f"❌ RAST PRIHODKOV: {rev_growth_val*100:.1f} % (PRENIZKO! Zahtevano je > 10 %)")
        razlogi_za_zavrnitev.append("Pričakovana rast prihodkov je pod 10 % (ali pa podatka ni).")

    # 2. TEHNIČNI PODATKI (Zgodovina)
    data = delnica.history(start="2014-01-01", interval="1wk", actions=False)
    if data is None or data.empty or len(data) < 205:
        print(f"❌ ZGODOVINA: Podjetje nima dovolj dolge zgodovine na borzi (zahtevano 205 tednov, ima {len(data) if data is not None else 0}).")
        razlogi_za_zavrnitev.append("Ni dovolj dolge zgodovine za izračun 200-tedenskega povprečja.")
        izpisi_zakljucek_in_generiraj_html(ticker, ime, mcap_str, rev_growth_val, razlogi_za_zavrnitev, None, None)
        return
    else:
        print(f"✅ ZGODOVINA: Na voljo je dovolj podatkov ({len(data)} tednov).")

    # 3. OGM IZRAČUN IN RAZČLENITEV
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    close_series = data['Close'].dropna()
    
    ma200 = close_series.rolling(window=200).mean()
    ma20 = close_series.rolling(window=4).mean() # 4 tedne = 20 dni
    
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
    trenutne_tocke_ma = float(tocke_ma[-1])
    trenutne_tocke_rsi = float(tocke_rsi[-1])
    
    trend_ok = (trenutna_cena >= zadnji_ma200)
    is_falling_phase = (zadnji_ma20 < zadnji_ma200)
    
    print("-" * 60)
    print(f"📊 OGM SCORE RAZČLENITEV: {trenutni_ogm:.1f} / 100")
    print(f"   [+] Baza (Fundamenti): 45.0 točk")
    
    # Detajlna razlaga MA točk
    print(f"   [+] Trend (Oddaljenost od 200-MA): {trenutne_tocke_ma:.1f} točk (Maksimalno 35)")
    print(f"       -> Dejanska oddaljenost: {trenutni_pct_ma:+.1f} %")
    ma_razlaga = ""
    if trenutni_pct_ma < 0:
        ma_razlaga = "Cena je POD 200-tedenskim povprečjem. Trend je negativen, kar drastično zniža oceno."
    elif trenutni_pct_ma > 50:
        ma_razlaga = "Delnica je preveč oddaljena od povprečja (>50%). Je 'pregreta' (overextended) in visoko tvegana za popravek, zato izgubi točke."
    elif trenutni_pct_ma > 25:
        ma_razlaga = "Delnica je v močnem trendu, a nekoliko preveč oddaljena od idealne točke nakupa (baze)."
    else:
        ma_razlaga = "Delnica se nahaja v idealnem območju blizu 200-tedenskega povprečja (odlična točka vstopa)."
    print(f"       -> DIAGNOZA: {ma_razlaga}")
    
    # Detajlna razlaga RSI točk
    print(f"   [+] Momentum (RSI): {trenutne_tocke_rsi:.1f} točk (Maksimalno 10)")
    print(f"       -> Dejanski RSI (14-tedenski): {trenutni_rsi:.1f}")
    rsi_razlaga = ""
    if trenutni_rsi > 70:
        rsi_razlaga = "RSI je visok (prekupljenost). Zagon morda pojenja, zato sistem zniža točke za vstop v tem trenutku."
    elif trenutni_rsi < 40:
        rsi_razlaga = "RSI je prenizek (šibek momentum). Delnica trenutno nima nakupne moči."
    else:
        rsi_razlaga = "RSI kaže na zdrav in stabilen momentum brez pregrevanja."
    print(f"       -> DIAGNOZA: {rsi_razlaga}")

    if trenutni_ogm < 65.0:
        razlogi_za_zavrnitev.append(f"Skupni OGM Score ({trenutni_ogm:.1f}) je pod mejo 65 točk.")
        
    print("-" * 60)
    print("📈 PRESEK TRENDOV:")
    print(f"   - Trenutna cena: ${trenutna_cena:.2f}")
    print(f"   - 20-Day MA (Kratkoročni trend): ${zadnji_ma20:.2f}")
    print(f"   - 200-Week MA (Dolgoročni trend): ${zadnji_ma200:.2f}")
    
    if is_falling_phase:
        print("   ⚠️ OPOZORILO: Delnica je v fazi padanja (20-day MA je pod 200-week MA).")
    if not trend_ok:
        print("   ⚠️ OPOZORILO: Cena je prebila dolgoročno 200-tedensko podporo.")

    # Priprava zgodovinske tabele za modal/prikaz v PDF poročilu
    datumi_str = [d.strftime("%Y-%m-%d") for d in close_series.index]
    zgodovina_tabela = []
    zadnji_indeks_signala = -999
    for i in range(len(ogm)):
        if ogm[i] >= 80.0 and (i - zadnji_indeks_signala) > 26:
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

    # Priprava podatkov za HTML Graf
    graf_data = {
        "dates": datumi_str,
        "prices": np.round(close_series.values, 2).tolist(),
        "ma200": np.round(ma200.values, 2).tolist(),
        "ma20": np.round(ma20.values, 2).tolist(),
        "ogm": np.round(ogm, 1).tolist(),
        "history": zgodovina_tabela
    }
    
    diagnostika_info = {
        "ogm_skupaj": trenutni_ogm, "tocke_ma": trenutne_tocke_ma, "pct_ma": trenutni_pct_ma, "ma_razlaga": ma_razlaga,
        "tocke_rsi": trenutne_tocke_rsi, "rsi": trenutni_rsi, "rsi_razlaga": rsi_razlaga,
        "is_falling": is_falling_phase, "trend_ok": trend_ok, "cena": trenutna_cena
    }

    izpisi_zakljucek_in_generiraj_html(ticker, ime, mcap_str, rev_growth_val, razlogi_za_zavrnitev, graf_data, diagnostika_info)


def izpisi_zakljucek_in_generiraj_html(ticker, ime, mcap_str, rev_growth_val, razlogi, graf_data, diag):
    print("=========================================================")
    print("📝 ZAKLJUČEK DIAGNOSTIKE:")
    if len(razlogi) == 0:
        print("✨ Delnica IZPOLNJUJE VSE POGOJE in SE NAHAJA na tvojem glavnem seznamu!")
        status_barva = "#16a34a" # Zelena
        status_tekst = "SPREJETO (USTREZA FILTROM)"
    else:
        print("🛑 Delnica NI NA SEZNAMU zaradi naslednjih razlogov:")
        for i, razlog in enumerate(razlogi, 1):
            print(f"   {i}. {razlog}")
        status_barva = "#dc2626" # Rdeča
        status_tekst = "ZAVRNJENO (NE USTREZA FILTROM)"
    print("=========================================================\n")

    if not graf_data:
        return # Če ni zgodovine, ne delamo HTML grafa
        
    print("Ustvarjam vizualno poročilo z grafom v brskalniku...")
    
    # Sestavljanje razlogov za HTML
    razlogi_html = "".join([f"<li>{r}</li>" for r in razlogi]) if razlogi else "<li>✓ Nobenih prekrškov. Delnica ustreza vsem kriterijem.</li>"
    
    # 1. DEL: HTML Telo (Tukaj uporabljamo f-string, ker ni JavaScripta)
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>Diagnostika: {ticker}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f8fafc; color: #1e293b; padding: 30px; max-width: 1200px; margin: 0 auto; }}
    .header {{ background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); color: white; padding: 25px; border-radius: 8px; margin-bottom: 25px; position: relative; }}
    .header h1 {{ margin: 0; font-size: 24pt; }}
    .status-badge {{ background-color: {status_barva}; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 11pt; display: inline-block; margin-top: 10px; }}
    
    /* GUMB ZA PDF IZVOZ */
    .btn-pdf {{ position: absolute; right: 25px; top: 35px; background-color: #ef4444; color: white; border: none; padding: 12px 20px; border-radius: 6px; font-weight: 700; font-size: 10pt; cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: 0.2s; }}
    .btn-pdf:hover {{ background-color: #dc2626; transform: translateY(-1px); }}
    
    .grid-container {{ display: grid; grid-template-columns: 1fr 1fr; gap: 25px; margin-bottom: 30px; }}
    .card {{ background-color: white; padding: 20px; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
    .card h3 {{ margin-top: 0; color: #334155; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; }}
    
    .ogm-velik {{ font-size: 32pt; font-weight: bold; color: #1d4ed8; text-align: center; margin: 10px 0; }}
    .razlaga-box {{ background-color: #f1f5f9; padding: 12px; border-left: 4px solid #3b82f6; border-radius: 4px; margin-bottom: 15px; font-size: 9.5pt; }}
    
    ul.razlogi {{ color: #dc2626; font-weight: 500; font-size: 10.5pt; }}
    li {{ margin-bottom: 8px; }}
    
    .chart-container {{ background-color: white; padding: 20px; border-radius: 8px; border: 1px solid #e2e8f0; height: 420px; position: relative; margin-bottom: 30px; }}
    
    .history-table {{ font-size: 8.5pt; width: 100%; border: 1px solid #e2e8f0; border-collapse: collapse; margin-top: 15px; background-color: white; }}
    .history-table th {{ background-color: #f1f5f9; color: #475569; padding: 8px; text-align: left; border-bottom: 2px solid #e2e8f0; }}
    .history-table td {{ padding: 8px; border-bottom: 1px solid #e2e8f0; }}
    
    /* STRATEŠKA PRIPRAVA ZA PDF PRINT */
    @media print {{
        body {{ background-color: white; padding: 0; margin: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
        .btn-pdf {{ display: none !important; }}
        .grid-container {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }}
        .card {{ box-shadow: none; border: 1px solid #cbd5e1; page-break-inside: avoid; }}
        .chart-container {{ box-shadow: none; border: 1px solid #cbd5e1; page-break-inside: avoid; }}
        .history-table {{ page-break-inside: auto; }}
        tr {{ page-break-inside: avoid; page-break-after: auto; }}
    }}
    </style>
    </head>
    <body>

    <div class="header">
        <h1>{ime} ({ticker}) - OGM Diagnostika</h1>
        <div class="status-badge">{status_tekst}</div>
        <button class="btn-pdf" onclick="window.print()">📥 Izvozi v PDF</button>
    </div>

    <div class="grid-container">
        <div class="card">
            <h3>1. Temeljni Filtri & Diagnoza</h3>
            <p><strong>Market Cap:</strong> {mcap_str} <em>(Pogoj: > 20B)</em></p>
            <p><strong>Pričakovana rast prihodkov:</strong> {rev_growth_val*100:.1f} % <em>(Pogoj: > 10%)</em></p>
            
            <h4 style="margin-top: 25px; color: #0f172a;">Zakaj delnica ni na radarju?</h4>
            <ul class="razlogi">
                {razlogi_html}
            </ul>
            
            <h4 style="margin-top: 25px; color: #0f172a;">Tehnični opozorilni znaki:</h4>
            <p>Faza padanja (20MA &lt; 200MA): <strong>{'DA ⚠️' if diag['is_falling'] else 'NE ✓'}</strong></p>
            <p>Zlomljen dolgoročni trend: <strong>{'DA ⚠️' if not diag['trend_ok'] else 'NE ✓'}</strong></p>
        </div>

        <div class="card">
            <h3>2. Anatomija OGM Faktorja (Zakaj takšna ocena?)</h3>
            <div class="ogm-velik">{diag['ogm_skupaj']:.1f} / 100</div>
            
            <p><strong>Osnova (Fundamenti):</strong> 45.0 točk</p>
            
            <p><strong>Trend (Oddaljenost od 200-MA):</strong> {diag['tocke_ma']:.1f} / 35.0 točk</p>
            <div class="razlaga-box">
                <em>Dejanska oddaljenost: {diag['pct_ma']:+.1f}%</em><br>
                <strong>Razlaga algoritma:</strong> {diag['ma_razlaga']}
            </div>
            
            <p><strong>Momentum (RSI 14-tedenski):</strong> {diag['tocke_rsi']:.1f} / 10.0 točk</p>
            <div class="razlaga-box">
                <em>Dejanski RSI: {diag['rsi']:.1f}</em><br>
                <strong>Razlaga algoritma:</strong> {diag['rsi_razlaga']}
            </div>
        </div>
    </div>

    <div class="chart-container">
        <canvas id="ogmChart"></canvas>
    </div>

    <div class="card" style="margin-bottom: 30px;">
        <h3>3. Uspešnost preteklih prebojev OGM > 80 (Backtest 10 Let)</h3>
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
    """

    # 2. DEL: JavaScript Telo (TO NI VEČ F-STRING! Python ga bo pustil popolnoma pri miru)
    js_template = """
    <script>
    const data = GRAF_DATA_PLACEHOLDER;
    const ctx = document.getElementById('ogmChart').getContext('2d');
    
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.dates,
            datasets: [
                {
                    label: 'Cena Delnice ($)',
                    data: data.prices,
                    yAxisID: 'y',
                    borderColor: '#0f172a',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.1
                },
                {
                    label: '200-Week MA (Dolgoročni trend)',
                    data: data.ma200,
                    yAxisID: 'y',
                    borderColor: '#dc2626',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    pointRadius: 0
                },
                {
                    label: '20-Day MA (Kratkoročni trend)',
                    data: data.ma20,
                    yAxisID: 'y',
                    borderColor: '#f59e0b',
                    borderWidth: 1.5,
                    pointRadius: 0
                },
                {
                    label: 'OGM Score (0-100)',
                    data: data.ogm,
                    yAxisID: 'y1',
                    borderColor: '#16a34a',
                    backgroundColor: 'rgba(22, 163, 74, 0.1)',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                title: { display: true, text: 'Zgodovina cene in OGM ocene (10 Let)', font: { size: 14 } }
            },
            scales: {
                x: { ticks: { maxTicksLimit: 12 } },
                y: { type: 'linear', display: true, position: 'left', title: { display: true, text: 'Cena ($)' } },
                y1: { type: 'linear', display: true, position: 'right', min: 0, max: 100, title: { display: true, text: 'OGM Točke' }, grid: { drawOnChartArea: false } }
            }
        }
    });

    const tbody = document.getElementById('historyBody');
    if (!data.history || data.history.length === 0) {
        tbody.innerHTML = "<tr><td colspan='4' style='text-align:center; color:#64748b;'>Ni zabeleženih preteklih signalov v zadnjih 10 letih.</td></tr>";
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
    </script>
    </body>
    </html>
    """
    
    # 3. Združitev obeh delov in vbrizgavanje podatkov na varen način
    js_template = js_template.replace("GRAF_DATA_PLACEHOLDER", json.dumps(graf_data))
    html_content = html_template + js_template
    
    ime_datoteke = "OGM_DIAGNOSTIKA_REPORT.html"
    with open(ime_datoteke, "w", encoding="utf-8") as f: 
        f.write(html_content)
    webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

if __name__ == "__main__":
    while True:
        diagnosticiraj_delnico()
        se_eno = input("\nŽeliš analizirati še eno delnico? (D/N): ").strip().upper()
        if se_eno != 'D':
            print("Zaključujem diagnostiko. Lep dan!")
            break