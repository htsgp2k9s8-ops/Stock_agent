import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import webbrowser
import os
import time

print("=========================================================")
print("🚨 OGM SELL STRATEGIJA: RAZŠIRJEN NASDAQ (Brez Hyperscalerjev)")
print("=========================================================")

# Razširjen nabor NASDAQ delnic (Brez NVDA, TSLA, AMD)
TICKERJI = [
    "AAPL", "MSFT", "AMZN", "META", "GOOGL", "NFLX", "ADBE", "CRM", "INTC", "CSCO", 
    "CMCSA", "PEP", "AVGO", "TXN", "AMGN", "HON", "QCOM", "SBUX", "GILD", "INTU", 
    "MDLZ", "ISRG", "BKNG", "ADI", "REGN", "VRTX", "LRCX", "MU", "ATVI", "MELI", 
    "PYPL", "SNPS", "ASML", "KLAC", "CDNS", "MAR", "PANW", "CTAS", "WDAY", "ORLY", 
    "NXPI", "MNST", "FTNT", "PCAR", "PAYX", "CPRT", "ROST", "MCHP", "KDP", "AEP",
    "BIIB", "VRSK", "EA", "TTWO", "ILMN", "ALGN", "IDXX", "ODFL", "EXC", "XEL", "FAST"
]

# Prilagojen filter za normalne delnice (25% v 3 mesecih je za te delnice ogromen skok)
MIN_3M_RAST = 25.0  

def izracunaj_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def testiraj_in_generiraj_porocilo():
    kronoloski_signali = []
    
    print(f"Skeniram {len(TICKERJI)} delnic (Obdobje do 31.12.2023)...")
    print(f"-> Pogoj: Rast v zadnjih 3 mesecih mora biti vsaj {MIN_3M_RAST}%")
    print("To lahko traja do 1 minute, prosim počakaj.\n")
    
    for count, ticker in enumerate(TICKERJI, 1):
        print(f"[{count}/{len(TICKERJI)}] Obdelujem: {ticker:<6} ...", end=" ")
        try:
            delnica = yf.Ticker(ticker)
            # ZAKLENJENO OBDOBJE NA KRAJ LETA 2023
            data = delnica.history(start="2016-01-01", end="2023-12-31", interval="1wk", actions=False)
            
            if len(data) < 210:
                print("[PREMALO PODATKOV]")
                continue
                
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
                
            close = data['Close']
            ma10 = close.rolling(window=10).mean()
            ma50 = close.rolling(window=50).mean()
            ma200 = close.rolling(window=200).mean()
            ma100_avg = close.rolling(window=100).mean() 
            rsi = izracunaj_rsi(close)
            
            # Razmaki in metrike
            dist_10_200 = ((ma10 - ma200) / ma200) * 100
            dist_50_200 = ((ma50 - ma200) / ma200) * 100
            
            past_ma10 = ma10.shift(10)
            strmina_10w = ((ma10 - past_ma10) / past_ma10) * 100
            pe_stretch = ((close - ma100_avg) / ma100_avg) * 100
            
            # Zgodovinska rast cene v zadnjih 12 tednih (3 meseci)
            rast_12w = ((close - close.shift(12)) / close.shift(12)) * 100
            
            # Interpolirane uteži (Risk Score 0-100)
            score_rsi = np.interp(rsi.values, [65, 75, 85], [0.0, 10.0, 20.0])
            score_d10 = np.interp(dist_10_200.values, [50, 70, 100], [0.0, 15.0, 25.0])
            score_d50 = np.interp(dist_50_200.values, [30, 40, 60], [0.0, 10.0, 15.0])
            score_strmina = np.interp(strmina_10w.values, [10, 12, 20], [0.0, 10.0, 20.0])
            score_pe = np.interp(pe_stretch.values, [30, 40, 60], [0.0, 10.0, 20.0])
            
            klimaks_score = score_rsi + score_d10 + score_d50 + score_strmina + score_pe
            
            oborozen_counter = 0
            st_signalov_za_delnico = 0
            zadnji_signal_idx = -999 
            
            for i in range(210, len(data)):
                trenutni_datum = data.index[i]
                trenutni_score = klimaks_score[i]
                trenutna_rast_3m = rast_12w.iloc[i]
                
                # Sistem oborožimo samo ob ekstremnem pospešku
                ima_ekstremno_rast = (trenutna_rast_3m >= MIN_3M_RAST)
                
                if trenutni_score >= 75.0 and ima_ekstremno_rast:
                    oborozen_counter = 4
                    
                # SPROŽILCI (TRIGGERS)
                dva_padajoca_tedna = (close.iloc[i] < close.iloc[i-1]) and (close.iloc[i-1] < close.iloc[i-2])
                je_ekstremno_pregreto = (rsi.iloc[i] > 75) and (strmina_10w.iloc[i] > 15) and (pe_stretch.iloc[i] > 40)
                trigger_klimaks = (oborozen_counter > 0) and dva_padajoca_tedna and je_ekstremno_pregreto
                
                cena_pod_10ma = close.iloc[i] < ma10.iloc[i]
                prej_nad_10ma = close.iloc[i-1] >= ma10.iloc[i-1]
                trigger_trend_break = (oborozen_counter > 0) and cena_pod_10ma and prej_nad_10ma
                
                trigger_parabola = (trenutni_score >= 90.0) and ima_ekstremno_rast
                
                # COOLDOWN POGOJ (8 tednov)
                dovolj_casa_minilo = (i - zadnji_signal_idx) >= 8
                
                if (trigger_klimaks or trigger_trend_break or trigger_parabola) and dovolj_casa_minilo:
                    razlog = ""
                    if trigger_parabola: razlog = "PARABOLA (>90)"
                    elif trigger_trend_break: razlog = "ZLOM 10w MA"
                    elif trigger_klimaks: razlog = "KLIMAKS (2w padec)"
                    
                    cena_ob_signalu = close.iloc[i]
                    idx_fut = min(i + 12, len(data) - 1)
                    cena_fut = close.iloc[idx_fut]
                    padec_po_signalu = ((cena_fut - cena_ob_signalu) / cena_ob_signalu) * 100
                    
                    kronoloski_signali.append({
                        "ticker": ticker,
                        "datum": trenutni_datum.strftime("%Y-%m-%d"),
                        "razlog": razlog,
                        "rast_3m": round(trenutna_rast_3m, 1),
                        "score": round(trenutni_score, 1),
                        "cena": round(cena_ob_signalu, 2),
                        "rsi": round(rsi.iloc[i], 1),
                        "donos_3m": round(padec_po_signalu, 1)
                    })
                    st_signalov_za_delnico += 1
                    zadnji_signal_idx = i  
                    oborozen_counter = 0   
                    
                if oborozen_counter > 0:
                    oborozen_counter -= 1
                    
            print(f"[OK - Najdenih {st_signalov_za_delnico} signalov]")
            time.sleep(0.02)
            
        except Exception as e:
            print(f"[NAPAKA: {e}]")
            
    sestavi_html_porocilo(kronoloski_signali)

def sestavi_html_porocilo(signali):
    df = pd.DataFrame(signali)
    if not df.empty:
        df = df.sort_values(by=["datum"], ascending=False)
        uspesni_signali = df[df['donos_3m'] < 0].shape[0]
        win_rate = (uspesni_signali / df.shape[0]) * 100 if df.shape[0] > 0 else 0
        povprecen_padec = df['donos_3m'].mean()
    else:
        win_rate = 0
        povprecen_padec = 0
        
    datum_danes = datetime.now().strftime("%d.%m.%Y ob %H:%M")
    
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>OGM SELL Strategija - Obdobje do 2023</title>
    <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f8fafc; color: #1e293b; padding: 30px; max-width: 1250px; margin: 0 auto; }}
    .header {{ background: linear-gradient(135deg, #450a0a 0%, #991b1b 100%); color: white; padding: 30px; border-radius: 8px; margin-bottom: 25px; position: relative; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
    .header h1 {{ margin: 0; font-size: 24pt; }}
    .header p {{ margin: 5px 0 0 0; color: #fca5a5; }}
    
    .btn-pdf {{ position: absolute; right: 30px; top: 35px; background-color: #ef4444; color: white; border: none; padding: 12px 20px; border-radius: 6px; font-weight: 700; font-size: 10pt; cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: 0.2s; }}
    .btn-pdf:hover {{ background-color: #dc2626; }}
    
    .summary-box {{ display: flex; gap: 20px; margin-bottom: 30px; }}
    .stat-card {{ background-color: white; padding: 20px; border-radius: 8px; border: 1px solid #e2e8f0; flex: 1; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
    .stat-card h3 {{ margin: 0; color: #64748b; font-size: 10pt; text-transform: uppercase; letter-spacing: 0.5px; }}
    .stat-card p {{ margin: 10px 0 0 0; font-size: 22pt; font-weight: bold; color: #991b1b; }}
    
    table {{ width: 100%; border-collapse: collapse; background-color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border-radius: 8px; overflow: hidden; border: 1px solid #e2e8f0; }}
    th {{ background-color: #0f172a; color: white; padding: 14px 12px; text-align: left; font-size: 10pt; font-weight: 600; }}
    td {{ padding: 12px; border-bottom: 1px solid #e2e8f0; font-size: 9.5pt; }}
    tr:nth-child(even) {{ background-color: #f8fafc; }}
    tr:hover {{ background-color: #f1f5f9; }}
    
    .badge {{ padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 8.5pt; display: inline-block; }}
    .badge-parabola {{ background-color: #fce7f3; color: #9d174d; border: 1px solid #fbcfe8; }}
    .badge-trend {{ background-color: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }}
    .badge-klimaks {{ background-color: #fef3c7; color: #92400e; border: 1px solid #fde68a; }}
    
    .status-win {{ background-color: #dcfce7; color: #16a34a; font-weight: bold; }}
    .status-loss {{ background-color: #fee2e2; color: #dc2626; font-weight: bold; }}
    .momentum-text {{ color: #2563eb; font-weight: bold; }}
    </style>
    </head>
    <body>

    <div class="header">
        <h1>OGM SELL Strategija &mdash; Tradicionalni NASDAQ (do 31.12.2023)</h1>
        <p>Preizkus na 60+ delnicah, brez AMD/NVDA/TSLA | Pogoj: >25% rast v 3 mesecih</p>
        <button class="btn-pdf" onclick="window.print()">📥 Izvozi v PDF</button>
    </div>
    
    <div class="summary-box">
        <div class="stat-card">
            <h3>Skupno št. signalov</h3>
            <p style="color: #0f172a;">{df.shape[0] if not df.empty else 0}</p>
        </div>
        <div class="stat-card">
            <h3>Uspešnost (Win-Rate)</h3>
            <p style="color: #16a34a;">{win_rate:.1f} %</p>
        </div>
        <div class="stat-card">
            <h3>Povprečen premik (3M po prodaji)</h3>
            <p>{povprecen_padec:.1f} %</p>
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th>Ticker</th>
                <th>Datum signala</th>
                <th>Sprožilec (Razlog)</th>
                <th>Rast pred vrhom (Zadnji 3M)</th>
                <th>Risk Score (0-100)</th>
                <th>Cena ob prodaji</th>
                <th>RSI ob vrhu</th>
                <th>Rezultat (Cena čez 3 mesece)</th>
            </tr>
        </thead>
        <tbody>
    """
    
    if not df.empty:
        for _, row in df.iterrows():
            if "PARABOLA" in row['razlog']: badge_class = "badge-parabola"
            elif "10w MA" in row['razlog']: badge_class = "badge-trend"
            else: badge_class = "badge-klimaks"
            
            # Negativen donos = uspeh (izognili smo se padcu)
            td_class = "status-win" if row['donos_3m'] < 0 else "status-loss"
            
            html_template += f"""
            <tr>
                <td style="font-weight: bold; color: #0f172a; font-size: 10.5pt;">{row['ticker']}</td>
                <td>{row['datum']}</td>
                <td><span class="badge {badge_class}">{row['razlog']}</span></td>
                <td class="momentum-text">+{row['rast_3m']:.1f} %</td>
                <td style="font-weight: 600;">{row['score']:.1f} / 100</td>
                <td style="font-weight: 600;">${row['cena']:.2f}</td>
                <td>{row['rsi']:.1f}</td>
                <td class="{td_class}">{row['donos_3m']:+.1f} %</td>
            </tr>
            """
    else:
        html_template += """<tr><td colspan="8" style="text-align:center; color:#64748b;">Ni najdenih ustreznih signalov pregrevanja v tem obdobju.</td></tr>"""
        
    html_template += """
        </tbody>
    </table>
    </body>
    </html>
    """
    
    ime_datoteke = "OGM_SELL_STRATEGY_REPORT.html"
    with open(ime_datoteke, "w", encoding="utf-8") as f:
        f.write(html_template)
        
    print(f"\n[USPEH] Profesionalno zbirno poročilo je ustvarjeno: '{ime_datoteke}'")
    webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

if __name__ == "__main__":
    testiraj_in_generiraj_porocilo()