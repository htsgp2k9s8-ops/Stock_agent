import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import webbrowser
import os

print("=========================================================")
print("🛡️ OGM LIVE SELL RADAR (Osebni Portfelj)")
print("=========================================================")

# TUKAJ VPIŠI SVOJE DELNICE IZ PORTFELJA
MOJ_PORTFELJ = ["NVMI", "MSFT", "AMZN", "META", "GOOGL", "NFLX", "ADBE", "CRM", "INTC", "CSCO", 
    "AEM", "EZPW", "BLBD", "TXN", "AMGN", "HON", "QCOM", "SBUX", "GILD", "INTU", 
    "MDLZ", "ISRG", "BKNG", "ADI", "REGN", "VRTX", "LRCX", "MU", "ATVI", "MELI", 
    "PYPL", "SNPS", "ASML", "KLAC", "CDNS", "MAR", "PANW", "CTAS", "WDAY", "ORLY", 
    "NXPI", "MNST", "FTNT", "PCAR", "PAYX", "CPRT", "ROST", "MCHP", "KDP", "AEP",
    "BIIB", "VRSK", "EA", "TTWO", "ILMN", "ALGN", "IDXX", "ODFL", "EXC", "XEL", "FAST", "SAP.DE", "ADSK", "LULU", "MRVL", "NVDA", "AMD", "NVO", "MA", "V", "ORCL", "IBM", "CSX", "UPS", "DHR", "TMO", "LIN", "UNH", "JNJ", "ABBV", "MRK", "PFE"]

# ====================================================================
# NAUČENE UTEŽI IZ GENETSKEGA ALGORITMA
# ====================================================================
W_RSI = 15.7
W_D10 = 29.8
W_D50 = 23.3
W_STRMINA = 20.1
W_PE = 22.4

PRAG_OBOROŽITVE = 84.6       
PRAG_PARABOLA_EXTREME = 100.0 
MIN_3M_RAST = 30.4           
# ====================================================================

def izracunaj_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analiziraj_moj_portfelj():
    rezultati = []
    print(f"Preverjam živo stanje za tvojih {len(MOJ_PORTFELJ)} delnic...\n")
    
    for ticker in MOJ_PORTFELJ:
        print(f"Skeniram {ticker}...", end=" ")
        try:
            delnica = yf.Ticker(ticker)
            data = delnica.history(period="5y", interval="1wk", actions=False)
            
            if len(data) < 205:
                print("[PREMALO PODATKOV - Ignoriram]")
                continue
                
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
                
            close_series = pd.to_numeric(data['Close'].squeeze(), errors='coerce').dropna()
            
            ma10 = close_series.rolling(window=10).mean()
            ma50 = close_series.rolling(window=50).mean()
            ma200 = close_series.rolling(window=200).mean()
            ma100_avg = close_series.rolling(window=100).mean()
            rsi = izracunaj_rsi(close_series)
            
            trenutna_cena = close_series.iloc[-1]
            prejsnji_teden = close_series.iloc[-2]
            predprejsnji_teden = close_series.iloc[-3]
            
            trenutni_ma10 = ma10.iloc[-1]
            prejsnji_ma10 = ma10.iloc[-2]
            trenutni_ma200 = ma200.iloc[-1]
            
            dist_10_200 = ((trenutni_ma10 - trenutni_ma200) / trenutni_ma200) * 100
            dist_50_200 = ((ma50.iloc[-1] - trenutni_ma200) / trenutni_ma200) * 100
            strmina_10w = ((trenutni_ma10 - ma10.iloc[-11]) / ma10.iloc[-11]) * 100
            pe_stretch = ((trenutna_cena - ma100_avg.iloc[-1]) / ma100_avg.iloc[-1]) * 100
            rast_12w = ((trenutna_cena - close_series.iloc[-13]) / close_series.iloc[-13]) * 100
            trenutni_rsi = rsi.iloc[-1]
            
            score_rsi = np.interp(trenutni_rsi, [65, 75, 85], [0.0, W_RSI/2, W_RSI])
            score_d10 = np.interp(dist_10_200, [50, 70, 100], [0.0, W_D10/2, W_D10])
            score_d50 = np.interp(dist_50_200, [30, 40, 60], [0.0, W_D50/2, W_D50])
            score_strmina = np.interp(strmina_10w, [10, 12, 20], [0.0, W_STRMINA/2, W_STRMINA])
            score_pe = np.interp(pe_stretch, [30, 40, 60], [0.0, W_PE/2, W_PE])
            
            surovi_score = score_rsi + score_d10 + score_d50 + score_strmina + score_pe
            trenutni_score = min(surovi_score, 100.0)
            
            # ============================================================
            # NAPREDNA LOGIKA ŽIVIH SIGNALOV
            # ============================================================
            status = "VARNO (Drži)"
            barva = "#16a34a" # Zelena
            akcija = "Sedi na rokah in pusti dobičkom rasti."
            
            ima_parabolo = rast_12w >= MIN_3M_RAST
            is_armed = (trenutni_score >= PRAG_OBOROŽITVE)
            
            # Če je delnica visoko, a ne divja
            if is_armed and not ima_parabolo:
                status = "👀 NATEGNJENO (Manjka parabola)"
                barva = "#3b82f6" # Modra
                akcija = "Delnica je tehnično zelo visoko, a trend je stabilen in počasen. Zlomi so tu redki. Še naprej drži."
                
            # Če je delnica visoko IN nevarno divja
            if is_armed and ima_parabolo:
                status = "⚠️ PREGRETO (Oboroženo)"
                barva = "#f59e0b" # Oranžna
                akcija = "Zagon je paraboličen in nevzdržen. Pomakni stop-loss tik pod ceno!"
                
                dva_padajoca_tedna = (trenutna_cena < prejsnji_teden) and (prejsnji_teden < predprejsnji_teden)
                zlom_trenda = (trenutna_cena < trenutni_ma10) and (prejsnji_teden >= prejsnji_ma10)
                
                if dva_padajoca_tedna:
                    status = "🚨 SELL SIGNAL (Klimaks Padec)"
                    barva = "#dc2626" # Rdeča
                    akcija = "PRODAJ (Vsaj 50%). Cena potrjuje konec momenta, sledi korekcija."
                elif zlom_trenda:
                    status = "🚨 SELL SIGNAL (Zlom 10w MA)"
                    barva = "#dc2626"
                    akcija = "PRODAJ VSE. Super-trend je prebit navzdol, institucije izstopajo."
                    
            # Absolutni ekstrem na 100 točkah s parabolo
            if trenutni_score >= 99.0 and ima_parabolo:
                status = "🔥 SELL SIGNAL (Blow-off Top)"
                barva = "#991b1b" # Temno rdeča
                akcija = "TAKOJ PRODAJ. Dosežen absolutni klimaks preden se cena sploh obrne."
            
            rezultati.append({
                "ticker": ticker,
                "cena": trenutna_cena,
                "status": status,
                "barva": barva,
                "akcija": akcija,
                "score": trenutni_score,
                "rast_3m": rast_12w,
                "rsi": trenutni_rsi,
                "dist_10": dist_10_200
            })
            print("[OK]")
            
        except Exception as e:
            print(f"[NAPAKA: {e}]")
            
    generiraj_html_dashboard(rezultati)

def generiraj_html_dashboard(rezultati):
    datum_danes = datetime.now().strftime("%d.%m.%Y ob %H:%M")
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>OGM SELL Live Radar</title>
    <style>
    html {{ overflow-x: hidden; }}
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #060d1a; color: #cbd5e1; margin: 0; padding: 22px 14px 50px; min-height: 100vh; }}
    .page-wrap {{ max-width: 1280px; margin: 0 auto; }}
    .header {{ background: linear-gradient(135deg, #0c1628 0%, #112244 55%, #1d4ed8 100%); color: #fff; padding: 26px 30px; border-radius: 12px; border: 1px solid rgba(255,255,255,.07); box-shadow: 0 8px 40px rgba(0,0,0,.55); margin-bottom: 24px; }}
    .header h1 {{ margin: 0; font-size: 20pt; font-weight: 800; }}
    .header p {{ margin: 5px 0 0; color: #93c5fd; font-size: 9.5pt; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 18px; }}
    .card {{ background: #0b1526; border-radius: 12px; padding: 20px; border: 1px solid rgba(255,255,255,.06); border-top: 4px solid #16a34a; position: relative; }}
    .ticker {{ font-size: 17pt; font-weight: bold; color: #f1f5f9; margin-bottom: 4px; }}
    .price {{ font-size: 13pt; color: #475569; margin-bottom: 14px; }}
    .status-badge {{ display: inline-block; padding: 4px 12px; border-radius: 20px; color: #fff; font-weight: bold; font-size: 9pt; margin-bottom: 14px; text-transform: uppercase; }}
    .metric {{ display: flex; justify-content: space-between; font-size: 9.5pt; border-bottom: 1px solid rgba(255,255,255,.04); padding: 7px 0; }}
    .metric:last-child {{ border-bottom: none; }}
    .metric-val {{ font-weight: bold; color: #94a3b8; }}
    .action-box {{ margin-top: 14px; padding: 12px; background: #0e1d32; border-radius: 6px; font-size: 9.5pt; color: #64748b; border: 1px solid rgba(255,255,255,.05); }}
    .action-title {{ font-weight: bold; margin-bottom: 5px; color: #93c5fd; }}
    @media print {{
        body {{ background-color: #060d1a; padding: 0; margin: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
        .header {{ border-radius: 0; }}
        .grid {{ gap: 12px; grid-template-columns: repeat(2, 1fr); }}
        .card {{ box-shadow: none; page-break-inside: avoid; }}
    }}
    </style>
    </head>
    <body>
<div class="page-wrap">

    <div class="header">
        <h1>OGM Osebni SELL Radar</h1>
        <p style="margin:6px 0 0; color:#93c5fd; font-size:9.5pt;">Živo &nbsp;|&nbsp; Generirano: {datum_danes}</p>
    </div>
    
    <div class="grid">
    """
    
    # Sortiramo tako, da so najbolj nevarni (najvišji OGM SELL FACTOR) na prvem mestu
    rezultati_sorted = sorted(rezultati, key=lambda x: x['score'], reverse=True)
    
    for r in rezultati_sorted:
        rast_color = "#dc2626" if r['rast_3m'] >= MIN_3M_RAST else "#64748b"
        
        html += f"""
        <div class="card" style="border-top-color: {r['barva']};">
            <div class="ticker">{r['ticker']}</div>
            <div class="price">${r['cena']:.2f}</div>
            <div class="status-badge" style="background-color: {r['barva']};">{r['status']}</div>
            
            <div class="metric">
                <span>OGM SELL FACTOR:</span>
                <span class="metric-val" style="color: #f1f5f9; font-size: 11pt;">{r['score']:.1f} / 100</span>
            </div>
            <div class="metric">
                <span>3M Rast (Nevarnost >30.4%):</span>
                <span class="metric-val" style="color: {rast_color}">+{r['rast_3m']:.1f} %</span>
            </div>
            <div class="metric">
                <span>RSI (14w):</span>
                <span class="metric-val">{r['rsi']:.1f}</span>
            </div>
            <div class="metric">
                <span>Oddaljenost od 200w MA:</span>
                <span class="metric-val">+{r['dist_10']:.1f} %</span>
            </div>
            
            <div class="action-box">
                <div class="action-title">AI Navodilo:</div>
                {r['akcija']}
            </div>
        </div>
        """
        
    html += """
    </div>
    </div><!-- /page-wrap -->
    </body>
    </html>
    """
    
    ime_datoteke = "OGM_PORTFOLIO_LIVE_SELL.html"
    with open(ime_datoteke, "w", encoding="utf-8") as f:
        f.write(html)
        
    print(f"\n[USPEH] Živi radar je ustvarjen: '{ime_datoteke}'")
    if os.environ.get("CI") != "true":
        webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

if __name__ == "__main__":
    analiziraj_moj_portfelj()