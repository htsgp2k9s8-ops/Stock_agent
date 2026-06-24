import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime
import webbrowser
import os
import json

print("=========================================================")
print("🚀 OGM PORTFOLIO BACKTESTER - Z MEGA-CAP PRAVILOM (V2)")
print("=========================================================")

CSV_DATOTEKA = "moje_globalne_delnice.csv"
ZACETNI_KAPITAL = 100000.0
MAX_WEIGHT_PER_STOCK = 0.05  
MIN_MARKET_CAP = 40_000_000_000  
MEGA_CAP_THRESHOLD = 200_000_000_000 

if not os.path.exists(CSV_DATOTEKA):
    print(f"[NAPAKA] Datoteka '{CSV_DATOTEKA}' ne obstaja!")
    os._exit(0)

# ==============================================================================
# 1. FAZA: FILTRACIJA IN PRENOS PODATKOV
# ==============================================================================
df_baza = pd.read_csv(CSV_DATOTEKA)
vsi_tickerji = df_baza['Ticker'].dropna().astype(str).str.strip().tolist()

print(f"Skeniram {len(vsi_tickerji)} delnic iz CSV za Market Cap in Fundamente...")

veljavni_tickerji = {}
market_caps = {}

for ticker in vsi_tickerji:
    try:
        delnica = yf.Ticker(ticker)
        info = delnica.info
        mcap = info.get('marketCap', 0)
        
        if mcap is None or mcap < MIN_MARKET_CAP:
            continue
            
        eps_growth = info.get('earningsQuarterlyGrowth', 0) or info.get('earningsGrowth', 0)
        peg_ratio = info.get('pegRatio', 2.0)
        gross_margin = info.get('grossMargins', 0)
        
        eps_pct = (eps_growth * 100) if eps_growth else 0.0
        margin_pct = (gross_margin * 100) if gross_margin else 0.0
        peg_val = float(peg_ratio) if peg_ratio else 2.0
        
        t_eps = np.interp(eps_pct, [0.0, 8.0, 16.5, 22.0, 30.0], [0.0, 5.0, 14.0, 20.0, 20.0])
        t_peg = np.interp(peg_val, [0.4, 0.8, 1.2, 1.6, 2.0], [15.0, 13.0, 10.0, 5.0, 0.0])
        t_mar = np.interp(margin_pct, [25, 35, 45, 55, 65], [0.0, 2.0, 5.0, 8.0, 10.0])
        
        base_buy_score = min(45.0, t_eps + t_peg + t_mar)
        
        veljavni_tickerji[ticker] = base_buy_score
        market_caps[ticker] = mcap
    except Exception:
        continue

print(f"Kvalificiranih delnic (>40B Market Cap): {len(veljavni_tickerji)}")
print("Prenašam zgodovino cen (2013-2024)...")

vsi_za_prenos = list(veljavni_tickerji.keys()) + ["^GSPC", "^NDX"]
data = yf.download(vsi_za_prenos, start="2013-01-01", end="2024-12-31", interval="1wk", progress=False)['Close']
data = data.ffill().bfill() 

if isinstance(data, pd.Series):
    data = data.to_frame()

def izracunaj_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# ==============================================================================
# 2. FAZA: PRIPRAVA OGM SIGNALOV (BUY in SELL)
# ==============================================================================
print("Kalkuliram OGM Buy in Sell točkovnike (z V2 Mega-Cap pravilom)...")
signali = {}

for ticker in veljavni_tickerji.keys():
    if ticker not in data.columns: continue
    
    close = data[ticker]
    ma10 = close.rolling(window=10).mean()
    ma50 = close.rolling(window=50).mean()
    ma100 = close.rolling(window=100).mean()
    ma200 = close.rolling(window=200).mean()
    rsi = izracunaj_rsi(close)
    
    # ---- OGM BUY IZRAČUN ----
    arr_rsi = rsi.values
    tocke_ma_buy = np.zeros_like(arr_rsi)
    
    is_mega_cap = market_caps[ticker] >= MEGA_CAP_THRESHOLD
    
    if is_mega_cap:
        # MEGA-CAP PRAVILO V2: Ne kaznujemo globokih padcev. Globok padec = MAX TOČKE.
        ma_target = ma50.replace(0, np.nan)
        pct_ma = ((close - ma_target) / ma_target) * 100
        arr_pct = pct_ma.values
        
        pos_mask = (arr_pct >= 0) & ~np.isnan(arr_pct)
        neg_mask = (arr_pct < 0) & ~np.isnan(arr_pct)
        
        tocke_ma_buy[pos_mask] = np.interp(arr_pct[pos_mask], [0, 2, 12, 30], [40*(33/35), 40.0, 40*(25/35), 0.0])
        # Sprememba tukaj: Tudi če pade do -40% pod 50w MA, dobi 40 točk!
        tocke_ma_buy[neg_mask] = np.interp(arr_pct[neg_mask], [-40, -15, -2, 0], [40.0, 40.0, 40*(34/35), 40*(33/35)])
    else:
        # KLASIČNO PRAVILO (Ostaja nespremenjeno za varno lovljenje manjših)
        ma_target = ma200.replace(0, np.nan)
        pct_ma = ((close - ma_target) / ma_target) * 100
        arr_pct = pct_ma.values
        
        pos_mask = (arr_pct >= 0) & ~np.isnan(arr_pct)
        neg_mask = (arr_pct < 0) & ~np.isnan(arr_pct)
        
        tocke_ma_buy[pos_mask] = np.interp(arr_pct[pos_mask], [0, 2, 10, 25, 50], [40*(33/35), 40.0, 40*(22/35), 40*(8/35), 0.0])
        tocke_ma_buy[neg_mask] = np.interp(arr_pct[neg_mask], [-20, -10, -5, 0], [0.0, 40*(12/35), 40*(25/35), 40*(33/35)])
        
    tocke_rsi_buy = np.interp(arr_rsi, [30, 45, 60, 70, 80], [15.0, 15*0.8, 15*0.5, 15*0.2, 0.0])
    ogm_buy = np.clip(tocke_ma_buy + tocke_rsi_buy + veljavni_tickerji[ticker], 0, 100)
    
    # ---- OGM SELL IZRAČUN ----
    ma200_safe = ma200.replace(0, np.nan)
    dist_10 = ((ma10 - ma200_safe) / ma200_safe) * 100
    dist_50 = ((ma50 - ma200_safe) / ma200_safe) * 100
    strmina = ((ma10 - ma10.shift(10)) / ma10.shift(10)) * 100
    pe_stretch = ((close - ma100.replace(0, np.nan)) / ma100.replace(0, np.nan)) * 100
    
    s_rsi = np.interp(np.nan_to_num(arr_rsi), [65, 75, 85], [0, 15.7/2, 15.7])
    s_d10 = np.interp(np.nan_to_num(dist_10.values), [50, 70, 100], [0, 29.8/2, 29.8])
    s_d50 = np.interp(np.nan_to_num(dist_50.values), [30, 40, 60], [0, 23.3/2, 23.3])
    s_strmina = np.interp(np.nan_to_num(strmina.values), [10, 12, 20], [0, 20.1/2, 20.1])
    s_pe = np.interp(np.nan_to_num(pe_stretch.values), [30, 40, 60], [0, 22.4/2, 22.4])
    
    ogm_sell = np.clip(s_rsi + s_d10 + s_d50 + s_strmina + s_pe, 0, 100)
    
    df_signals = pd.DataFrame({'Close': close, 'Buy': ogm_buy, 'Sell': ogm_sell}, index=close.index)
    signali[ticker] = df_signals[df_signals.index >= '2017-01-01']

# ==============================================================================
# 3. FAZA: VIRTUALNI PORTFOLIO BACKTEST
# ==============================================================================
print("Začenjam simulacijo portfelja skozi čas...")

all_dates = data[data.index >= '2017-01-01'].index

ogm_cash = ZACETNI_KAPITAL
ogm_positions = {} 
zgodovina_trgov = [] 

start_date = all_dates[0]
sp500_shares = ZACETNI_KAPITAL / data.loc[start_date, '^GSPC'] if '^GSPC' in data.columns else 0
ndx_shares = ZACETNI_KAPITAL / data.loc[start_date, '^NDX'] if '^NDX' in data.columns else 0

benchmark_history = {'Dates': [], 'OGM': [], 'SP500': [], 'NDX': []}

for current_date in all_dates:
    str_date = current_date.strftime("%Y-%m-%d")
    
    for ticker in list(ogm_positions.keys()):
        if ticker not in signali or current_date not in signali[ticker].index:
            continue
            
        row = signali[ticker].loc[current_date]
        trenutna_cena = float(row['Close'])
        
        if row['Sell'] >= 85.0:
            prodana_vrednost = ogm_positions[ticker] * trenutna_cena
            ogm_cash += prodana_vrednost
            zgodovina_trgov.append({
                "Datum": str_date, "Akcija": "SELL 🔴", "Ticker": ticker, 
                "Cena": f"${trenutna_cena:.2f}", "Vrednost": prodana_vrednost, 
                "Razlog": f"Presežen Sell Score: {row['Sell']:.1f}"
            })
            del ogm_positions[ticker]
            
    trenutna_vrednost_pozicij = sum([ogm_positions[t] * float(data.loc[current_date, t]) for t in ogm_positions])
    trenutni_equity = ogm_cash + trenutna_vrednost_pozicij
    
    for ticker, df in signali.items():
        if current_date not in df.index: continue
        if ticker in ogm_positions: continue 
            
        row = df.loc[current_date]
        
        if row['Buy'] >= 80.0:
            trenutna_cena = float(row['Close'])
            max_investicija = trenutni_equity * MAX_WEIGHT_PER_STOCK
            investicija = min(max_investicija, ogm_cash)
            
            if investicija > 100: 
                vrsta = "🔥 MEGA-CAP BUY" if market_caps[ticker] >= MEGA_CAP_THRESHOLD else "🟢 VALUE BUY"
                shares_to_buy = investicija / trenutna_cena
                ogm_positions[ticker] = shares_to_buy
                ogm_cash -= investicija
                zgodovina_trgov.append({
                    "Datum": str_date, "Akcija": vrsta, "Ticker": ticker, 
                    "Cena": f"${trenutna_cena:.2f}", "Vrednost": investicija, 
                    "Razlog": f"Buy Score: {row['Buy']:.1f}"
                })
                
    koncna_vrednost_pozicij = sum([ogm_positions[t] * float(data.loc[current_date, t]) for t in ogm_positions])
    koncni_equity = ogm_cash + koncna_vrednost_pozicij
    
    benchmark_history['Dates'].append(str_date)
    benchmark_history['OGM'].append(round(koncni_equity, 2))
    benchmark_history['SP500'].append(round(sp500_shares * float(data.loc[current_date, '^GSPC']), 2))
    benchmark_history['NDX'].append(round(ndx_shares * float(data.loc[current_date, '^NDX']), 2))

# ==============================================================================
# 4. HTML POROČILO
# ==============================================================================
print("Generiram interaktivno poročilo...")

df_krivulje = pd.DataFrame(benchmark_history)
df_krivulje['Leto'] = pd.to_datetime(df_krivulje['Dates']).dt.year

letni_rezultati = []
leta = sorted(df_krivulje['Leto'].unique())

for leto in leta:
    df_leto = df_krivulje[df_krivulje['Leto'] == leto]
    if len(df_leto) < 2: continue
    
    zacetek = df_leto.iloc[0]
    konec = df_leto.iloc[-1]
    
    letni_rezultati.append({
        "Leto": leto, 
        "OGM": round(((konec['OGM'] - zacetek['OGM']) / zacetek['OGM']) * 100, 2), 
        "SP500": round(((konec['SP500'] - zacetek['SP500']) / zacetek['SP500']) * 100, 2), 
        "NDX": round(((konec['NDX'] - zacetek['NDX']) / zacetek['NDX']) * 100, 2)
    })

chart_data = {
    "labels": benchmark_history['Dates'],
    "ogm": benchmark_history['OGM'],
    "sp500": benchmark_history['SP500'],
    "ndx": benchmark_history['NDX']
}

html_content = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>OGM Backtest (2017-2024)</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f8fafc; color: #1e293b; margin: 40px auto; max-width: 1400px; padding: 0 20px; }}
.header {{ background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 100%); color: #ffffff; padding: 30px; border-radius: 8px; margin-bottom: 30px; position: relative; }}
.header h1 {{ margin: 0; font-size: 24pt; }}
.header p {{ margin: 5px 0 0 0; color: #bfdbfe; font-size: 11pt; }}
.btn-tx {{ position: absolute; right: 30px; top: 35px; background-color: #10b981; color: white; border: none; padding: 12px 20px; border-radius: 6px; font-weight: 700; cursor: pointer; }}
.stats-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 30px; }}
.stat-card {{ background: white; padding: 20px; border-radius: 8px; border: 1px solid #e2e8f0; text-align: center; }}
.stat-card h3 {{ margin: 0 0 10px 0; color: #64748b; font-size: 11pt; }}
.stat-card .val {{ font-size: 24pt; font-weight: bold; }}
.val-ogm {{ color: #16a34a; }}
.chart-container {{ background: white; padding: 20px; border-radius: 8px; border: 1px solid #e2e8f0; height: 500px; margin-bottom: 30px; }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; margin-bottom: 40px; }}
th {{ background-color: #1e293b; color: white; padding: 12px; text-align: center; }}
td {{ padding: 12px; border-bottom: 1px solid #e2e8f0; text-align: center; font-weight: bold; }}
.pos {{ color: #16a34a; }} .neg {{ color: #dc2626; }}
.modal {{ display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.6); }}
.modal-content {{ background-color: #fff; margin: 3% auto; padding: 25px; border-radius: 12px; width: 80%; max-height: 85vh; overflow-y: auto; position: relative; }}
.close {{ color: #94a3b8; position: absolute; right: 20px; top: 15px; font-size: 28px; font-weight: bold; cursor: pointer; }}
</style>
</head>
<body>

<div class="header">
    <h1>📊 OGM Sklad - Backtest Poročilo (2017 - 2024)</h1>
    <p>Začetni kapital: 100.000 € | Max 5% na delnico | V2 Mag7 Odklep Padajočih Nožev</p>
    <button class="btn-tx" onclick="openTx()">📋 Poglej vse transakcije</button>
</div>

<div class="stats-grid">
    <div class="stat-card">
        <h3>Končna vrednost OGM Portfelja</h3>
        <div class="val val-ogm">{benchmark_history['OGM'][-1]:,.2f} €</div>
    </div>
    <div class="stat-card">
        <h3>Končna vrednost S&P 500</h3>
        <div class="val" style="color:#0f172a;">{benchmark_history['SP500'][-1]:,.2f} €</div>
    </div>
    <div class="stat-card">
        <h3>Končna vrednost NASDAQ 100</h3>
        <div class="val" style="color:#0f172a;">{benchmark_history['NDX'][-1]:,.2f} €</div>
    </div>
</div>

<div class="chart-container">
    <canvas id="performanceChart"></canvas>
</div>

<h2 style="color: #0f172a;">Primerjava Letnih Donosov (%)</h2>
<table>
    <thead><tr><th>Leto</th><th>OGM Portfelj</th><th>S&P 500</th><th>NASDAQ 100</th><th>Razlika OGM vs S&P500</th></tr></thead>
    <tbody>
"""

for row in letni_rezultati:
    razlika = row['OGM'] - row['SP500']
    html_content += f"""
        <tr>
            <td style="color:#475569;">{row['Leto']}</td>
            <td class="{'pos' if row['OGM'] >= 0 else 'neg'}">{row['OGM']:+.2f} %</td>
            <td class="{'pos' if row['SP500'] >= 0 else 'neg'}">{row['SP500']:+.2f} %</td>
            <td class="{'pos' if row['NDX'] >= 0 else 'neg'}">{row['NDX']:+.2f} %</td>
            <td class="{'pos' if razlika >= 0 else 'neg'}">{razlika:+.2f} %</td>
        </tr>
    """

html_content += f"""
    </tbody>
</table>

<div id="txModal" class="modal">
    <div class="modal-content">
        <span class="close" onclick="closeTx()">&times;</span>
        <h2 style="margin-top:0; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;">Zgodovina transakcij</h2>
        <table>
            <thead><tr><th>Datum</th><th>Akcija</th><th>Ticker</th><th>Cena</th><th>Vrednost (€)</th><th>Razlog</th></tr></thead>
            <tbody id="txBody"></tbody>
        </table>
    </div>
</div>

<script>
const ctx = document.getElementById('performanceChart').getContext('2d');
const data = {json.dumps(chart_data)};

new Chart(ctx, {{
    type: 'line',
    data: {{
        labels: data.labels,
        datasets: [
            {{ label: 'OGM Portfelj (€)', data: data.ogm, borderColor: '#16a34a', backgroundColor: 'rgba(22, 163, 74, 0.1)', borderWidth: 3, pointRadius: 0, fill: true }},
            {{ label: 'NASDAQ 100 (€)', data: data.ndx, borderColor: '#1d4ed8', borderWidth: 2, pointRadius: 0, borderDash: [5, 5] }},
            {{ label: 'S&P 500 (€)', data: data.sp500, borderColor: '#64748b', borderWidth: 2, pointRadius: 0, borderDash: [5, 5] }}
        ]
    }},
    options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ mode: 'index', intersect: false }} }}
}});

const txs = {json.dumps(zgodovina_trgov)};
function openTx() {{
    const tb = document.getElementById('txBody');
    tb.innerHTML = "";
    txs.forEach(tx => {{
        let c = tx.Akcija.includes('MEGA') ? '#d946ef' : (tx.Akcija.includes('BUY') ? '#16a34a' : '#dc2626');
        tb.innerHTML += `<tr><td>${{tx.Datum}}</td><td style="color:${{c}}; font-weight:bold;">${{tx.Akcija}}</td><td style="color:#1d4ed8;">${{tx.Ticker}}</td><td>${{tx.Cena}}</td><td>${{new Intl.NumberFormat('sl-SI',{{style:'currency',currency:'EUR'}}).format(tx.Vrednost)}}</td><td style="color:#64748b; font-size:9pt;">${{tx.Razlog}}</td></tr>`;
    }});
    document.getElementById('txModal').style.display = "block";
}}
function closeTx() {{ document.getElementById('txModal').style.display = "none"; }}
</script>
</body>
</html>
"""

ime_datoteke = "OGM_BACKTEST_POROCILO.html"
with open(ime_datoteke, "w", encoding="utf-8") as f: f.write(html_content)
print(f"\n[USPEH] Backtest zaključen! Poročilo ustvarjeno: '{ime_datoteke}'")
webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")