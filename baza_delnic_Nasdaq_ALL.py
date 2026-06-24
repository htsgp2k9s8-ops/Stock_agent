import yfinance as yf
import pandas as pd
import urllib.request
import json
import time
import os

print("=========================================================")
print("KORAK 1: AVTOMATSKI PRENOS IN FILTRIRANJE - CELOTEN NASDAQ")
print("=========================================================")

# ==============================================================================
# A. PRENOS SUROVEGA SEZNAMA VSEH DELNIC IZ NASDAQ STREŽNIKA
# ==============================================================================
print("[1/3] Povezujem se z uradnim NASDAQ API strežnikom...")
vsi_surovi_tickerji = []

try:
    url_nasdaq = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=7000&download=true"
    req = urllib.request.Request(url_nasdaq, headers={'User-Agent': 'Mozilla/5.0'})
    
    with urllib.request.urlopen(req) as response:
        podatki = json.loads(response.read().decode())
        
    rows = podatki['data']['rows']
    # Izločimo sklade in opcije s simbolom ^
    vsi_surovi_tickerji = [row['symbol'].strip() for row in rows if "^" not in row['symbol']]
    print(f"      -> Našli smo celoten nabor: {len(vsi_surovi_tickerji)} surovih tikerjev.")
    
except Exception as e:
    print(f"      [NAPAKA] Ni mogoče dostopati do NASDAQ API: {e}")
    os._exit(0)

# ==============================================================================
# B. FILTRIRANJE: MASOVNI PREGLED CELOTNE BORZE
# ==============================================================================
print("\n[2/3] Začenjam masovno filtriranje celotne borze...")
print("      (Opozorilo: Proces bo trajal dlje časa. Lahko si skhaš kavo.)")
print("---------------------------------------------------------")

prečiščeni_tickerji = []
regije = []

# CELOTEN TRG: Sedaj vzamemo čisto vse tikerje od A do Ž!
celoten_nabor = vsi_surovi_tickerji 
skupno_za_preveriti = len(celoten_nabor)

for krog, ticker in enumerate(celoten_nabor, 1):
    # Vsakih 50 delnic izpišemo vmesno stanje v terminal
    if krog % 50 == 0:
        print(f"      ... obdelano {krog} / {skupno_za_preveriti} delnic ... (V bazi trenutno: {len(prečiščeni_tickerji)})")
        
    try:
        # Varovalka za poševnice v tikerjih
        yf_ticker = ticker.replace('/', '-')
        
        delnica = yf.Ticker(yf_ticker)
        data = delnica.history(start="2021-01-01", interval="1wk", actions=False)
        
        # Filter 1: Razpoložljivost podatkov za MA200
        if data is None or data.empty or len(data) < 205:
            continue
            
        close_prices = data['Close'].dropna()
        if close_prices.empty or len(close_prices) < 205:
            continue
            
        # Filter 2: Odstranjevanje Penny stocks (cena pod $2)
        zadnja_cena = float(close_prices.iloc[-1])
        if zadnja_cena < 2.00:
            continue
            
        # Shranimo očiščen tiker
        prečiščeni_tickerji.append(yf_ticker)
        regije.append("NASDAQ (ZDA)")
        
        # Časovna pavza (0.04 sekunde), da ne preobremenimo strežnikov
        time.sleep(0.04)
        
    except Exception:
        continue

# ==============================================================================
# C. SHRANJEVANJE V KONČNO CSV DATOTEKO
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
    print(f"[USPEH] TVOJA POPOLNA NASDAQ CSV BAZA JE ZGRAJENA!")
    print(f"        Lokacija datoteke: '{os.path.abspath(ime_izvoza)}'")
    print(f"        Skupaj uspešno shranjenih: {len(df_baza)} zdravih operativnih delnic (od A do Ž).")
    print("=========================================================")
    print("Ko se ta dolg proces zaključi, mi sporoči število delnic, da narediva KORAK 2!")
except PermissionError:
    print(f"\n[KRITIČNA NAPAKA] Nujno zapri datoteko '{ime_izvoza}' v Excelu in ponovno zaženi program!")