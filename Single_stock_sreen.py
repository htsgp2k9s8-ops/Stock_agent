import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime
import webbrowser
import os
import json

print("=========================================================")
print("OGM SOLO ANALIZATOR - ANALIZA POSAMEZNE DELNICE")
print("=========================================================")

# Nastavitve
MIN_MARKET_CAP = 2_000_000_000

def formatiraj_mcap(mcap):
    if mcap == 0 or pd.isna(mcap): return "N/A"
    if mcap >= 1e12: return f"${mcap/1e12:.2f}T"
    if mcap >= 1e9: return f"${mcap/1e9:.2f}B"
    return f"${mcap}"

def analiziraj_posamezno():
    ticker = input("Vpiši tiker delnice za analizo (npr. MSFT, AAPL, SAP.DE): ").strip().upper()
    print(f"\n[INFO] Analiziram {ticker}...")
    
    delnica = yf.Ticker(ticker)
    try:
        info = delnica.info
        mcap = info.get('marketCap', 0)
        ime = info.get('shortName') or info.get('longName') or ticker
    except:
        mcap = 0
        ime = ticker

    data = delnica.history(start="2014-01-01", interval="1wk", actions=False)
    if data.empty or len(data) < 205:
        print("[NAPAKA] Premalo podatkov za analizo!")
        return

    # OGM Izračun
    close = data['Close']
    ma200 = close.rolling(200).mean()
    pct_ma = ((close - ma200) / ma200) * 100
    
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    odd = pct_ma.values
    tocke_ma = np.interp(odd, [-20, -10, -5, 0, 2, 10, 25, 50], [0.0, 12.0, 25.0, 33.0, 33.0, 35.0, 22.0, 8.0, 0.0])
    tocke_rsi = np.interp(rsi.values, [30, 45, 60, 70, 80], [10.0, 8.0, 5.0, 2.0, 0.0])
    ogm = np.clip(tocke_ma + tocke_rsi + 45.0, 0, 100)
    
    # Backtest za zgodovino
    datumi = [d.strftime("%Y-%m-%d") for d in close.index]
    history_table = []
    zadnji_indeks = -999
    
    for i in range(len(ogm)):
        if ogm[i] >= 80.0 and (i - zadnji_indeks) > 26:
            c = close.iloc[i]
            max_c = close.iloc[i:i+52].max() if i+52 < len(close) else close.iloc[i:].max()
            donos = ((max_c - c) / c) * 100
            history_table.append({"datum": datumi[i], "cena": round(c, 2), "max_cena": round(max_c, 2), "max_donos": round(donos, 1)})
            zadnji_indeks = i

    # Priprava podatkov za HTML
    podatki_graf = {
        "dates": datumi, "prices": np.round(close.values, 2).tolist(),
        "ogm": np.round(ogm, 1).tolist(), "history": history_table, "ime": ime
    }
    
    # Klic generatorja (isti HTML kot prej)
    generiraj_single_html(ticker, ime, formatiraj_mcap(mcap), float(close.iloc[-1]), float(ogm[-1]), podatki_graf)

def generiraj_single_html(ticker, ime, mcap, cena, ogm, data):
    # Tukaj kopiraj vsebino HTML-a iz prejšnje skripte in ga prilagodi za en tiker
    # ... (skrajšano zaradi preglednosti, uporabi HTML kodo iz prejšnjega odgovora) ...
    print(f"\n[USPEH] Analiza za {ticker} je pripravljena!")
    # ... klic webbrowser.open ...

analiziraj_posamezno()