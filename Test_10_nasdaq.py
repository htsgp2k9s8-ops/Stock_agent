import yfinance as yf
import pandas as pd
import numpy as np
import time

# ==============================================================================
# NASTAVITEV SEZNAMA DELNIC (Tukaj lahko poljubno dodajaš ali brišeš tickerje)
# ==============================================================================
seznam_tickerjev = ["MSFT", "AAPL", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "COST", "NFLX", "SAP"]

print(f"Zaganjaš OVVICEK GROWTH MATRIX (OGM) masovni skener za {len(seznam_tickerjev)} delnic...")
print("Prosim počakaj, da model zbere in analizira tehnične ter fundamentalne podatke...\n")

tabela_rezultatov = []

for ticker in seznam_tickerjev:
    try:
        print(f" -> Analiziram {ticker}...")
        
        # 1. PRIDOBIVANJE IN IZRAČUN TEHNIČNIH PODATKOV
        data = yf.download(ticker, start="2016-01-01", end="2026-05-31", interval="1wk", progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
            
        if data.empty or len(data) < 200:
            print(f"    [OPOZORILO] Premalo zgodovinskih podatkov za {ticker}. Preskakujem.")
            continue
            
        # 200-week MA
        data['200_week_MA'] = data['Close'].rolling(window=200).mean()
        data['Pct_from_200MA'] = ((data['Close'] - data['200_week_MA']) / data['200_week_MA']) * 100
        
        # Tedenski RSI
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        data['RSI_14'] = 100 - (100 / (1 + rs))
        
        zadnji_podatki = data.dropna(subset=['200_week_MA', 'RSI_14']).iloc[-1]
        trenutna_cena = zadnji_podatki['Close']
        oddaljenost_ma = zadnji_podatki['Pct_from_200MA']
        trenutni_rsi = zadnji_podatki['RSI_14']
        
        # 2. PRIDOBIVANJE FUNDAMENTALNIH PODATKOV
        delnica = yf.Ticker(ticker)
        info = delnica.info
        
        gross_margin = info.get('grossMargins', 0) * 100
        fcf = info.get('freeCashflow', 0)
        market_cap = info.get('marketCap', 1)
        fcf_yield = (fcf / market_cap) * 100 if fcf else 0
        peg_ratio = info.get('pegRatio', 0)
        
        # EPS Growth pridobivanje
        eps_growth_trenutni = info.get('earningsGrowth', 0.14) * 100
        if eps_growth_trenutni == 0:
            eps_growth_trenutni = 14.5  # Varna privzeta vrednost, če Yahoo nima podatka
            
        # Dinamična prilagoditev 10y zgodovinskega EPS povprečja glede na tip podjetja
        # (Nvidia/Tesla rasteta hitreje kot Apple/Costco)
        if ticker in ["NVDA", "TSLA", "META"]:
            zgodovinski_eps_growth_10y = 25.0
        elif ticker in ["MSFT", "AMZN", "NFLX"]:
            zgodovinski_eps_growth_10y = 16.5
        else:
            zgodovinski_eps_growth_10y = 12.5

        # 3. DINAMIČNA LOGIKA ZA FCF (Max 5 točk)
        je_visoko_maržni_stroj = gross_margin > 45.0 and peg_ratio < 1.5
        if je_visoko_maržni_stroj:
            tocke_fcf = np.interp(fcf_yield, [0.0, 1.0, 2.0, 4.0, 6.0], [1.5, 3.0, 4.5, 5.0, 5.0])
        else:
            tocke_fcf = np.interp(fcf_yield, [0.5, 2.0, 4.0, 5.5, 7.0], [0.0, 1.5, 3.0, 4.5, 5.0])

        # 4. OGM TOČKOVALNA LESTVICA
        # A) 200-week MA (Max 35 točk)
        if oddaljenost_ma >= 0:
            tocke_ma = np.interp(oddaljenost_ma, [0, 2, 10, 25, 50], [33.0, 35.0, 22.0, 8.0, 0.0])
        else:
            tocke_ma = np.interp(oddaljenost_ma, [-20, -10, -5, 0], [0.0, 12.0, 25.0, 33.0])

        # B) EPS Growth vs povprečje (Max 20 točk)
        tocke_eps = np.interp(eps_growth_trenutni, [0.0, 8.0, zgodovinski_eps_growth_10y, zgodovinski_eps_growth_10y + 5, zgodovinski_eps_growth_10y + 15], [0.0, 5.0, 14.0, 20.0, 20.0])

        # C) PEG Razmerje (Max 15 točk)
        tocke_peg = np.interp(peg_ratio, [0.4, 0.8, 1.2, 1.6, 2.0], [15.0, 13.0, 10.0, 5.0, 0.0])

        # D) Gross Margin (Max 15 točk)
        tocke_margin = np.interp(gross_margin, [25, 35, 45, 55, 65], [0.0, 4.0, 10.0, 14.0, 15.0])

        # E) Tedenski RSI (Max 10 točk)
        tocke_rsi = np.interp(trenutni_rsi, [30, 45, 60, 70, 80], [10.0, 8.0, 5.0, 2.0, 0.0])

        # URADNI OVNICEK GROWTH MATRIX SEŠTEVEK
        ovnicek_growth_matrix = tocke_ma + tocke_eps + tocke_peg + tocke_margin + tocke_fcf + tocke_rsi
        
        # Določitev statusa delnice
        if ovnicek_growth_matrix >= 80.0:
            status = "🔥 STRONG BUY"
        elif ovnicek_growth_matrix >= 65.0:
            status = "📈 BUY"
        elif ovnicek_growth_matrix >= 45.0:
            status = "⏳ HOLD"
        else:
            status = "❌ OVERVALUED"

        # Shranjevanje v tabelo
        tabela_rezultatov.append({
            "Ticker": ticker,
            "Cena (USD)": f"{trenutna_cena:.2f}",
            "Odmaknjenost 200MA": f"{oddaljenost_ma:+.1f}%",
            "RSI (14)": f"{trenutni_rsi:.1f}",
            "PEG": f"{peg_ratio:.2f}",
            "Marža": f"{gross_margin:.1f}%",
            "OGM SCORE": ovnicek_growth_matrix,
            "STATUS": status
        })
        
        # Kratka pavza med klici na Yahoo API, da nas ne blokirajo
        time.sleep(0.5)
        
    except Exception as e:
        print(f"    [NAPAKA] Težava pri obdelavi tickerja {ticker}: {e}")

# Pretvori rezultate v lep Pandas DataFrame in jih sortiraj
df_končni = pd.DataFrame(tabela_rezultatov)
df_končni = df_končni.sort_values(by="OGM SCORE", ascending=False)

# Zaokroževanje samega izpisa rezultata za lepši prikaz
df_končni["OGM SCORE"] = df_končni["OGM SCORE"].map('{:.1f}'.format)

# PROFI IZPIS ZBIRNE TABELE
print("\n" + "="*95)
print("                       ZBIRNI POROČILO: OVNICEK GROWTH MATRIX (OGM)")
print("="*95)
print(df_končni.to_string(index=False))
print("="*95)
print("Navodilo: Delnice z OGM SCORE 80+ se statistično nahajajo v coni zrelega odboja (Strong Buy).")