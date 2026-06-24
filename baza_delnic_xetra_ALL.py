import pandas as pd
import yfinance as yf
import time
import os

print("=========================================================")
print("KORAK 1: TABULARNI PARSER URADNIH SEGMENTOV (XETRA)")
print("=========================================================")

datoteke_segmentov = [
    "Listed-companies.xlsx - Prime Standard.csv",
    "Listed-companies.xlsx - General Standard.csv",
    "Listed-companies.xlsx - Scale.csv",
    "Listed-companies.xlsx - Basic Board.csv"
]

vsi_surovi_tickerji = []

print("[1/3] Berem stolpce iz uradnih izvozov...")

for datoteka in datoteke_segmentov:
    if not os.path.exists(datoteka):
        print(f"      [Opozorilo] Datoteka '{datoteka}' manjka v mapi, jo preskakujem.")
        continue
        
    try:
        # Ker je datoteka ločena s tabulatorji ali vejicami, pustimo 'sep=None', 
        # da Pandas samodejno ugotovi pravi format ločila!
        # ignoriramo slabe vrstice na vrhu in dnu z on_bad_lines
        df_raw = pd.read_csv(datoteka, sep=None, header=None, on_bad_lines='skip', engine='python').astype(str)
        
        # Poiščemo vrstico, ki vsebuje tekst 'Trading Symbol'
        vrstica_glave = None
        for i, row in df_raw.iterrows():
            if any('Trading Symbol' in str(cell) for cell in row):
                vrstica_glave = i
                break
                
        if vrstica_glave is not None:
            # Ponovno naložimo datoteko od te vrstice naprej
            df_prava = pd.read_csv(datoteka, sep=None, skiprows=vrstica_glave, on_bad_lines='skip', engine='python')
            df_prava.columns = df_prava.columns.str.strip()
            
            if 'Trading Symbol' in df_prava.columns:
                simboli = df_prava['Trading Symbol'].dropna().astype(str).str.strip().tolist()
                
                števec_datoteke = 0
                for s in simboli:
                    # Očistimo morebitne čudne znake in presledke
                    s_clean = s.split()[0].upper() if s.split() else ""
                    
                    if s_clean and len(s_clean) <= 5 and s_clean != 'NAN' and not s_clean.startswith('NUMBER'):
                        if not s_clean.isdigit():
                            vsi_surovi_tickerji.append(s_clean + ".DE")
                            števec_datoteke += 1
                            
                print(f"      -> {datoteka}: Uspešno prebrana (Najdenih {števec_datoteke} delnic).")
        else:
            print(f"      [Opozorilo] V datoteki {datoteka} ni bil najden stolpec 'Trading Symbol'.")
            
    except Exception as e:
        print(f"      [Opozorilo] Težava pri branju datoteke {datoteka}: {e}")
        continue

# Odstranimo duplikate in razvrstimo
vsi_surovi_tickerji = sorted(list(set(vsi_surovi_tickerji)))
print(f"\n      Skupaj zbranih {len(vsi_surovi_tickerji)} unikatnih XETRA tikerjev.")

if not vsi_surovi_tickerji:
    print("[PREKINITEV] Seznam tikerjev je prazen. Preveri mapo!")
    os._exit(0)

# ==============================================================================
# B. FILTRIRANJE: PREVERJANJE NA YAHOO FINANCE (IDENTIČNO KOT NASDAQ)
# ==============================================================================
print("\n[2/3] Začenjam masovno filtriranje celotne nemške borze...")
print("      (Preverjam ceno nad 2.00 € in polno zgodovino za MA200...)")
print("---------------------------------------------------------")

prečiščeni_tickerji = []
regije = []

# Za test vzamemo prvih 300 delnic, da potrdiva, da vse teče hitro
# Ko želiš procesirati VSE od A do Ž, spremeni spodnjo vrstico v: celoten_nabor = vsi_surovi_tickerji
omejitev_za_test = 300
celoten_nabor = vsi_surovi_tickerji[:omejitev_za_test]
skupno_za_preveriti = len(celoten_nabor)

for krog, ticker in enumerate(celoten_nabor, 1):
    if krog % 50 == 0:
        print(f"      ... obdelano {krog} / {skupno_za_preveriti} delnic ... (V bazi trenutno: {len(prečiščeni_tickerji)})")
        
    try:
        delnica = yf.Ticker(ticker)
        data = delnica.history(start="2021-01-01", interval="1wk", actions=False)
        
        if data is None or data.empty or len(data) < 205:
            continue
            
        close_prices = data['Close'].dropna()
        if close_prices.empty or len(close_prices) < 205:
            continue
            
        # Filter za Penny stocks (nad 2.00 €)
        zadnja_cena = float(close_prices.iloc[-1])
        if zadnja_cena < 2.00:
            continue
            
        prečiščeni_tickerji.append(ticker)
        regije.append("XETRA (Nemčija)")
        
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
ime_izvoza = "xetra_delnice.csv"

try:
    df_baza.to_csv(ime_izvoza, index=False)
    print("=========================================================")
    print(f"[USPEH] TVOJA POPOLNA XETRA CSV BAZA JE ZGRAJENA!")
    print(f"        Lokacija datoteke: '{os.path.abspath(ime_izvoza)}'")
    print(f"        Skupaj uspešno shranjenih: {len(df_baza)} operativnih nemških delnic.")
    print("=========================================================")
except PermissionError:
    print(f"\n[KRITIČNA NAPAKA] Nujno zapri datoteko '{ime_izvoza}' v Excelu!")