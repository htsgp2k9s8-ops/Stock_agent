import yfinance as yf
import pandas as pd
import numpy as np

# ticker = "MSFT" # Tukaj zamenjaš za katero koli delnico
ticker = "DIS" 
print(f"Zaganjaš uradni OVNICEK GROWTH MATRIX (OGM) za ticker: {ticker}...\n")

# ==========================================
# 1. PRIDOBIVANJE IN IZRAČUN PODATKOV (Tehnika)
# ==========================================
data = yf.download(ticker, start="2016-01-01", end="2026-05-31", interval="1wk", progress=False)
if isinstance(data.columns, pd.MultiIndex):
    data.columns = data.columns.get_level_values(0)

# 200-week MA
data['200_week_MA'] = data['Close'].rolling(window=200).mean()
data['Pct_from_200MA'] = ((data['Close'] - data['200_week_MA']) / data['200_week_MA']) * 100

# Tedenski RSI (14)
delta = data['Close'].diff()
gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
rs = gain / loss
data['RSI_14'] = 100 - (100 / (1 + rs))

zadnji_podatki = data.dropna(subset=['200_week_MA', 'RSI_14']).iloc[-1]
trenutna_cena = zadnji_podatki['Close']
oddaljenost_ma = zadnji_podatki['Pct_from_200MA']
trenutni_rsi = zadnji_podatki['RSI_14']

# ==========================================
# 2. PRIDOBIVANJE PODATKOV (Fundamenti)
# ==========================================
delnica = yf.Ticker(ticker)
info = delnica.info

gross_margin = info.get('grossMargins', 0) * 100
fcf = info.get('freeCashflow', 0)
market_cap = info.get('marketCap', 1)
fcf_yield = (fcf / market_cap) * 100 if fcf else 0
peg_ratio = info.get('pegRatio', 0)
trenutni_pe = info.get('trailingPE', 0)

# Prilagoditev za MSFT
zgodovinski_pe_povprecje = 29.5
pe_odstopanje = ((trenutni_pe - zgodovinski_pe_povprecje) / zgodovinski_pe_povprecje) * 100

# EPS Growth
eps_growth_trenutni = info.get('earningsGrowth', 0.14) * 100
if eps_growth_trenutni == 0: eps_growth_trenutni = 14.5
zgodovinski_eps_growth_10y = 16.5

# ==========================================
# 3. DINAMIČNA LOGIKA ZA FCF (Max 5 točk)
# ==========================================
je_visoko_maržni_stroj = gross_margin > 45.0 and peg_ratio < 1.5

if je_visoko_maržni_stroj:
    tip_fcf_lestvice = "Oblažena (Marža > 45% / Reinvestiranje)"
    tocke_fcf = np.interp(fcf_yield, [0.0, 1.0, 2.0, 4.0, 6.0], [1.5, 3.0, 4.5, 5.0, 5.0])
else:
    tip_fcf_lestvice = "Standardna (Stroga)"
    tocke_fcf = np.interp(fcf_yield, [0.5, 2.0, 4.0, 5.5, 7.0], [0.0, 1.5, 3.0, 4.5, 5.0])

# ==========================================
# 4. OGM TOČKOVALNA LESTVICA (Z dodanima varnostnima filtromoma)
# ==========================================

# 1. 200-week MA
if oddaljenost_ma >= 0:
    tocke_ma = np.interp(oddaljenost_ma, [0, 2, 10, 25, 50], [33.0, 35.0, 22.0, 8.0, 0.0])
else:
    tocke_ma = np.interp(oddaljenost_ma, [-20, -10, -5, 0], [0.0, 12.0, 25.0, 33.0])

# 2. EPS Growth
tocke_eps = np.interp(eps_growth_trenutni, [0.0, 8.0, 16.5, 22.0, 30.0], [0.0, 5.0, 14.0, 20.0, 20.0])

# 3. PEG
tocke_peg = np.interp(peg_ratio, [0.4, 0.8, 1.2, 1.6, 2.0], [15.0, 13.0, 10.0, 5.0, 0.0])

# 4. Gross Margin
tocke_margin = np.interp(gross_margin, [25, 35, 45, 55, 65], [0.0, 4.0, 10.0, 14.0, 15.0])

# 5. RSI
tocke_rsi = np.interp(trenutni_rsi, [30, 45, 60, 70, 80], [10.0, 8.0, 5.0, 2.0, 0.0])

# SEŠTEVEK Z OMEJITVIJO NA 100
ovnicek_growth_matrix = min(100.0, tocke_ma + tocke_eps + tocke_peg + tocke_margin + tocke_fcf + tocke_rsi)

# ==========================================
# 5. INSTITUCIONALNI REZULTAT
# ==========================================
# FILTER ZA 200-MA (Prikaz statusa)
trend_ok = oddaljenost_ma >= 0
status = "STRONG BUY" if (ovnicek_growth_matrix >= 80.0 and trend_ok) else ("WARNING: POD 200-MA" if not trend_ok else "OPAZOVANJE (PREMALO OGM)")

print("="*65)
print(f"   OFFICIAL REPORT: OVNICEK GROWTH MATRIX (OGM)")
print("="*65)
print(f"Podjetje:                  {ticker}")
print(f"Trenutna cena:             {trenutna_cena:.2f} USD")
print(f"Status trenda (200-MA):    {'OK' if trend_ok else 'POZOR: POD 200-MA'}")
print("-"*65)
print(f"1. MA LOKACIJA (200-week): {oddaljenost_ma:.2f} %    -> OGM: {tocke_ma:.1f} / 35")
print(f"2. EPS MOTOR (Rast):       {eps_growth_trenutni:.1f} %    -> OGM: {tocke_eps:.1f} / 20")
print(f"3. PEG VALUACIJA:          {peg_ratio:.2f}           -> OGM: {tocke_peg:.1f} / 15")
print(f"4. BRUTO MARŽA:            {gross_margin:.2f} %      -> OGM: {tocke_margin:.1f} / 15")
print(f"5. TEDENSKI RSI (14):      {trenutni_rsi:.2f}        -> OGM: {tocke_rsi:.1f} / 10")
print(f"6. FCF GOTOVINSKI YIELD:   {fcf_yield:.2f} %         -> OGM: {tocke_fcf:.1f} / 5")
print("-"*65)
print(f"--> URADNA OCENA OGM:      {ovnicek_growth_matrix:.1f} / 100")
print(f"--> STATUS VSTOPA:         {status}")
print("="*65)