import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import json
import webbrowser
import os

print("=========================================================")
print("🔍 OGM DIAGNOSTIKA: RAZČLENITEV IN VIZUALIZACIJA (MOAT V3)")
print("=========================================================")

MIN_MARKET_CAP = 20_000_000_000
MEGA_CAP_THRESHOLD = 200_000_000_000 
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
    
    try:
        info = delnica.info
        mcap = info.get('marketCap')
        if mcap is None or pd.isna(mcap) or mcap < MIN_MARKET_CAP:
            razlogi_za_zavrnitev.append(f"Market Cap je premajhen ({formatiraj_mcap(mcap)} < 20B$).")
            
        rev_growth = info.get('revenueGrowth', 0)
        if rev_growth is None or pd.isna(rev_growth) or float(rev_growth) < MIN_REVENUE_GROWTH:
            razlogi_za_zavrnitev.append(f"Pričakovana rast prihodkov je prenizka ({(float(rev_growth or 0)*100):.1f}% < 10%).")
            
        is_mega_cap = mcap >= MEGA_CAP_THRESHOLD if mcap else False
    except Exception as e:
        print(f"[NAPAKA] Ocenjujem, da tiker {ticker} ne obstaja ali pa ga Yahoo API zavrača.")
        return

    data = delnica.history(start="2014-01-01", interval="1wk", actions=False)
    if data is None or data.empty or len(data) < 205:
        print("[NAPAKA] Podjetje nima dovolj dolge zgodovine na borzi.")
        return

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
        
    close = data['Close'].dropna()

    eps_growth = info.get('earningsQuarterlyGrowth') or info.get('earningsGrowth', 0)
    eps_pct = float(eps_growth) * 100 if eps_growth else 0.0
    
    peg_val = float(info.get('pegRatio') or 2.0)
    if peg_val == 0.0: peg_val = 2.0
    
    margin_val = float(info.get('grossMargins') or 0.0) * 100
    is_high_margin_moat = (not is_mega_cap) and (margin_val >= 50.0)
    
    # POPRAVLJENA V3 FUNDAMENTALNA MATRIKA
    t_eps = np.interp(eps_pct, [0.0, 8.0, 16.5, 22.0, 30.0], [0.0, 5.0, 14.0, 20.0, 20.0])
    t_peg = np.interp(peg_val, [0.4, 0.8, 1.2, 1.6, 2.0], [15.0, 13.0, 10.0, 5.0, 0.0])
    t_mar = np.interp(margin_val, [25, 35, 45, 55, 65], [0.0, 2.0, 5.0, 8.0, 10.0]) 
    
    fund_score = min(45.0, t_eps + t_peg + t_mar)

    ma50 = close.rolling(window=50).mean()
    ma200 = close.rolling(window=200).mean()
    
    ma_target = ma50 if is_mega_cap else ma200
    tip_ma = "50w MA (Mega-Cap)" if is_mega_cap else ("200w MA (Moat)" if is_high_margin_moat else "200w MA")
    
    pct_ma = ((close - ma_target) / ma_target) * 100

    delta = close.diff()
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
    
    if is_mega_cap:
        tocke_ma[pos_mask] = np.interp(oddaljenost_arr[pos_mask], [0, 2, 8, 15], [W_MA*(32/35), W_MA, W_MA*(15/35), 0.0])
        tocke_ma[neg_mask] = np.interp(oddaljenost_arr[neg_mask], [-40, -15, -2, 0], [W_MA, W_MA, W_MA*(34/35), W_MA*(32/35)])
    elif is_high_margin_moat:
        tocke_ma[pos_mask] = np.interp(oddaljenost_arr[pos_mask], [0, 2, 10, 25, 50], [W_MA*(33/35), W_MA, W_MA*(22/35), W_MA*(8/35), 0.0])
        tocke_ma[neg_mask] = np.interp(oddaljenost_arr[neg_mask], [-35, -20, -15, -5, 0], [0.0, 35.0, 40.0, 38.0, W_MA*(33/35)])
    else:
        tocke_ma[pos_mask] = np.interp(oddaljenost_arr[pos_mask], [0, 2, 10, 25, 50], [W_MA*(33/35), W_MA, W_MA*(22/35), W_MA*(8/35), 0.0])
        tocke_ma[neg_mask] = np.interp(oddaljenost_arr[neg_mask], [-20, -10, -5, 0], [0.0, W_MA*(12/35), W_MA*(25/35), W_MA*(33/35)])
        
    tocke_rsi = np.interp(rsi_arr, [30, 45, 60, 70, 80], [15.0, 15*0.8, 15*0.5, 15*0.2, 0.0])
    
    # TRDI ZAKLEP 100 TOČK
    ogm_zgodovina = np.clip(tocke_ma + tocke_rsi + fund_score, 0, 100.0)
    trenutni_ogm = min(100.0, float(ogm_zgodovina[-1]))

    if trenutni_ogm < 65.0:
        razlogi_za_zavrnitev.append(f"OGM Score je prenizek ({trenutni_ogm:.1f} < 65).")

    ime = info.get('shortName', ticker)
    trenutna_cena = float(close.iloc[-1])
    dist_ma_trenutna = float(oddaljenost_arr[-1])
    
    zgodovina_tabela = []
    zadnji_indeks_signala = -999
    datumi_str = [d.strftime("%Y-%m-%d") for d in close.index]
    
    for i in range(len(ogm_zgodovina)):
        if ogm_zgodovina[i] >= 80.0 and (i - zadnji_indeks_signala) > 26:
            cena_ob_signalu = close.iloc[i]
            if i + 52 < len(close): max_cena_12m = close.iloc[i:i+52].max()
            else: max_cena_12m = close.iloc[i:].max() if i + 1 < len(close) else cena_ob_signalu
            donos = ((max_cena_12m - cena_ob_signalu) / cena_ob_signalu) * 100
            if i + 52 < len(close):
                zgodovina_tabela.append({"datum": datumi_str[i], "cena": round(cena_ob_signalu, 2), "max_cena": round(max_cena_12m, 2), "max_donos": round(donos, 1)})
            zadnji_indeks_signala = i

    status_barva = "#15803d" if not razlogi_za_zavrnitev else "#dc2626"
    status_tekst = "SPREJETO (USTREZA FILTROM)" if not razlogi_za_zavrnitev else "ZAVRNJENO (NE USTREZA FILTROM)"
    razlogi_html = "".join([f"<li>{r}</li>" for r in razlogi_za_zavrnitev]) if razlogi_za_zavrnitev else "<li>Vsi strateški in OGM filtri so uspešno prestani.</li>"

    graf_data = {
        "ime": ime,
        "dates": datumi_str,
        "prices": np.round(close.values, 2).tolist(),
        "ogm": np.round(ogm_zgodovina, 1).tolist(),
        "history": zgodovina_tabela,
        "components": {
            "eps_growth_raw": eps_pct, "eps_growth_score": float(t_eps),
            "peg_raw": peg_val, "peg_score": float(t_peg),
            "margin_raw": margin_val, "margin_score": float(t_mar),
            "rsi_raw": float(rsi_arr[-1]), "rsi_score": float(tocke_rsi[-1]),
            "ma_dist_raw": dist_ma_trenutna, "ma_dist_score": float(tocke_ma[-1]),
            "total_score": float(trenutni_ogm),
            "ma_type": tip_ma
        }
    }

    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>OGM Diagnostika - {ticker}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
    html {{ overflow-x: hidden; }}
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #060d1a; color: #cbd5e1; margin: 0; padding: 22px 14px 50px; min-height: 100vh; }}
    .page-wrap {{ max-width: 1280px; margin: 0 auto; }}
    .header {{ background: linear-gradient(135deg, #0c1628 0%, #112244 55%, #1d4ed8 100%); color: #fff; padding: 26px 30px; border-radius: 12px; border: 1px solid rgba(255,255,255,.07); box-shadow: 0 8px 40px rgba(0,0,0,.55); margin-bottom: 24px; }}
    .header h1 {{ margin: 0; font-size: 20pt; font-weight: 800; }}
    .header p {{ margin: 5px 0 0; color: #93c5fd; font-size: 9.5pt; }}
    .card {{ background: #0b1526; border-radius: 12px; padding: 22px; margin-bottom: 22px; border: 1px solid rgba(255,255,255,.06); box-shadow: 0 4px 20px rgba(0,0,0,.3); }}
    .status-badge {{ padding: 5px 14px; border-radius: 20px; font-weight: 700; font-size: 9pt; color: #fff; display: inline-block; margin-bottom: 14px; }}
    .chart-container {{ position: relative; height: 400px; width: 100%; margin-bottom: 22px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; margin-top: 14px; }}
    th {{ background: #09152a; color: #475569; padding: 10px 8px; text-align: left; border-bottom: 1px solid rgba(255,255,255,.06); font-size: 7.5pt; text-transform: uppercase; letter-spacing: .6px; font-weight: 700; }}
    td {{ padding: 10px 8px; border-bottom: 1px solid rgba(255,255,255,.035); color: #94a3b8; }}
    tr:nth-child(even) td {{ background: #0e1d32; }}
    tr:hover td {{ background: #152338 !important; }}
    .grid-2col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
    @media print {{
        body {{ background-color: #060d1a; margin: 0; padding: 10px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
        .card {{ box-shadow: none; page-break-inside: avoid; }}
    }}
    </style>
    </head>
    <body>
<div class="page-wrap">

    <div class="header">
        <h1>OGM Diagnostika: {ticker}</h1>
        <p style="margin:6px 0 0; color:#93c5fd; font-size:9.5pt;">{ime} &mdash; ${trenutna_cena:.2f} &mdash; {datetime.now().strftime("%d.%m.%Y")}</p>
    </div>

    <div class="card">
        <div class="status-badge" style="background-color: {status_barva};">{status_tekst}</div>
        <div style="background: #0e1d32; padding: 15px; border-radius: 8px; border-left: 4px solid {status_barva}; margin-bottom: 25px;">
            <h4 style="margin: 0 0 10px 0; color: #94a3b8;">Status filtrov:</h4>
            <ul style="margin: 0; padding-left: 20px; color: #64748b;">{razlogi_html}</ul>
        </div>
        
        <div class="chart-container">
            <canvas id="ogmChart"></canvas>
        </div>
    </div>

    <div class="grid-2col">
        <div class="card">
            <h3 style="margin-top:0; border-bottom: 1px solid rgba(255,255,255,.06); padding-bottom: 10px; color: #f1f5f9;">Struktura OGM Točk</h3>
            <table>
                <tr><th>Faktor</th><th>Vrednost</th><th>Dodeljene točke</th></tr>
                <tr><td>Rast EPS</td><td>{eps_pct:.1f} %</td><td style="font-weight:bold;">{t_eps:.1f} / 20</td></tr>
                <tr><td>PEG Ratio</td><td>{peg_val:.2f}</td><td style="font-weight:bold;">{t_peg:.1f} / 15</td></tr>
                <tr><td>Bruto Marža</td><td>{margin_val:.1f} %</td><td style="font-weight:bold;">{t_mar:.1f} / 10</td></tr>
                <tr><td>RSI (14w)</td><td>{rsi_arr[-1]:.1f}</td><td style="font-weight:bold;">{tocke_rsi[-1]:.1f} / 15</td></tr>
                <tr><td>Oddaljenost od {tip_ma}</td><td>{dist_ma_trenutna:+.1f} %</td><td style="font-weight:bold;">{tocke_ma[-1]:.1f} / 40</td></tr>
                <tr style="background: #0e1d32; font-weight: bold; font-size: 11pt; color: #f1f5f9;"><td>SKUPAJ OGM</td><td>-</td><td>{trenutni_ogm:.1f} / 100</td></tr>
            </table>
        </div>
        
        <div class="card">
            <h3 style="margin-top:0; border-bottom: 1px solid rgba(255,255,255,.06); padding-bottom: 10px; color: #f1f5f9;">Zgodovina Preteklih Signalov (>80)</h3>
            <table>
                <thead><tr><th>Datum</th><th>Cena ob signalu</th><th>Max cena (12m)</th><th>Max donos</th></tr></thead>
                <tbody id="historyBody"></tbody>
            </table>
        </div>
    </div>
    """

    js_template = """
    <script>
    const data = GRAF_DATA_PLACEHOLDER;
    
    const ctx = document.getElementById('ogmChart').getContext('2d');
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
                x: { ticks: { maxTicksLimit: 12, color: '#6b7280' }, grid: { color: 'rgba(255,255,255,.05)' } },
                y: { type: 'linear', display: true, position: 'left', ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,.05)' } },
                y1: { type: 'linear', display: true, position: 'right', min: 0, max: 100, ticks: { color: '#6b7280' }, grid: { drawOnChartArea: false } }
            },
            plugins: { legend: { labels: { color: '#94a3b8' } } }
        }
    });

    const tbody = document.getElementById('historyBody');
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
    </script>
    </div><!-- /page-wrap -->
    </body>
    </html>
    """
    
    js_template = js_template.replace("GRAF_DATA_PLACEHOLDER", json.dumps(graf_data))
    html_content = html_template + js_template
    
    ime_datoteke = f"OGM_DIAGNOSTIKA_{ticker}.html"
    with open(ime_datoteke, "w", encoding="utf-8") as f: f.write(html_content)
    
    print(f"\n[USPEH] Analitično poročilo je ustvarjeno: '{ime_datoteke}'")
    if os.environ.get("CI") != "true":
        webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

if __name__ == "__main__":
    diagnosticiraj_delnico()