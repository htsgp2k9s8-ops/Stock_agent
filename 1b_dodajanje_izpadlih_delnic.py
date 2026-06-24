import yfinance as yf
import pandas as pd
import time
import os

print("=========================================================")
print("KORAK 1b: DOPOLNJEVANJE IN NAKNADNO REŠEVANJE NASDAQ BAZE")
print("=========================================================")

CSV_DATOTEKA = "moje_globalne_delnice.csv"

# Seznam delnic, ki so dokazano izpadle zaradi omrežne napake (iz tvojega loga)
izpadle_delnice = [
    "GOOGL", "GOOG", "HD", "GEHC", "GILD", "GEN", "GEO", "GME", "GOLD", "GTLB", "GRMN",
    "GENC", "GENI", "GERN", "GEVO", "GFS", "GLNG", "GLOB", "GLW", "GNRC", "GOGO", "GOOS", 
    "GPCR", "GPRO", "GRAB", "GRBK", "GRND", "GRPN", "GRWG", "GSBC", "GSBD", "GSHD", "GSK", 
    "GSM", "GT", "GTE", "GTLB", "GXO", "GYRE", "HAE", "HAFC", "HAL", "HALO", "HAS", "HASI", 
    "HBAN", "HCA", "HCC", "HCI", "HCKT", "HCSG", "HDB", "HEI", "HELE", "HEPS", "HIG", "HII", 
    "HIMS", "HIMX", "HIPO", "HITI"
]

if not os.path.exists(CSV_DATOTEKA):
    print(f"[NAPAKA] Glavna datoteka '{CSV_DATOTEKA}' ne obstaja. Najprej zaženi glavni skener.")
    os._exit(0)

# Preberemo trenutno bazo, da vemo, kaj že imamo noter
df_obstojeca = pd.read_csv(CSV_DATOTEKA)
ze_shranjeni = df_obstojeca['Ticker'].astype(str).tolist()

print(f"[INFO] V obstoječi bazi imaš trenutno {len(ze_shranjeni)} delnic.")
print(f"[START] Začenjam kirurško preverjanje {len(izpadle_delnice)} ponovnih zahtevkov...")
print("---------------------------------------------------------")

novi_tickerji = []
nove_regije = []

for krog, ticker in enumerate(izpadle_delnice, 1):
    # Če je delnica po nekem naključju že v CSV-ju, jo preskočimo, da ne delamo dvojnikov
    if ticker in ze_shranjeni:
        continue
        
    try:
        delnica = yf.Ticker(ticker)
        # Prenesemo podatke (uporabimo daljšo pavzo in ponoven poskus, če Yahoo zataji)
        data = delnica.history(start="2021-01-01", interval="1wk", actions=False)
        
        if data is None or data.empty or len(data) < 205:
            continue
            
        close_prices = data['Close'].dropna()
        if close_prices.empty or len(close_prices) < 205:
            continue
            
        # Filter za Penny Stocks (cena nad 2.00 $)
        zadnja_cena = float(close_prices.iloc[-1])
        if zadnja_cena < 2.00:
            print(f"      [FILTER] {ticker} preverjen, vendar zavržen (Cena: ${zadnja_cena:.2f} < $2.00)")
            continue
            
        # Če uspešno opravi izpit, ga shranimo v začasni seznam
        novi_tickerji.append(ticker)
        nove_regije.append("NASDAQ (ZDA)")
        print(f"      [USPEH] {ticker} je odklepan in ustreza pogojem! (Zadnja cena: ${zadnja_cena:.2f})")
        
        # Povečamo pavzo med kliki na 0.3 sekunde, da strežnik ponovno ne blokira najinega IP-ja!
        time.sleep(0.3)
        
    except Exception as e:
        print(f"      [X] Ticker {ticker} se še vedno ne odziva.")
        continue

# ==============================================================================
# ZAPIS IN DODAJANJE (APPEND) V OBSTOJEČO CSV DATOTEKO
# ==============================================================================
if novi_tickerji:
    print("\n[ZAPIS] Dodajam uspešno rešena podjetja v obstoječo bazo...")
    
    df_novi = pd.DataFrame({
        "Ticker": novi_tickerji,
        "Trg": nove_regije
    })
    
    # Združimo staro tabelo z novimi podatki
    df_končna_baza = pd.concat([df_obstojeca, df_novi], ignore_index=True)
    # Dokončno izbrišemo morebitne dvojnike za vsak primer
    df_končna_baza = df_končna_baza.drop_duplicates(subset=["Ticker"])
    
    try:
        df_končna_baza.to_csv(CSV_DATOTEKA, index=False)
        print("=========================================================")
        print(f"[KONČANO] Dopolnjevanje uspešno zaključeno!")
        print(f"          Nova skupna številka zdravih delnic v CSV: {len(df_končna_baza)}")
        print("=========================================================")
    except PermissionError:
        print(f"\n[KRITIČNA NAPAKA] Zapri datoteko '{CSV_DATOTEKA}' v Excelu!")
else:
    print("\n[INFO] Nobena od izpadlih delnic ni ustrezala filtrom ali pa so že v bazi.")
    print("=========================================================")