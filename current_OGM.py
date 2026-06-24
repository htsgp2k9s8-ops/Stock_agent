import yfinance as yf
import pandas as pd
import numpy as np
import schedule
import time
from datetime import datetime
import webbrowser
import os

print("=========================================================")
print("AI OGM LIVE DASHBOARD - IZPIS VSEH 30 DELNIC BREZ FILTRA")
print("=========================================================")

# Seznam 30 največjih velikanov trga
top30_tickerji = [
    "MSFT", "AAPL", "NVDA", "AMZN", "META", "GOOGL", "BRK-B", "LLY", "AVGO", "JPM",
    "TSLA", "XOM", "UNH", "V", "MA", "PG", "COST", "HD", "JNJ", "NFLX",
    "MRK", "ABBV", "BAC", "AMD", "ADBE", "CRM", "CVX", "PEP", "TMO", "KO", "ALL"
]

def skeniraj_vse_top_30():
    print(f"\n[START] Začenjam živi OGM sken za vseh 30 delnic...")
    trenutno_leto = datetime.now().year
    rezultati = []
    
    for krog, ticker in enumerate(top30_tickerji, 1):
        try:
            delnica = yf.Ticker(ticker)
            # Podatki od leta 2021 za brezhiben izračun tedenskega MA200
            data = delnica.history(start="2021-01-01", interval="1wk", top_level_only=True, actions=False)
            
            # Varnostni pregled pred praznimi podatki
            if data is None or data.empty or len(data) < 205:
                continue
                
            close_prices = data['Close'].dropna().squeeze()
            if close_prices.empty or len(close_prices) < 205:
                continue
            
            # Tehnični izračuni OGM Matrike
            ma200 = close_prices.rolling(window=200).mean()
            pct_ma = ((close_prices - ma200) / ma200) * 100

            delta = close_prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rsi = 100 - (100 / (1 + (gain / loss)))
            
            # Zadnje razpoložljive vrednosti za ta vikend / danes
            trenutna_cena = close_prices.iloc[-1]
            oddaljenost_ma = pct_ma.iloc[-1]
            trenutni_rsi = rsi.iloc[-1]
            
            if pd.isna(oddaljenost_ma) or pd.isna(trenutni_rsi): 
                continue
                
            trend_ok = oddaljenost_ma >= 0
            
            # 1. Tvoja nelinearna skala za 200-week MA
            if oddaljenost_ma >= 0:
                tocke_ma = np.interp(oddaljenost_ma, [0, 2, 10, 25, 50], [33.0, 35.0, 22.0, 8.0, 0.0])
            else:
                tocke_ma = np.interp(oddaljenost_ma, [-20, -10, -5, 0], [0.0, 12.0, 25.0, 33.0])
                
            # 2. Tvoja nelinearna skala za RSI
            tocke_rsi = np.interp(trenutni_rsi, [30, 45, 60, 70, 80], [10.0, 8.0, 5.0, 2.0, 0.0])
            
            # Fiksni fundamentalni del za vrhunska podjetja
            fundamenti_skupaj = 45.0 
            ogm_trenutni = min(100.0, tocke_ma + tocke_rsi + fundamenti_skupaj)
            
            # --- IZRAČUN DONOSNOSTI ---
            # Kratkoročni trend (Zadnjih 5 tednov = cca 1 mesec)
            cena_1m_nazaj = close_prices.iloc[-5] if len(close_prices) > 5 else close_prices.iloc[0]
            donos_1m = ((trenutna_cena - cena_1m_nazaj) / cena_1m_nazaj) * 100
            
            # Letni trend (YTD od prvega trgovalnega tedna trenutnega leta)
            vsi_datumi = close_prices.index
            datumi_trenutnega_leta = vsi_datumi[vsi_datumi.year == trenutno_leto]
            if len(datumi_trenutnega_leta) > 0:
                cena_zacetek_leta = close_prices.loc[datumi_trenutnega_leta[0]]
                if isinstance(cena_zacetek_leta, pd.Series): 
                    cena_zacetek_leta = cena_zacetek_leta.iloc[0]
                donos_ytd = ((trenutna_cena - cena_zacetek_leta) / cena_zacetek_leta) * 100
            else:
                donos_ytd = 0.0
            
            # Določitev statusov (Ker izpisujemo vse, bo večina v stanju OPAZOVANJA)
            if ogm_trenutni >= 80.0 and trend_ok: status = "STRONG BUY"
            elif ogm_trenutni >= 65.0 and trend_ok: status = "BUY"
            elif not trend_ok: status = "WARNING (POD 200-MA)"
            else: status = "OPAZOVANJE"
                
            # Shranimo rezultat za VSAKO delnico (Brez IF filtra)
            rezultati.append({
                "Ticker": ticker, "Cena": trenutna_cena, "OGM": ogm_trenutni,
                "Status": status, "1M_Donos": donos_1m, "YTD_Donos": donos_ytd
            })
            
            # Kratek premor za stabilnost
            time.sleep(0.04)
        except Exception:
            continue

    generiraj_html_porocilo(rezultati)

# ==============================================================================
# 3. GENERIRANJE HTML ŽIVEGA UKAZNEGA RADARJA
# ==============================================================================
def generiraj_html_porocilo(podatki):
    df_html = pd.DataFrame(podatki)
    if not df_html.empty: 
        df_html = df_html.sort_values(by="OGM", ascending=False)
        
    datum_danes = datetime.now().strftime("%d.%m.%Y")
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>OGM Živi Radar - TOP 30 celotna lista</title>
    <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #1e293b; background-color: #f8fafc; margin: 40px auto; max-width: 1100px; padding: 0 20px; }}
    .header {{ background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%); color: #ffffff; padding: 30px; border-radius: 8px; border-bottom: 4px solid #1d4ed8; }}
    .header h1 {{ margin: 0; font-size: 22pt; font-weight: 700; }}
    .header p {{ margin: 5px 0 0 0; color: #93c5fd; font-size: 11pt; }}
    .section-title {{ font-size: 14pt; color: #0f172a; border-left: 5px solid #2563eb; padding-left: 12px; margin-top: 35px; margin-bottom: 15px; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
    th {{ background-color: #1e293b; color: #ffffff; text-align: left; padding: 12px 10px; font-size: 9.5pt; font-weight: 600; }}
    td {{ padding: 12px 10px; border-bottom: 1px solid #e2e8f0; font-size: 9.5pt; }}
    tr:nth-child(even) {{ background-color: #f8fafc; }}
    tr:hover {{ background-color: #f1f5f9; }}
    .badge {{ padding: 4px 8px; border-radius: 4px; font-weight: 700; font-size: 8.5pt; display: inline-block; }}
    .strong-buy {{ background-color: #dcfce7; color: #15803d; }}
    .buy {{ background-color: #e0f2fe; color: #0369a1; }}
    .warning {{ background-color: #fee2e2; color: #b91c1c; }}
    .opazovanje {{ background-color: #f1f5f9; color: #475569; }}
    .pos-return {{ color: #16a34a; font-weight: 600; }}
    .neg-return {{ color: #dc2626; font-weight: 600; }}
    </style>
    </head>
    <body>

    <div class="header">
        <h1>OVNICEK GROWTH MATRIX &mdash; ŽIVI PRESEK ZA VSEH 30 GIGANTOV</h1>
        <p>Celotna lista brez filtrov minimalnega praga, sortirana od relativno najmočnejše navzdol | Osveženo: {datum_danes}</p>
    </div>

    <div class="section-title">Trenutna borzna matrika (Vseh 30 podjetij)</div>
    <table>
        <thead>
            <tr>
                <th>Ticker</th>
                <th>Trenutna cena</th>
                <th>Trenutni OGM Score</th>
                <th>Uradni status</th>
                <th>Performance (Zadnji 1 mesec)</th>
                <th>Performance (YTD)</th>
            </tr>
        </thead>
        <tbody>
    """
    
    if not df_html.empty:
        for _, row in df_html.iterrows():
            if row['Status'] == "STRONG BUY": badge_class = "strong-buy"
            elif row['Status'] == "BUY": badge_class = "buy"
            elif "WARNING" in row['Status']: badge_class = "warning"
            else: badge_class = "opazovanje"
            
            class_1m = "pos-return" if row['1M_Donos'] >= 0 else "neg-return"
            class_ytd = "pos-return" if row['YTD_Donos'] >= 0 else "neg-return"
            
            html_content += f"""
                <tr>
                    <td><strong>{row['Ticker']}</strong></td>
                    <td style="font-weight: 600;">${row['Cena']:.2f}</td>
                    <td style="font-weight: 700; font-size: 10pt; color: #0f172a;">{row['OGM']:.1f} / 100</td>
                    <td><span class="badge {badge_class}">{row['Status']}</span></td>
                    <td class="{class_1m}">{row['1M_Donos']:+.1f} %</td>
                    <td class="{class_ytd}">{row['YTD_Donos']:+.1f} %</td>
                </tr>
            """
    else:
        html_content += """<tr><td colspan="6" style="text-align: center; padding: 20px; color: #64748b;">Ni podatkov za izpis.</td></tr>"""
        
    html_content += """</tbody></table></body></html>"""
    
    ime_datoteke = "OGM_LIVE_DASHBOARD_TOP30.html"
    with open(ime_datoteke, "w", encoding="utf-8") as f: 
        f.write(html_content)
    print(f"\n[USPEH] Popolno živo poročilo za vseh 30 delnic je ustvarjeno: '{ime_datoteke}'")
    webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

# ==============================================================================
# 4. ZAGON AGENTA
# ==============================================================================
def sprozi_agent_top30():
    print(f"\n=== PROŽENJE TOP 30 CELOTNE ANALIZE: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} ===")
    skeniraj_vse_top_30()
    print("\n[KONČANO] Živi radar je odprt v tvojem brskalniku.")

schedule.every().friday.at("22:30").do(sprozi_agent_top30)

# Takojšnji štart ob zagonu
sprozi_agent_top30()

while True:
    schedule.run_pending()
    time.sleep(60)