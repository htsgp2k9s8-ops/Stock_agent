import yfinance as yf
import pandas as pd
import numpy as np

ticker = "MSFT"
print(f"Začenjam zgodovinski BACKTEST faktorja za {ticker} (2016-2026)...\n")

# 1. Prenos celotne zgodovine tedenskih podatkov
data = yf.download(ticker, start="2016-01-01", end="2026-05-31", interval="1wk", progress=False)
if isinstance(data.columns, pd.MultiIndex):
    data.columns = data.columns.get_level_values(0)

# 2. Izračun tehničnih indikatorjev skozi čas
data['200_week_MA'] = data['Close'].rolling(window=200).mean()
data['Pct_from_200MA'] = ((data['Close'] - data['200_week_MA']) / data['200_week_MA']) * 100

delta = data['Close'].diff()
gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
rs = gain / loss
data['RSI_14'] = 100 - (100 / (1 + rs))

# Odstranimo vrstice brez 200-MA podatkov
data_clean = data.dropna(subset=['200_week_MA', 'RSI_14']).copy()

# 3. Simulacija zgodovinskega VTS točkovanja teden za tednom
# Ker simuliramo stabilen MSFT "stroj", vzamemo njegove tipične fundamentalne točke:
# Odlična marža (15t), oblažen FCF zaradi reinvestiranja (12t), soliden PEG (10t).
# P/E odstopanje pa bomo dinamično vezali na oddaljenost od 200-MA (ko cena pade na MA, je P/E pod povprečjem).

vts_zgodovina = []

for index, row in data_clean.iterrows():
    oddaljenost_ma = row['Pct_from_200MA']
    trenutni_rsi = row['RSI_14']
    
    # A) Tehnika: 200-week MA
    if oddaljenost_ma >= 0:
        tocke_ma = np.interp(oddaljenost_ma, [0, 2, 10, 25, 50], [28, 30, 20, 10, 0])
    else:
        tocke_ma = np.interp(oddaljenost_ma, [-20, -10, -5, 0], [0, 10, 20, 28])
        
    # B) Tehnika: Tedenski RSI
    tocke_rsi = np.interp(trenutni_rsi, [30, 45, 60, 70, 80], [15, 12, 8, 3, 0])
    
    # C) Fundamenti (Simulirano stabilno stanje za MSFT):
    tocke_margin = 15.0  # MSFT ima vedno maržo daleč nad 45%
    tocke_fcf = 12.0     # Oblažena lestvica za visoko-maržne rastoče stroje
    tocke_peg = 10.0     # Povprečni zdrav zgodovinski PEG
    
    # P/E odstopanje: Ko delnica pade blizu 200-MA, postane podcenjena glede na lastno povprečje
    if oddaljenost_ma < 5:
        tocke_pe = 9.0   # Pod povprečjem (Ugodno)
    elif oddaljenost_ma < 15:
        tocke_pe = 6.0   # Okoli povprečja
    else:
        tocke_pe = 2.0   # Nad povprečjem (Drago)
        
    # SKUPNI FAKTOR ZA TA TEDEN
    vts_score = tocke_ma + tocke_rsi + tocke_peg + tocke_margin + tocke_fcf + tocke_pe
    vts_zgodovina.append(vts_score)

data_clean['VTS_Score'] = vts_zgodovina

# 4. Analiza rezultatov: Poiščemo tedne, ko je bil VTS Score >= 80
signali_80 = data_clean[data_clean['VTS_Score'] >= 80.0].copy()

print(f"Skupno število analiziranih tednov: {len(data_clean)}")
print(f"Število tednov, ko je faktor dosegel STROGI BUY (80+): {len(signali_80)}")
print("-" * 75)
print(f"{'Datum Signala':<15} | {'VTS Score':<10} | {'Cena takrat':<12} | {'Max donos v 12 mesecih'}")
print("-" * 75)

# Grupiramo zaporedne tedne, da dobimo čiste vstopne točke (baze)
zgodovina_izpisa = []
for index, row in signali_80.iterrows():
    trenutni_indeks = data.index.get_loc(index)
    
    # Preverimo prihodnji donos (max cena v naslednjih 52 tednih)
    if trenutni_indeks + 52 < len(data):
        prihodnji_podatki = data.iloc[trenutni_indeks : trenutni_indeks + 52]
        max_cena_12m = prihodnji_podatki['High'].max()
        max_donos_12m = ((max_cena_12m - row['Close']) / row['Close']) * 100
        
        # Filtriramo izpis, da ne izpiše vsakega zaporednega tedna, ampak samo začetek baze
        if not zgodovina_izpisa or (index - zgodovina_izpisa[-1]).days > 30:
            zgodovina_izpisa.append(index)
            print(f"{str(index.date()):<15} | {row['VTS_Score']:<10.1f} | {row['Close']:<12.2f} | {max_donos_12m:.1f} %")

print("=" * 75)