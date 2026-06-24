import yfinance as yf
import pandas as pd
import numpy as np
import schedule
import time
from datetime import datetime
import webbrowser
import os

print("=========================================================")
print("AI OGM LIVE DASHBOARD - MASTER RAZLIČICA (TOP 100)")
print("=========================================================")

# ==============================================================================
# 1. PREČIŠČEN ZDRUŽEN SEZNAM TOP 50 NASDAQ + TOP 50 S&P 500
# ==============================================================================
nasdaq50_tickerji = [
    "MSFT", "AAPL", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "AVGO", "TSLA", "COST",
    "NFLX", "AMD", "ADBE", "ASML", "PEP", "LIN", "AZN", "CSCO", "TMUS", "PDD",
    "INTU", "QUAL", "AMAT", "TXN", "CMCSA", "AMGN", "HON", "ISRG", "BKNG", "VRTX",
    "GILD", "REGN", "MDLZ", "PANW", "MELI", "ADP", "LRCX", "MU", "ADI", "KLAC",
    "SNPS", "CDNS", "PYPL", "MAR", "CSX", "CRWD", "NXPI", "CTSH", "MNST", "ROST"
]

sp500_50_tickerji = [
    "MSFT", "AAPL", "NVDA", "AMZN", "META", "GOOGL", "BRK-B", "LLY", "AVGO", "JPM",
    "TSLA", "XOM", "UNH", "V", "MA", "PG", "COST", "HD", "JNJ", "NFLX",
    "MRK", "ABBV", "BAC", "AMD", "ADBE", "CRM", "CVX", "PEP", "TMO", "KO",
    "WMT", "WFC", "ACN", "DIS", "PM", "CSCO", "INTC", "ORCL", "CMCSA", "VZ", 
    "INTU", "ABT", "QCOM", "PFE", "AMGN", "DHR", "IBM", "TXN", "UNP", "GE"
]

vsi_izbrani_tickerji = list(set(nasdaq50_tickerji + sp500_50_tickerji))

# ==============================================================================
# 2. ŽIVI SKENER (Z napredno YTD varovalko pred NaN vrednostmi)
# ==============================================================================
def skeniraj_trg():
    print(f"\n[START] Začenjam živi sken za {len(vsi_izbrani_tickerji)} unikatnih delnic...")
    trenutno_leto = datetime.now().year
    rezultati = []
    
    for krog, ticker in enumerate(vsi_izbrani_tickerji, 1):
        if krog % 20 == 0:
            print(f"    ... obdelano {krog} / {len(vsi_izbrani_tickerji)} delnic ...")
            
        try:
            delnica = yf.Ticker(ticker)
            data = delnica.history(start="2021-01-01", interval="1wk", actions=False)
            
            if data is None or data.empty or len(data) < 205:
                continue
            
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
                
            close_series = data['Close'].dropna()
            if close_series.empty or len(close_series) < 205:
                continue
                
            close_prices = pd.Series(close_series.values, index=close_series.index)
            
            # Izračun indikatorjev
            ma200 = close_prices.rolling(window=200).mean()
            pct_ma = ((close_prices - ma200) / ma200) * 100

            delta = close_prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rsi = 100 - (100 / (1 + (gain / loss)))
            
            trenutna_cena = float(close_prices.iloc[-1])
            oddaljenost_ma = float(pct_ma.iloc[-1])
            trenutni_rsi = float(rsi.iloc[-1])
            
            if pd.isna(oddaljenost_ma) or pd.isna(trenutni_rsi): 
                continue
                
            trend_ok = oddaljenost_ma >= 0
            
            if oddaljenost_ma >= 0:
                tocke_ma = np.interp(oddaljenost_ma, [0, 2, 10, 25, 50], [33.0, 35.0, 22.0, 8.0, 0.0])
            else:
                tocke_ma = np.interp(oddaljenost_ma, [-20, -10, -5, 0], [0.0, 12.0, 25.0, 33.0])
                
            tocke_rsi = np.interp(trenutni_rsi, [30, 45, 60, 70, 80], [10.0, 8.0, 5.0, 2.0, 0.0])
            fundamenti_skupaj = 45.0 
            ogm_trenutni = min(100.0, tocke_ma + tocke_rsi + fundamenti_skupaj)
            
            # 1-mesečni donos
            cena_1m_nazaj = float(close_prices.iloc[-5]) if len(close_prices) > 5 else float(close_prices.iloc[0])
            donos_1m = ((trenutna_cena - cena_1m_nazaj) / cena_1m_nazaj) * 100
            
            # === POPRAVLJEN IN VAREN YTD IZRAČUN ===
            vsi_datumi = close_prices.index
            datumi_trenutnega_leta = vsi_datumi[vsi_datumi.year == trenutno_leto]
            
            try:
                if len(datumi_trenutnega_leta) > 0:
                    cena_zacetek_leta = close_prices.loc[datumi_trenutnega_leta[0]]
                    if isinstance(cena_zacetek_leta, pd.Series): 
                        cena_zacetek_leta = float(cena_zacetek_leta.iloc[0])
                    else:
                        cena_zacetek_leta = float(cena_zacetek_leta)
                else:
                    # Rezervni načrt: če ne najde tekočega leta, pogleda 22 tednov nazaj (začetek leta)
                    cena_zacetek_leta = float(close_prices.iloc[-22])
                
                donos_ytd = ((trenutna_cena - cena_zacetek_leta) / cena_zacetek_leta) * 100
                if pd.isna(donos_ytd): donos_ytd = 0.0
            except Exception:
                donos_ytd = 0.0
            
            pripadnost = "S&P 500 & NSDQ" if (ticker in nasdaq50_tickerji and ticker in sp500_50_tickerji) else ("NASDAQ 100" if ticker in nasdaq50_tickerji else "S&P 500")
            
            if ogm_trenutni >= 80.0 and trend_ok: status = "STRONG BUY"
            elif ogm_trenutni >= 65.0 and trend_ok: status = "BUY"
            elif not trend_ok: status = "WARNING (POD 200-MA)"
            else: status = "OPAZOVANJE"
                
            rezultati.append({
                "Ticker": ticker, "Indeks": pripadnost, "Cena": trenutna_cena, "OGM": ogm_trenutni,
                "Status": status, "1M_Donos": donos_1m, "YTD_Donos": donos_ytd
            })
            
            time.sleep(0.04)
        except Exception:
            continue

    generiraj_html_porocilo(rezultati)

# ==============================================================================
# 3. GENERIRANJE HTML POROČILA Z PAUZAMI ZA STRANI IN GUMBOM ZA PDF
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
    <title>OGM Živi Radar - TOP 100</title>
    <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #1e293b; background-color: #f8fafc; margin: 40px auto; max-width: 1200px; padding: 0 20px; }}
    .header {{ background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 100%); color: #ffffff; padding: 30px; border-radius: 8px; border-bottom: 4px solid #2563eb; position: relative; }}
    .header h1 {{ margin: 0; font-size: 22pt; font-weight: 700; }}
    .header p {{ margin: 5px 0 0 0; color: #bfdbfe; font-size: 11pt; }}
    
    .btn-pdf {{ position: absolute; right: 30px; top: 35px; background-color: #ef4444; color: white; border: none; padding: 12px 20px; border-radius: 6px; font-weight: 700; font-size: 10pt; cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: 0.2s; }}
    .btn-pdf:hover {{ background-color: #doc2626; transform: translateY(-1px); }}
    
    .section-title {{ font-size: 14pt; color: #0f172a; border-left: 5px solid #2563eb; padding-left: 12px; margin-top: 35px; margin-bottom: 15px; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
    th {{ background-color: #1e293b; color: #ffffff; text-align: left; padding: 12px 10px; font-size: 9.5pt; font-weight: 600; }}
    td {{ padding: 11px 10px; border-bottom: 1px solid #e2e8f0; font-size: 9.5pt; }}
    tr:nth-child(even) {{ background-color: #f8fafc; }}
    tr:hover {{ background-color: #f1f5f9; }}
    .badge {{ padding: 4px 8px; border-radius: 4px; font-weight: 700; font-size: 8.5pt; display: inline-block; }}
    .strong-buy {{ background-color: #dcfce7; color: #15803d; }}
    .buy {{ background-color: #e0f2fe; color: #0369a1; }}
    .warning {{ background-color: #fee2e2; color: #b91c1c; }}
    .opazovanje {{ background-color: #f1f5f9; color: #475569; }}
    .pos-return {{ color: #16a34a; font-weight: 600; }}
    .neg-return {{ color: #dc2626; font-weight: 600; }}
    
    @media print {{
        .btn-pdf {{ display: none !important; }}
        body {{ background-color: white; margin: 0; padding: 0; }}
        table {{ box-shadow: none; page-break-inside: auto; }}
        tr {{ page-break-inside: avoid; page-break-after: auto; }}
        thead {{ display: table-header-group; }}
    }}
    </style>
    </head>
    <body>

    <div class="header">
        <h1>OVNICEK GROWTH MATRIX &mdash; ŽIVI MASOVNI RADAR (TOP 100)</h1>
        <p>Združen presek 50 največjih delnic S&P 500 in 50 največjih delnic NASDAQ 100 | Osveženo: {datum_danes}</p>
        <button class="btn-pdf" onclick="window.print()">Izvozi v PDF</button>
    </div>

    <div class="section-title">Trenutna borzna matrika (Združen presek, urejen po OGM moči)</div>
    <table>
        <thead>
            <tr>
                <th>Ticker</th>
                <th>Primarni indeks</th>
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
                    <td style="color: #64748b; font-size: 9pt;">{row['Indeks']}</td>
                    <td style="font-weight: 600;">${row['Cena']:.2f}</td>
                    <td style="font-weight: 700; font-size: 10pt; color: #0f172a;">{row['OGM']:.1f} / 100</td>
                    <td><span class="badge {badge_class}">{row['Status']}</span></td>
                    <td class="{class_1m}">{row['1M_Donos']:+.1f} %</td>
                    <td class="{class_ytd}">{row['YTD_Donos']:+.1f} %</td>
                </tr>
            """
            
    html_content += """</tbody></table></body></html>"""
    
    # Dodatno prečiščevanje surove kode pred pisanjem
    html_content = html_content.replace("NaN", "0.0")
    
    ime_datoteke = "OGM_LIVE_DASHBOARD_TOP100.html"
    with open(ime_datoteke, "w", encoding="utf-8") as f: 
        f.write(html_content)
    print(f"\n[USPEH] Popolno živo poročilo za TOP 100 delnic je zgenerirano: '{ime_datoteke}'")
    webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

# ==============================================================================
# 4. TURNUSNI SISTEM
# ==============================================================================
def sprozi_agent_top100():
    print(f"\n=== PROŽENJE MASOVNE TOP 100 ANALIZE: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} ===")
    skeniraj_trg()
    print("\n[KONČANO] Živi radar za top 100 podjetij je uspešno osvežen.")

schedule.every().friday.at("22:30").do(sprozi_agent_top100)

# Takojšnji start ob zagonu
# sprozi_agent_top100()

while True:
    schedule.run_pending()
    time.sleep(60)