import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import webbrowser
import os
import time

print("=========================================================")
print("📉 OGM SELL STRATEGIJA: ANALIZA ZGODOVINSKIH VRHOV")
print("=========================================================")

# Nabor 50 prepoznavnih NASDAQ / Tech delnic
TICKERJI = [
    "AAPL", "MSFT", "AMZN", "NVDA", "META", "GOOGL", "TSLA", "NFLX", "AMD", "ADBE",
    "CRM", "INTC", "CSCO", "CMCSA", "PEP", "AVGO", "TXN", "AMGN", "HON", "QCOM",
    "SBUX", "GILD", "INTU", "MDLZ", "ISRG", "BKNG", "ADI", "REGN", "VRTX", "LRCX",
    "MU", "ATVI", "MELI", "PYPL", "SNPS", "ASML", "KLAC", "CDNS", "MAR", "PANW",
    "CTAS", "WDAY", "ORLY", "NXPI", "MNST", "FTNT", "PCAR", "PAYX", "CPRT", "ROST"
]

def izracunaj_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def poisi_zgodovinski_vrh_in_padec(data):
    """
    Algoritem za iskanje večjega padca (>20%).
    Sprehodi se skozi cene, beleži lokalni maksimum in preveri,
    če je cena od tega maksimuma padla za več kot 20%.
    Vrne prvi velik zlom (ali tistega z najvišjim donosom pred njim).
    """
    max_price = 0
    max_date = None
    
    najboljsi_vrh = None
    najvecji_padec = 0
    
    for date, price in data['Close'].items():
        if price > max_price:
            max_price = price
            max_date = date
        elif max_price > 0:
            padec_od_vrha = ((price - max_price) / max_price) * 100
            
            # Če detektiramo padec hujši od -20% (korekcija)
            if padec_od_vrha <= -20.0:
                if padec_od_vrha < najvecji_padec:
                    najvecji_padec = padec_od_vrha
                    najboljsi_vrh = {
                        "peak_date": max_date,
                        "peak_price": max_price,
                        "drop_date": date,
                        "drop_pct": padec_od_vrha
                    }
                    
                # Ko najdemo zlom, resetiramo max_price, da iščemo naslednje cikle
                # (Za ta preprost algoritem bomo vzeli najhujši padec v izbranem obdobju)
                max_price = price
                max_date = date
                
    return najboljsi_vrh

def analiziraj_trg():
    rezultati = []
    print(f"Začenjam prenos in analizo za {len(TICKERJI)} delnic (Obdobje 2015-2024)...")
    print("To lahko traja kakšno minuto. Prosim počakaj.\n")
    
    for i, ticker in enumerate(TICKERJI, 1):
        try:
            print(f"[{i}/{len(TICKERJI)}] Analiziram {ticker} ...", end=" ")
            # Vzamemo od 2013 naprej, da je v 2017 že izračunan 200-week MA
            delnica = yf.Ticker(ticker)
            data = delnica.history(start="2013-01-01", end="2024-01-01", interval="1wk", actions=False)
            
            if data.empty or len(data) < 210:
                print("Ni dovolj podatkov.")
                continue
                
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
                
            data['MA_10'] = data['Close'].rolling(window=10).mean()
            data['MA_50'] = data['Close'].rolling(window=50).mean()
            data['MA_200'] = data['Close'].rolling(window=200).mean()
            data['MA_100_avg'] = data['Close'].rolling(window=100).mean() # Zgodovinsko povprečje (ca. 2 leti) za P/E stretch
            data['RSI'] = izracunaj_rsi(data['Close'])
            
            # Omejimo iskanje vrha samo na obdobje po letu 2017 (ko so vsi drseči veljavni)
            analizno_obdobje = data.loc["2017-01-01":]
            
            vrh = poisi_zgodovinski_vrh_in_padec(analizno_obdobje)
            
            if vrh is None:
                print("Ni bilo detektiranega >20% padca.")
                continue
                
            peak_date = vrh['peak_date']
            
            # Varnostni check, če podatki točno na ta datum manjkajo (vikendi ipd.)
            if peak_date not in data.index:
                print("Napaka pri indeksu.")
                continue
                
            # Zajem vseh tehničnih parametrov na dan Vrhunca
            peak_close = float(data.loc[peak_date, 'Close'])
            peak_ma10 = float(data.loc[peak_date, 'MA_10'])
            peak_ma50 = float(data.loc[peak_date, 'MA_50'])
            peak_ma200 = float(data.loc[peak_date, 'MA_200'])
            peak_rsi = float(data.loc[peak_date, 'RSI'])
            peak_hist_avg = float(data.loc[peak_date, 'MA_100_avg'])
            
            if pd.isna(peak_ma200):
                print("Vrh je bil prehitro (ni še bilo 200-tednov).")
                continue
                
            # 1. Razmak 10w MA vs 200w MA
            dist_10_200 = ((peak_ma10 - peak_ma200) / peak_ma200) * 100
            
            # 2. Razmak 50w MA vs 200w MA
            dist_50_200 = ((peak_ma50 - peak_ma200) / peak_ma200) * 100
            
            # 3. Naklon 10 week MA (Koliko % je zrasla premica 10w MA v zadnjih 10 tednih pred vrhom)
            # Pridobimo indeks datuma vrha in vzamemo 10 tednov nazaj
            idx = data.index.get_loc(peak_date)
            if idx >= 10:
                past_ma10 = float(data.iloc[idx-10]['MA_10'])
                naklon_10w = ((peak_ma10 - past_ma10) / past_ma10) * 100
            else:
                naklon_10w = 0.0
                
            # 4. P/E Growth Proxy (Valuation Stretch) - Razlika med trenutno ceno in povprečno ceno zadnjih 2 let
            val_stretch = ((peak_close - peak_hist_avg) / peak_hist_avg) * 100
            
            rezultati.append({
                "Ticker": ticker,
                "Obdobje_vrha": peak_date.strftime("%b %Y"),
                "Padec": vrh['drop_pct'],
                "RSI": peak_rsi,
                "Dist_10_200": dist_10_200,
                "Dist_50_200": dist_50_200,
                "Naklon_10w": naklon_10w,
                "Valuation_Stretch": val_stretch
            })
            
            print("[OK]")
            time.sleep(0.05)
            
        except Exception as e:
            print(f"[NAPAKA: {e}]")
            
    generiraj_html(rezultati)

def generiraj_html(podatki):
    df = pd.DataFrame(podatki)
    if not df.empty:
        # Sortiramo od najmočnejših vrhov naprej
        df = df.sort_values(by="Dist_10_200", ascending=False)
        
    povprecje_rsi = df['RSI'].mean() if not df.empty else 0
    povprecje_dist10 = df['Dist_10_200'].mean() if not df.empty else 0
    povprecje_naklon = df['Naklon_10w'].mean() if not df.empty else 0
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>OGM SELL Analiza Zgodovine</title>
    <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f8fafc; color: #1e293b; padding: 30px; max-width: 1200px; margin: 0 auto; }}
    .header {{ background: linear-gradient(135deg, #7f1d1d 0%, #dc2626 100%); color: white; padding: 25px; border-radius: 8px; margin-bottom: 25px; }}
    .header h1 {{ margin: 0; font-size: 24pt; }}
    
    .summary-box {{ display: flex; gap: 20px; margin-bottom: 30px; }}
    .stat-card {{ background-color: white; padding: 20px; border-radius: 8px; border: 1px solid #e2e8f0; flex: 1; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
    .stat-card h3 {{ margin: 0; color: #64748b; font-size: 11pt; text-transform: uppercase; }}
    .stat-card p {{ margin: 10px 0 0 0; font-size: 22pt; font-weight: bold; color: #dc2626; }}
    
    table {{ width: 100%; border-collapse: collapse; background-color: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }}
    th {{ background-color: #1e293b; color: white; padding: 12px; text-align: left; font-size: 10pt; }}
    td {{ padding: 12px; border-bottom: 1px solid #e2e8f0; font-size: 9.5pt; }}
    tr:hover {{ background-color: #f1f5f9; }}
    
    .high-risk {{ font-weight: bold; color: #dc2626; }}
    .drop {{ color: #b91c1c; font-weight: 600; }}
    </style>
    </head>
    <body>

    <div class="header">
        <h1>Anatomija "Blow-Off" Vrhov (NASDAQ Top 50)</h1>
        <p>Kakšni so bili indikatorji na dan vrhunca, preden je delnica padla za >20 %?</p>
    </div>
    
    <div class="summary-box">
        <div class="stat-card">
            <h3>Povprečen RSI ob vrhu</h3>
            <p>{povprecje_rsi:.1f}</p>
        </div>
        <div class="stat-card">
            <h3>Povprečen razmak (10w MA vs 200w MA)</h3>
            <p>+{povprecje_dist10:.1f} %</p>
        </div>
        <div class="stat-card">
            <h3>Povprečen Naklon rasti (Zadnjih 10 tednov)</h3>
            <p>+{povprecje_naklon:.1f} %</p>
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th>Ticker</th>
                <th>Obdobje Vrha</th>
                <th>Sledil je padec</th>
                <th>RSI na vrhu</th>
                <th>Razmak (10w MA vs 200w)</th>
                <th>Razmak (50w MA vs 200w)</th>
                <th>Strmina rasti (Naklon 10w MA)</th>
                <th>Valuation Stretch (Proxy P/E)</th>
            </tr>
        </thead>
        <tbody>
    """
    
    if not df.empty:
        for _, row in df.iterrows():
            rsi_class = "high-risk" if row['RSI'] > 75 else ""
            dist_class = "high-risk" if row['Dist_10_200'] > 100 else ""
            
            html += f"""
            <tr>
                <td style="font-weight: bold; color: #0f172a;">{row['Ticker']}</td>
                <td>{row['Obdobje_vrha']}</td>
                <td class="drop">{row['Padec']:.1f} %</td>
                <td class="{rsi_class}">{row['RSI']:.1f}</td>
                <td class="{dist_class}">+{row['Dist_10_200']:.1f} %</td>
                <td>+{row['Dist_50_200']:.1f} %</td>
                <td>+{row['Naklon_10w']:.1f} % rast/10tednov</td>
                <td>+{row['Valuation_Stretch']:.1f} % od povprečja</td>
            </tr>
            """
            
    html += """
        </tbody>
    </table>
    </body>
    </html>
    """
    
    ime_datoteke = "OGM_SELL_ANALIZA.html"
    with open(ime_datoteke, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[USPEH] Poročilo generirano: {ime_datoteke}")
    webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

if __name__ == "__main__":
    analiziraj_trg()