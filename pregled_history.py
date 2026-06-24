import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import webbrowser
import os

print("=========================================================")
print("AI OGM BACKTESTER - STROGO 1 VRSTICA NA POSAMEZNO DELNICO")
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

# Odstranitev duplikatov med indeksoma
vsi_izbrani_tickerji = list(set(nasdaq50_tickerji + sp500_50_tickerji))

# ==============================================================================
# 2. GLAVNI BACKTEST ENGINE (Z globalno zaporo za podvajanje podjetij)
# ==============================================================================
def zaženi_ogm_backtest():
    skrajni_rok_za_signale = (datetime.now() - timedelta(days=365)).date()
    
    print(f"[INFO] Analiziram {len(vsi_izbrani_tickerji)} unikatnih podjetij.")
    print(f"[START] Iskanje zgodovinskih prebojev...")
    vsi_zgodovinski_signali = []
    
    # Globalni register, ki bo preprečil, da se isti tiker v tabeli pojavi večkrat
    obdelani_globalni_tickerji = set()
    
    for krog, ticker in enumerate(vsi_izbrani_tickerji, 1):
        if krog % 15 == 0:
            print(f"    ... obdelano {krog} / {len(vsi_izbrani_tickerji)} delnic ...")
            
        try:
            delnica = yf.Ticker(ticker)
            
            try:
                ime_podjetja = delnica.info.get('longName', ticker)
            except Exception:
                ime_podjetja = ticker
                
            data = delnica.history(start="2021-01-01", interval="1wk", actions=False)
            
            if data is None or data.empty or len(data) < 205:
                continue
            
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
                
            close_series = data['Close'].dropna()
            if close_series.empty or len(close_series) < 205:
                continue
                
            close_prices = pd.Series(close_series.values, index=close_series.index)
            
            # Izračun tehničnih indikatorjev
            ma200 = close_prices.rolling(window=200).mean()
            pct_ma = ((close_prices - ma200) / ma200) * 100

            delta = close_prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rsi = 100 - (100 / (1 + (gain / loss)))
            
            # Brskamo kronološko od najstarejših podatkov proti najnovejšim
            for pozicija, idx in enumerate(close_prices.index):
                datum_tedna = idx.date()
                
                # Varnostni časovni ščit (minilo mora vsaj 12 mesecev od danes)
                if datum_tedna > skrajni_rok_za_signale:
                    break 
                
                # Če smo za to delnico v preteklosti že našli in zapisali preboj, 
                # prekinemo zanko in ne iščemo novih signalov (s tem preprečimo duplikate)
                if ticker in obdelani_globalni_tickerji:
                    break
                
                oddaljenost_ma = pct_ma.loc[idx]
                trenutni_rsi = rsi.loc[idx]
                cena_takrat = float(close_prices.loc[idx])
                
                if pd.isna(oddaljenost_ma) or pd.isna(trenutni_rsi): 
                    continue
                    
                trend_ok = oddaljenost_ma >= 0
                
                # Izračun točk OGM
                if oddaljenost_ma >= 0:
                    tocke_ma = np.interp(oddaljenost_ma, [0, 2, 10, 25, 50], [33.0, 35.0, 22.0, 8.0, 0.0])
                else:
                    tocke_ma = np.interp(oddaljenost_ma, [-20, -10, -5, 0], [0.0, 12.0, 25.0, 33.0])
                    
                tocke_rsi = np.interp(trenutni_rsi, [30, 45, 60, 70, 80], [10.0, 8.0, 5.0, 2.0, 0.0])
                fundamenti_skupaj = 45.0 
                ogm_tedenski = min(100.0, tocke_ma + tocke_rsi + fundamenti_skupaj)
                
                # Pogoj OGM >= 80 (Nakupni signal)
                if ogm_tedenski >= 80.0 and trend_ok:
                    # Izračun uspešnosti po točno 12 mesecih (52 tednov naprej)
                    if pozicija + 52 < len(close_prices):
                        cena_po_12m = float(close_prices.iloc[pozicija + 52])
                        donos_12m = ((cena_po_12m - cena_takrat) / cena_takrat) * 100
                        tekst_12m = f"{donos_12m:+.1f} %"
                        barva_klasa = "pos-return" if donos_12m >= 0 else "neg-return"
                        
                        vsi_zgodovinski_signali.append({
                            "Ticker": ticker,
                            "Ime": ime_podjetja,
                            "Datum": str(datum_tedna),
                            "Cena": cena_takrat,
                            "OGM": ogm_tedenski,
                            "Donos12M": tekst_12m,
                            "BarvaClass": barva_klasa
                        })
                        
                        # STROGI POPRAVEK: Ticker dodamo v register obdelanih, 
                        # zanka se bo v naslednjem koraku takoj prekinila in duplikata ne bo!
                        obdelani_globalni_tickerji.add(ticker)
                        
            time.sleep(0.04)
        except Exception:
            continue

    generiraj_html_backtest(vsi_zgodovinski_signali)

# ==============================================================================
# 3. GENERIRANJE HTML POROČILA Z GUMBOM ZA PDF
# ==============================================================================
def generiraj_html_backtest(podatki):
    df_html = pd.DataFrame(podatki)
    if not df_html.empty: 
        df_html = df_html.sort_values(by="Datum", ascending=False)
        
    datum_danes = datetime.now().strftime("%d.%m.%Y")
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>OGM Unikatni 12M Signali</title>
    <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #1e293b; background-color: #f8fafc; margin: 40px auto; max-width: 1250px; padding: 0 20px; }}
    .header {{ background: linear-gradient(135deg, #111827 0%, #dc2626 100%); color: #ffffff; padding: 30px; border-radius: 8px; border-bottom: 4px solid #991b1b; position: relative; }}
    .header h1 {{ margin: 0; font-size: 22pt; font-weight: 700; }}
    .header p {{ margin: 5px 0 0 0; color: #fecaca; font-size: 11pt; }}
    
    .btn-pdf {{ position: absolute; right: 30px; top: 35px; background-color: #ffffff; color: #dc2626; border: none; padding: 12px 20px; border-radius: 6px; font-weight: 700; font-size: 10pt; cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: 0.2s; }}
    .btn-pdf:hover {{ background-color: #f3f4f6; transform: translateY(-1px); }}
    
    .section-title {{ font-size: 14pt; color: #0f172a; border-left: 5px solid #dc2626; padding-left: 12px; margin-top: 35px; margin-bottom: 15px; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
    th {{ background-color: #1e293b; color: #ffffff; text-align: left; padding: 12px 10px; font-size: 9.5pt; font-weight: 600; }}
    td {{ padding: 11px 10px; border-bottom: 1px solid #e2e8f0; font-size: 9.5pt; }}
    tr:nth-child(even) {{ background-color: #f8fafc; }}
    tr:hover {{ background-color: #f1f5f9; }}
    .badge {{ padding: 4px 8px; border-radius: 4px; font-weight: 700; font-size: 8.5pt; display: inline-block; background-color: #fef2f2; color: #991b1b; border: 1px solid #fee2e2; }}
    .pos-return {{ color: #16a34a; font-weight: 700; }}
    .neg-return {{ color: #dc2626; font-weight: 700; }}
    
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
        <h1>OVNICEK GROWTH MATRIX &mdash; POTRJENI UNIKATNI 12M REZULTATI</h1>
        <p>Arhiv čistih signalov (OGM &ge; 80) &mdash; Izpisana je natanko ena (prva kronološka) vrstica za posamezno delnico | Osveženo: {datum_danes}</p>
        <button class="btn-pdf" onclick="window.print()">Izvozi v PDF</button>
    </div>

    <div class="section-title">Pregled zgodovinske uspešnosti signalov (Brez kakršnegakoli podvajanja podjetij)</div>
    <table>
        <thead>
            <tr>
                <th>Datum prvega preboja</th>
                <th>Ticker</th>
                <th>Ime podjetja</th>
                <th>Cena ob vstopu</th>
                <th>Dosežen OGM Score</th>
                <th>Uradni status</th>
                <th>Končni donos po 12 mesecih</th>
            </tr>
        </thead>
        <tbody>
    """
    
    if not df_html.empty:
        for _, row in df_html.iterrows():
            html_content += f"""
                <tr>
                    <td style="font-weight: 600; color: #475569;">{row['Datum']}</td>
                    <td><strong>{row['Ticker']}</strong></td>
                    <td style="color: #0f172a;">{row['Ime']}</td>
                    <td style="font-weight: 500;">${row['Cena']:.2f}</td>
                    <td style="font-weight: 700; color: #991b1b;">{row['OGM']:.1f} / 100</td>
                    <td><span class="badge">STRONG BUY</span></td>
                    <td class="{row['BarvaClass']}">{row['Donos12M']}</td>
                </tr>
            """
    else:
        html_content += """<tr><td colspan="7" style="text-align: center; padding: 20px; color: #64748b;">V varnem zgodovinskem oknu ni zaznanih prebojev z OGM >= 80.</td></tr>"""
        
    html_content += """</tbody></table></body></html>"""
    
    ime_datoteke = "OGM_UNIKATNI_BACKTEST.html"
    with open(ime_datoteke, "w", encoding="utf-8") as f: 
        f.write(html_content)
    print(f"\n[USPEH] Poročilo brez kakršnihkoli duplikatov je uspešno ustvarjeno: '{ime_datoteke}'")
    webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

# ==============================================================================
# 3. ZAGON BACKTEST ENGINE-A
# ==============================================================================
zaženi_ogm_backtest()