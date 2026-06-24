import yfinance as yf
import pandas as pd
import numpy as np
import optuna
import time
from datetime import datetime
import webbrowser
import os

# Izklopimo opozorila Optune, da ne smetimo terminala
optuna.logging.set_verbosity(optuna.logging.WARNING)

print("=========================================================")
print("🧠 OGM AI OPTIMIZATOR: Iskanje DNK profila delnic (HTML)")
print("=========================================================")

CSV_DATOTEKA = "moje_globalne_delnice_50.csv"
MAX_DELNIC_ZA_TEST = 5  # Povečaj, ko boš želel skenirati celoten trg!
STEVILO_ITERACIJ = 100   # Število poizkusov umetne inteligence na delnico (več = boljše, a počasneje)

# 1. Funkcija za hitro simulacijo (Backtest)
def simuliraj_trgovanje(closes, rsis, ma_diffs, rsi_buy, ma_buy, take_profit, stop_loss):
    capital = 100.0 # Začnemo s 100%
    in_position = False
    entry_price = 0.0
    
    for i in range(len(closes)):
        if not in_position:
            if rsis[i] < rsi_buy and ma_diffs[i] < ma_buy:
                in_position = True
                entry_price = closes[i]
        else:
            change = (closes[i] - entry_price) / entry_price
            if change >= take_profit or change <= -stop_loss:
                capital *= (1 + change)
                in_position = False
                
    # Če smo na koncu še v poziciji, jo navidezno zapremo
    if in_position:
        change = (closes[-1] - entry_price) / entry_price
        capital *= (1 + change)
        
    return capital

# 2. Optimizacija posamezne delnice
def optimize_stock(ticker):
    print(f"[{ticker}] Prenašam zgodovino in iščem optimalne parametre...")
    try:
        # Pridobimo dnevne podatke za zadnjih 5 let
        df = yf.download(ticker, period="5y", interval="1d", progress=False)
        if df.empty or len(df) < 250:
            print(f"[{ticker}] Premalo podatkov.")
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # Izračun indikatorjev
        df['MA200'] = df['Close'].rolling(window=200).mean()
        df['MA_Odmik'] = ((df['Close'] - df['MA200']) / df['MA200']) * 100
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        df = df.dropna()
        
        # Priprava numpy arrayev za hitrejšo izvedbo
        closes = df['Close'].values
        rsis = df['RSI'].values
        ma_diffs = df['MA_Odmik'].values
        
        # Objective funkcija za AI
        def objective(trial):
            rsi_buy = trial.suggest_int('rsi_buy', 20, 60)
            ma_buy = trial.suggest_float('ma_buy', -30.0, 5.0)
            take_profit = trial.suggest_float('take_profit', 0.10, 1.0)
            stop_loss = trial.suggest_float('stop_loss', 0.05, 0.30)
            
            return simuliraj_trgovanje(closes, rsis, ma_diffs, rsi_buy, ma_buy, take_profit, stop_loss)

        # Trening
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=STEVILO_ITERACIJ)
        
        best = study.best_params
        best_return = study.best_value - 100 # Čisti profit v %
        
        print(f"   -> USPEH! Max donos: +{best_return:.1f}%")
        
        return {
            "ticker": ticker,
            "rsi_opt": best['rsi_buy'],
            "ma_opt": best['ma_buy'],
            "tp_opt": best['take_profit'] * 100, # Vrnemo v procentih
            "sl_opt": best['stop_loss'] * 100,
            "max_return": best_return
        }

    except Exception as e:
        print(f"[{ticker}] Napaka: {e}")
        return None

# ==============================================================================
# 3. GLAVNI PROCES
# ==============================================================================
if not os.path.exists(CSV_DATOTEKA):
    print(f"Napaka: {CSV_DATOTEKA} ne obstaja!")
    exit()

df_baza = pd.read_csv(CSV_DATOTEKA)
tickerji = df_baza['Ticker'].dropna().unique().tolist()[:MAX_DELNIC_ZA_TEST]

rezultati = []
start_time = time.time()

for t in tickerji:
    res = optimize_stock(t)
    if res:
        rezultati.append(res)

# Sortiramo po tistih, ki imajo najboljši potencial za donos
rezultati.sort(key=lambda x: x['max_return'], reverse=True)

trajanje = time.time() - start_time
print(f"\n✅ Optimizacija zaključena v {trajanje:.1f} sekundah.")
print("Generiram HTML poročilo...")

# ==============================================================================
# 4. GENERIRANJE HTML POROČILA
# ==============================================================================
html_vrstice = ""
for r in rezultati:
    html_vrstice += f"""
    <tr class="hover:bg-slate-700/30 transition-colors border-b border-slate-700/50">
        <td class="p-4 font-bold text-blue-400">{r['ticker']}</td>
        <td class="p-4 text-center">RSI <strong class="text-white">{r['rsi_opt']}</strong></td>
        <td class="p-4 text-center text-rose-400"><strong>{r['ma_opt']:.1f}%</strong> pod MA200</td>
        <td class="p-4 text-center text-emerald-400">+{r['tp_opt']:.1f}%</td>
        <td class="p-4 text-center text-rose-500">-{r['sl_opt']:.1f}%</td>
        <td class="p-4 text-right">
            <div class="inline-flex items-center justify-center bg-emerald-900/30 border border-emerald-700 px-3 py-1 rounded-md">
                <span class="font-bold text-lg text-emerald-400">+{r['max_return']:.1f}%</span>
            </div>
        </td>
    </tr>
    """

html_content = f"""
<!DOCTYPE html>
<html lang="sl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OGM AI Optimizator</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ background-color: #0B0F19; color: #F8FAFC; font-family: 'Inter', sans-serif; }}
        .glass-panel {{ background: #1E293B; border: 1px solid #334155; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5); }}
    </style>
</head>
<body class="p-8">
    <div class="max-w-6xl mx-auto">
        <div class="flex items-center justify-between mb-8 border-b border-slate-700 pb-6">
            <div>
                <h1 class="text-3xl font-extrabold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-emerald-400">
                    OGM AI QUANT OPTIMIZATOR
                </h1>
                <p class="text-slate-400 mt-2">Personalizirani "DNK" nakupni parametri za posamezno delnico (Optuna Machine Learning)</p>
            </div>
            <div class="text-right">
                <p class="text-sm text-slate-500">Čas generiranja: {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
                <p class="text-sm text-slate-500">Analiziranih: {len(rezultati)} delnic</p>
            </div>
        </div>

        <div class="glass-panel rounded-xl overflow-hidden">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-800 text-slate-300 text-xs uppercase tracking-wider">
                        <th class="p-4 font-semibold">Ticker</th>
                        <th class="p-4 font-semibold text-center">Optimalen vstop (RSI)</th>
                        <th class="p-4 font-semibold text-center">Optimalen vstop (MA200)</th>
                        <th class="p-4 font-semibold text-center">Ciljni Profit (TP)</th>
                        <th class="p-4 font-semibold text-center">Stop-Loss (SL)</th>
                        <th class="p-4 font-semibold text-right">Max Zgodovinski Donos</th>
                    </tr>
                </thead>
                <tbody>
                    {html_vrstice}
                </tbody>
            </table>
        </div>
        
        <div class="mt-8 text-sm text-slate-500 text-center">
            *Rezultati so pridobljeni z Bayesovo optimizacijo hiperparametrov na podlagi zadnjih 5 let dnevnega trgovanja.
        </div>
    </div>
</body>
</html>
"""

ime_datoteke = "OGM_AI_OPTIMIZED_REPORT.html"
with open(ime_datoteke, "w", encoding="utf-8") as f:
    f.write(html_content)

url = "file://" + os.path.realpath(ime_datoteke)
webbrowser.open(url)
print(f"Poročilo odprto v brskalniku: {ime_datoteke}")