import yfinance as yf
import pandas as pd
import numpy as np
from scipy.optimize import differential_evolution
import time
import warnings

warnings.filterwarnings("ignore")

print("=========================================================")
print("🧬 OGM MACHINE LEARNING: BUY OPTIMIZACIJA (4 STEBRI)")
print("=========================================================")

# Nabor vrhunskih delnic (Tech, Biotech, Blue-Chip)
TICKERJI = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AVGO", "PEP", "COST", 
    "CSCO", "TMUS", "ADBE", "TXN", "CMCSA", "AMD", "NFLX", "QCOM", "INTU", "HON", 
    "AMAT", "AMGN", "SBUX", "ISRG", "MDLZ", "BKNG", "GILD", "ADI", "VRTX", "REGN", 
    "PANW", "SNPS", "KLAC", "CDNS", "CSX", "MELI", "MU", "PYPL", "MAR", "CTAS", 
    "ASML", "NXPI", "WDAY", "ORLY", "MNST", "FTNT", "PCAR", "LRCX", "PAYX", "CPRT",
    "ROST", "KDP", "EA", "TTWO", "ILMN", "ALGN", "IDXX", "EXC", "DXCM", "CRWD", 
    "MCHP", "CTSH", "ENPH", "INTC", "LULU", "TEAM", "MRNA", "ZM", "DOCU", "OKTA"
]

ZGODOVINA_PODATKOV = {}
print(f"Prenašam zgodovino in fundamente za {len(TICKERJI)} delnic...")
print("To bo trajalo približno 1-2 minuti, saj prenašamo tudi bilance...")

for count, t in enumerate(TICKERJI, 1):
    try:
        stock = yf.Ticker(t)
        hist = stock.history(start="2013-01-01", end="2023-12-31", interval="1wk", actions=False)
        
        if len(hist) >= 200:
            info = stock.info
            mcap = info.get('marketCap', 0)
            rev = info.get('revenueGrowth', 0)
            
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
                
            close_series = pd.to_numeric(hist['Close'].squeeze(), errors='coerce').dropna()
            
            if len(close_series) >= 200:
                ZGODOVINA_PODATKOV[t] = {
                    'close': close_series,
                    'mcap': mcap if mcap else 0,
                    'rev': rev if rev else 0
                }
    except Exception:
        pass 
        
print(f"Uspešno naloženih {len(ZGODOVINA_PODATKOV)} delnic. Pripravljen na učenje!\n")

def izracunaj_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    return 100 - (100 / (1 + (gain / loss)))

# ==============================================================================
# CILJNA FUNKCIJA ZA BUY SIGNALE
# ==============================================================================
def buy_fitness_funkcija(parametri):
    w_mcap, w_rev, w_ma, w_rsi, prag_buy = parametri
    
    # NORMALIZACIJA: Zagotovimo, da je vsota vseh uteži natanko 100 točk
    skupaj = w_mcap + w_rev + w_ma + w_rsi
    w_mcap = (w_mcap / skupaj) * 100.0
    w_rev = (w_rev / skupaj) * 100.0
    w_ma = (w_ma / skupaj) * 100.0
    w_rsi = (w_rsi / skupaj) * 100.0
    
    skupni_signali = 0
    uspesni_signali = 0
    vsi_donosi = []
    
    for ticker, podatki in ZGODOVINA_PODATKOV.items():
        close = podatki['close']
        mcap = podatki['mcap']
        rev = podatki['rev']
        
        # 1. STEBER: Fundamentalna ocena podjetja (Statična za backtest)
        score_mcap = w_mcap if mcap > 20e9 else (w_mcap * 0.5 if mcap > 10e9 else 0.0)
        score_rev = w_rev if rev > 0.15 else (w_rev * 0.6 if rev > 0.10 else 0.0)
        base_fundament_score = score_mcap + score_rev
        
        # 2. STEBER: Tehnični izračuni
        ma200 = close.rolling(window=200).mean()
        rsi = izracunaj_rsi(close)
        
        ma200_safe = ma200.replace(0, np.nan)
        oddaljenost_arr = ((close - ma200_safe) / ma200_safe) * 100
        
        x_odd = np.asarray(oddaljenost_arr, dtype=float)
        x_rsi = np.asarray(rsi, dtype=float)
        
        tocke_ma = np.zeros_like(x_odd)
        pos_mask = (x_odd >= 0) & (~np.isnan(x_odd))
        neg_mask = (x_odd < 0) & (~np.isnan(x_odd))
        
        # Prilagojena interpolacija glede na novo utež (razmerja ostajajo enaka kot v originalu)
        tocke_ma[pos_mask] = np.interp(x_odd[pos_mask], [0, 2, 10, 25, 50], [w_ma*(33/35), w_ma, w_ma*(22/35), w_ma*(8/35), 0.0])
        tocke_ma[neg_mask] = np.interp(x_odd[neg_mask], [-20, -10, -5, 0], [0.0, w_ma*(12/35), w_ma*(25/35), w_ma*(33/35)])
        
        tocke_rsi = np.interp(x_rsi, [30, 45, 60, 70, 80], [w_rsi, w_rsi*0.8, w_rsi*0.5, w_rsi*0.2, 0.0])
        
        # SKUPNI SCORE (Max 100)
        ogm_zgodovina = base_fundament_score + tocke_ma + tocke_rsi
        dates = close.index
        
        zadnji_indeks_signala = -999
        
        for i in range(200, len(close)):
            if dates[i].year < 2017:
                continue
                
            if ogm_zgodovina[i] >= prag_buy and (i - zadnji_indeks_signala) > 26: 
                cena_ob_signalu = close.iloc[i]
                konec_idx = min(i + 52, len(close))
                
                if konec_idx > i + 1:
                    max_cena_12m = close.iloc[i:konec_idx].max()
                else:
                    max_cena_12m = cena_ob_signalu
                    
                donos = ((max_cena_12m - cena_ob_signalu) / cena_ob_signalu) * 100
                
                vsi_donosi.append(donos)
                skupni_signali += 1
                if donos >= 15.0: # Pogoj za uspešen signal: vsaj 15% donos v letu dni
                    uspesni_signali += 1
                    
                zadnji_indeks_signala = i

    # Kazen proti Overfittingu
    if skupni_signali < 30:
        return 1000.0
        
    avg_return = np.mean(vsi_donosi)
    win_rate = uspesni_signali / skupni_signali
    
    # Maksimiziramo win rate in povprečen donos
    fitness = -(avg_return * win_rate)
    return float(fitness)

# ==============================================================================
# MEJE ISKANJA (Surove uteži pred normalizacijo in Prag)
# ==============================================================================
meje = [
    (10.0, 40.0),  # w_mcap
    (10.0, 40.0),  # w_rev
    (20.0, 60.0),  # w_ma
    (10.0, 40.0),  # w_rsi
    (65.0, 85.0),  # prag_buy (Kje sprožimo nakup)
]

print("Začenjam evolucijski proces (Iskanje idealne formule do 100 točk)...")
start_time = time.time()

# Funkcija, ki jo algoritem pokliče ob koncu VSAKE generacije
def prikazi_napredek(xk, convergence=None):
    print(f"🧬 Generacija uspešno zaključena! Trenutni najboljši fit (kazen/nagrada): {buy_fitness_funkcija(xk):.2f}")

print("Začenjam evolucijski proces (Iskanje idealne formule do 100 točk)...")
start_time = time.time()

# Dodan parameter callback=prikazi_napredek
rezultat = differential_evolution(
    buy_fitness_funkcija, 
    meje, 
    strategy='best1bin', 
    maxiter=25, 
    popsize=15, 
    mutation=(0.5, 1), 
    recombination=0.7, 
    polish=True,
    callback=prikazi_napredek
)
# NORMALIZIRAMO KONČNE REZULTATE ZA IZPIS
opt = rezultat.x
skupaj_opt = opt[0] + opt[1] + opt[2] + opt[3]
opt_mcap = (opt[0] / skupaj_opt) * 100.0
opt_rev = (opt[1] / skupaj_opt) * 100.0
opt_ma = (opt[2] / skupaj_opt) * 100.0
opt_rsi = (opt[3] / skupaj_opt) * 100.0
opt_prag = opt[4]

print("\n=========================================================")
print("✨ EVOLUCIJA ZAKLJUČENA! OPTIMALNA 'BUY' FORMULA (Do 100 točk):")
print("=========================================================")
print("🏛️ FUNDAMENTI:")
print(f"🥇 Max točk - Market Cap: {opt_mcap:.1f} točk")
print(f"🥇 Max točk - Rast Prihodkov: {opt_rev:.1f} točk")
print("📈 TEHNIČNA SLIKA:")
print(f"🥇 Max točk - Oddaljenost MA200: {opt_ma:.1f} točk")
print(f"🥇 Max točk - RSI Momentum: {opt_rsi:.1f} točk")
print("---------------------------------------------------------")
print(f"🚀 Najboljši sprožilec za NAKUP: OGM Score preseže > {opt_prag:.1f} točk")
print(f"⏱️ Čas učenja: {time.time() - start_time:.1f} sekund")
print("=========================================================\n")