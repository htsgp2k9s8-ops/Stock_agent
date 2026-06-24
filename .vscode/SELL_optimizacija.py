import yfinance as yf
import pandas as pd
import numpy as np
from scipy.optimize import differential_evolution
import time

print("=========================================================")
print("🧬 OGM MACHINE LEARNING: GENETSKI OPTIMIZATOR ZA SELL")
print("=========================================================")

# Testni nabor delnic za učenje (izločeni hyperscalerji, obdobje do konca 2023)
TICKERJI = ["AAPL", "MSFT", "AMZN", "META", "GOOGL", "NFLX", "ADBE", "CRM", "CSCO", "AVGO"]

# Vnaprejšnji prenos podatkov, da optimizacija teče ultra hitro v pomnilniku
ZGODOVINA_PODATKOV = {}
print("Prenašam zgodovinske podatke za optimizacijo...")
for t in TICKERJI:
    try:
        d = yf.Ticker(t).history(start="2016-01-01", end="2023-12-31", interval="1wk", actions=False)
        if len(d) >= 210:
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
                
            # KRITIČEN POPRAVEK: Prisilimo 'Close' v enodimenzionalen seznam čistih številk (float)
            close_series = pd.to_numeric(d['Close'].squeeze(), errors='coerce').dropna()
            
            if len(close_series) >= 210:
                ZGODOVINA_PODATKOV[t] = close_series
    except Exception as e:
        print(f"Napaka pri prenosu {t}: {e}")
        
print(f"Uspešno naloženih {len(ZGODOVINA_PODATKOV)} delnic.\n")

def izracunaj_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    return 100 - (100 / (1 + (gain / loss)))

# ==============================================================================
# CILJNA FUNKCIJA (FITNESS FUNCTION) - To ocenjuje genetski algoritem
# ==============================================================================
def sell_fitness_funkcija(parametri):
    # Algoritem nam pošlje testni paket parametrov (uteži in pragove)
    w_rsi, w_d10, w_d50, w_strmina, w_pe, prag_score, prag_parabola_3m = parametri
    
    skupni_signali = 0
    uspesni_signali = 0
    vsi_padci = []
    
    for ticker, close in ZGODOVINA_PODATKOV.items():
        ma10 = close.rolling(window=10).mean()
        ma50 = close.rolling(window=50).mean()
        ma200 = close.rolling(window=200).mean()
        ma100_avg = close.rolling(window=100).mean()
        rsi = izracunaj_rsi(close)
        
        dist_10_200 = ((ma10 - ma200) / ma200) * 100
        dist_50_200 = ((ma50 - ma200) / ma200) * 100
        strmina_10w = ((ma10 - ma10.shift(10)) / ma10.shift(10)) * 100
        pe_stretch = ((close - ma100_avg) / ma100_avg) * 100
        rast_12w = ((close - close.shift(12)) / close.shift(12)) * 100
        
        # VARNOSTNI POPRAVEK: Zagotovimo, da numpy vsekakor dobi 1D float format
        x_rsi = np.asarray(rsi, dtype=float)
        x_d10 = np.asarray(dist_10_200, dtype=float)
        x_d50 = np.asarray(dist_50_200, dtype=float)
        x_strmina = np.asarray(strmina_10w, dtype=float)
        x_pe = np.asarray(pe_stretch, dtype=float)
        
        # Interpolacija z uporabo trenutnih testnih uteži algoritma
        score_rsi = np.interp(x_rsi, [65.0, 75.0, 85.0], [0.0, float(w_rsi)/2.0, float(w_rsi)])
        score_d10 = np.interp(x_d10, [50.0, 70.0, 100.0], [0.0, float(w_d10)/2.0, float(w_d10)])
        score_d50 = np.interp(x_d50, [30.0, 40.0, 60.0], [0.0, float(w_d50)/2.0, float(w_d50)])
        score_strmina = np.interp(x_strmina, [10.0, 12.0, 20.0], [0.0, float(w_strmina)/2.0, float(w_strmina)])
        score_pe = np.interp(x_pe, [30.0, 40.0, 60.0], [0.0, float(w_pe)/2.0, float(w_pe)])
        
        klimaks_score = score_rsi + score_d10 + score_d50 + score_strmina + score_pe
        
        oborozen_counter = 0
        zadnji_signal_idx = -999
        
        for i in range(210, len(close)):
            trenutni_score = float(klimaks_score[i])
            trenutna_rast_3m = float(rast_12w.iloc[i])
            
            if trenutni_score >= prag_score and trenutna_rast_3m >= prag_parabola_3m:
                oborozen_counter = 4
                
            dva_padajoca = (close.iloc[i] < close.iloc[i-1]) and (close.iloc[i-1] < close.iloc[i-2])
            trigger_klimaks = (oborozen_counter > 0) and dva_padajoca and (rsi.iloc[i] > 75)
            trigger_trend_break = (oborozen_counter > 0) and (close.iloc[i] < ma10.iloc[i]) and (close.iloc[i-1] >= ma10.iloc[i-1])
            trigger_parabola = (trenutni_score >= 90.0) and (trenutna_rast_3m >= prag_parabola_3m)
            
            if (trigger_klimaks or trigger_trend_break or trigger_parabola) and (i - zadnji_signal_idx >= 8):
                idx_fut = min(i + 12, len(close) - 1)
                donos_3m = ((close.iloc[idx_fut] - close.iloc[i]) / close.iloc[i]) * 100
                
                skupni_signali += 1
                vsi_padci.append(donos_3m)
                if donos_3m < 0:  # Cena je padla, uspešna prodaja!
                    uspesni_signali += 1
                    
                zadnji_signal_idx = i
                oborozen_counter = 0
                
            if oborozen_counter > 0: oborozen_counter -= 1

    # Kazen, če algoritem nastavi pogoje tako strogo, da ne najde nobenega signala
    if skupni_signali < 5:
        return 100.0
        
    win_rate = uspesni_signali / skupni_signali
    povprecen_padec = np.mean(vsi_padci)
    
    # MATEMATIČNI FIT: Želimo čim nižji padec (zato povprečen padec, ki je negativen) 
    # in čim višji Win-Rate. differential_evolution minimizira funkcijo, zato obrnemo predznake.
    fitness = povprecen_padec - (win_rate * 50)
    return float(fitness)

# ==============================================================================
# MEJE ISKANJA ZA GENETSKI ALGORITEM (Bounds)
# ==============================================================================
# [max_rsi_točk, max_d10_točk, max_d50_točk, max_strmina_točk, max_pe_točk, prag_za_sell, min_3m_rast]
meje = [
    (10.0, 30.0),  # Utež RSI
    (15.0, 40.0),  # Utež Dist 10w
    (10.0, 25.0),  # Utež Dist 50w
    (10.0, 30.0),  # Utež Strmina
    (10.0, 30.0),  # Utež P/E Proxy
    (65.0, 85.0),  # Prag za aktivacijo (Risk Score)
    (15.0, 40.0)   # Zahtevana 3M rast v %
]

print("Začenjam evolucijski proces (Genetski algoritem)...")
start_time = time.time()

# Optimizacija (manjša populacija in generacije za hitrejši prikaz rezultata)
rezultat = differential_evolution(sell_fitness_funkcija, meje, strategy='best1bin', maxiter=20, popsize=15, mutation=(0.5, 1), recombination=0.7, polish=True)

print("\n=========================================================")
print("✨ EVOLUCIJA ZAKLJUČENA! OPTIMALNE NASTAVITVE ZA TVOJ PORTFELJ:")
print("=========================================================")
opt = rezultat.x
print(f"🥇 Optimalna utež RSI: {opt[0]:.1f} točk")
print(f"🥇 Optimalna utež Dist 10w vs 200w: {opt[1]:.1f} točk")
print(f"🥇 Optimalna utež Dist 50w vs 200w: {opt[2]:.1f} točk")
print(f"🥇 Optimalna utež Strmina 10w MA: {opt[3]:.1f} točk")
print(f"🥇 Optimalna utež P/E Stretch: {opt[4]:.1f} točk")
print(f"---------------------------------------------------------")
print(f"🚀 Najboljši prag za sprožitev (Risk Score): {opt[5]:.1f} točk")
print(f"🚀 Najboljši pogoj za 3M pred-rast: {opt[6]:.1f} %")
print(f"⏱️ Čas učenja: {time.time() - start_time:.1f} sekund")
print("=========================================================\n")