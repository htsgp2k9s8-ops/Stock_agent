import yfinance as yf
import pandas as pd
import urllib.request
import json
import time
import os

print("=========================================================")
print("KORAK 1: AVTOMATSKI PRENOS IN FILTRIRANJE NASDAQ TRGA")
print("=========================================================")

# ==============================================================================
# A. PRENOS SUROVEGA SEZNAMA VSEH DELNIC IZ NASDAQ STREŽNIKA
# ==============================================================================
print("[1/3] Povezujem se z uradnim NASDAQ API strežnikom...")
vsi_surovi_tickerji = []

try:
    url_nasdaq = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=6000&download=true"
    req = urllib.request.Request(url_nasdaq, headers={'User-Agent': 'Mozilla/5.0'})
    
    with urllib.request.urlopen(req) as response:
        podatki = json.loads(response.read().decode())
        
    rows = podatki['data']['rows']
    vsi_surovi_tickerji = [row['symbol'].strip() for row in rows if "^" not in row['symbol']]
    print(f"      -> Najdenih {len(vsi_surovi_tickerji)} surovih tikerjev na borzi.")
    
except Exception as e:
    print(f"      [NAPAKA] Ni mogoče dostopati do NASDAQ API: {e}")
    os._exit(0)

# ==============================================================================
# B. FILTRIRANJE: ODSTRANJEVANJE PENNY STOCKS IN DELNIC BREZ ZGODOVINE
# ==============================================================================
print("\n[2/3] Začenjam filtriranje. Preverjam ceno in zgodovino (MA200)...")
print("---------------------------------------------------------")

prečiščeni_tickerji = []
regije = []

# Nastavljeno na prvih 300 za test (Ko želiš VSE, spremeni na len(vsi_surovi_tickerji))
omejitev_za_test = 300 
testni_nabor = vsi_surovi_tickerji[:omejitev_za_test]

for krog, ticker in enumerate(testni_nabor, 1):
    if krog % 25 == 0:
        print(f"      ... preverjeno {krog} / {len(testni_nabor)} delnic ...")
        
    try:
        # POPRAVEK: Yahoo Finance ne mara poševnic (npr. AKO/A spremenimo v AKO-A)
        yf_ticker = ticker.replace('/', '-')
        
        delnica = yf.Ticker(yf_ticker)
        data = delnica.history(start="2021-01-01", interval="1wk", actions=False)
        
        if data is None or data.empty or len(data) < 205:
            continue
            
        close_prices = data['Close'].dropna()
        if close_prices.empty or len(close_prices) < 205:
            continue
            
        # Filter za Penny stocks (nad $2)
        zadnja_cena = float(close_prices.iloc[-1])
        if zadnja_cena < 2.00:
            continue
            
        # Če je vse OK, shranimo ORIGINALEN tiker (ali popravljenega za kasnejše lažje branje)
        prečiščeni_tickerji.append(yf_ticker)
        regije.append("NASDAQ (ZDA)")
        
        time.sleep(0.05)
        
    except Exception:
        continue

# ==============================================================================
# C. GRADITEV NOVE PREČIŠČENE CSV DATOTEKE
# ==============================================================================
print("\n[3/3] Shranjujem prečiščene podatke...")

df_baza = pd.DataFrame({
    "Ticker": prečiščeni_tickerji,
    "Trg": regije
})

df_baza = df_baza.drop_duplicates(subset=["Ticker"])

ime_izvoza = "moje_globalne_delnice.csv"

try:
    df_baza.to_csv(ime_izvoza, index=False)
    print("=========================================================")
    print(f"[USPEH] Tvoja čista NASDAQ CSV baza je zgrajena!")
    print(f"        V bazo je shranjenih: {len(df_baza)} operativnih delnic.")
    print("=========================================================")
    print("Ko si pripravljen, mi sporoči, da preideva na KORAK 2 (OGM izračun)!")
except PermissionError:
    print(f"\n[KRITIČNA NAPAKA] Prosim zapri datoteko '{ime_izvoza}' v Excelu in ponovno zaženi program!")