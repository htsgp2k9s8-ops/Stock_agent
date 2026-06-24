import yfinance as yf
import pandas as pd
import numpy as np
import optuna
import time
from datetime import datetime
import webbrowser
import os

# Izklopimo opozorila Optune
optuna.logging.set_verbosity(optuna.logging.WARNING)

print("=========================================================")
print("🧠 OGM AI OPTIMIZATOR v2.0: Walk-Forward + Fundamenti")
print("=========================================================")

CSV_DATOTEKA = "moje_globalne_delnice_50.csv"
MAX_DELNIC_ZA_TEST = 5  # Pusti na malo za hitro testiranje
STEVILO_ITERACIJ = 200   

# Datumi za Walk-Forward
TRAIN_START = "2015-01-01"
TRAIN_END = "2023-12-31"
TEST_START = "2022-01-01"

# 1. Funkcija za hitro simulacijo (Backtest)
def simuliraj_trgovanje(closes, rsis, ma_diffs, rsi_buy, ma_buy, take_profit, stop_loss):
    """
    Simulira trgovanje na podlagi tehničnih parametrov.
    """
    capital = 100.0 # Začnemo s 100%
    in_position = False
    entry_price = 0.0
    št_trgovanj = 0
    
    for i in range(len(closes)):
        # Preskočimo NaN vrednosti, ki nastanejo zaradi MA in RSI na začetku
        if np.isnan(closes[i]) or np.isnan(rsis[i]) or np.isnan(ma_diffs[i]):
            continue

        if not in_position:
            if rsis[i] < rsi_buy and ma_diffs[i] < ma_buy:
                in_position = True
                entry_price = closes[i]
        else:
            change = (closes[i] - entry_price) / entry_price
            if change >= take_profit or change <= -stop_loss:
                capital *= (1 + change)
                in_position = False
                št_trgovanj += 1
                
    # Če smo na koncu še v poziciji, jo navidezno zapremo
    if in_position:
        change = (closes[-1] - entry_price) / entry_price
        capital *= (1 + change)
        št_trgovanj += 1
        
    return capital, št_trgovanj

# 2. Optimizacija posamezne delnice
def optimize_stock(ticker):
    print(f"\n[{ticker}] Prenašam podatke in treniram AI...")
    try:
        # Pridobimo podatke od leta 2015 do danes
        df = yf.download(ticker, start=TRAIN_START, interval="1d", progress=False)
        if df.empty or len(df) < 500:
            print(f"[{ticker}] Premalo podatkov.")
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # Pridobimo trenutne fundamente
        info = yf.Ticker(ticker).info
        trenutni_pe = info.get('trailingPE', 999) # Če ni podatka, damo 999, da ga filter izloči
        trenutni_peg = info.get('pegRatio', 999)

        # Izračun indikatorjev
        df['MA200'] = df['Close'].rolling(window=200).mean()
        df['MA_Odmik'] = ((df['Close'] - df['MA200']) / df['MA200']) * 100
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # --- WALK-FORWARD RAZDELITEV ---
        # IN-SAMPLE (2015 - 2021)
        df_train = df.loc[TRAIN_START:TRAIN_END].copy()
        
        # OUT-OF-SAMPLE (2022 - danes)
        df_test = df.loc[TEST_START:].copy()

        if len(df_train) < 200 or len(df_test) < 100:
             print(f"[{ticker}] Premalo podatkov za razdelitev na Train/Test.")
             return None

        # Objective funkcija za AI (učenje SAMO na Train podatkih)
        def objective(trial):
            # Parametri za iskanje
            rsi_buy = trial.suggest_int('rsi_buy', 20, 50)
            ma_buy = trial.suggest_float('ma_buy', -40.0, 0.0)
            take_profit = trial.suggest_float('take_profit', 0.10, 1.50)
            stop_loss = trial.suggest_float('stop_loss', 0.05, 0.30)
            max_dovoljen_pe = trial.suggest_int('max_pe', 10, 80)
            max_dovoljen_peg = trial.suggest_float('max_peg', 0.5, 4.0)

            # Če trenutni fundamenti podjetja ne ustrezajo iskanim parametrom, zavrnemo to kombinacijo
            if trenutni_pe > max_dovoljen_pe or trenutni_peg > max_dovoljen_peg:
                return -100.0 # Kazen za slab fundament

            closes_train = df_train['Close'].values
            rsis_train = df_train['RSI'].values
            ma_diffs_train = df_train['MA_Odmik'].values

            koncni_kapital, st_trgovanj = simuliraj_trgovanje(closes_train, rsis_train, ma_diffs_train, rsi_buy, ma_buy, take_profit, stop_loss)
            
            # Če je bilo trgovanj premalo, to strategijo kaznujemo (ne želimo naključnih 1-kratnih zmag)
            if st_trgovanj < 2:
                return -50.0

            return koncni_kapital

        # Trening (In-Sample)
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=STEVILO_ITERACIJ)
        
        best = study.best_params
        best_return_train = study.best_value - 100 
        
        # Če je bil najboljši donos negativen (ali zaradi kazni), preskočimo
        if best_return_train <= 0:
             print(f"   -> [FAIL] AI ni našel dobičkonosne strategije za In-Sample.")
             return None

        print(f"   -> [IN-SAMPLE OK] Max donos (2015-2021): +{best_return_train:.1f}%")

        # --- TESTIRANJE NA OUT-OF-SAMPLE (2022 - danes) ---
        closes_test = df_test['Close'].values
        rsis_test = df_test['RSI'].values
        ma_diffs_test = df_test['MA_Odmik'].values

        # Uporabimo NAJDENE parametre na NOVEM obdobju
        kapital_test, st_trgovanj_test = simuliraj_trgovanje(
            closes_test, rsis_test, ma_diffs_test, 
            best['rsi_buy'], best['ma_buy'], best['take_profit'], best['stop_loss']
        )
        
        best_return_test = kapital_test - 100

        print(f"   -> [OUT-OF-SAMPLE] Donos (2022-danes): {best_return_test:.1f}% (Trgovanj: {st_trgovanj_test})")

        return {
            "ticker": ticker,
            "rsi_opt": best['rsi_buy'],
            "ma_opt": best['ma_buy'],
            "tp_opt": best['take_profit'] * 100, 
            "sl_opt": best['stop_loss'] * 100,
            "max_pe": best['max_pe'],
            "max_peg": best['max_peg'],
            "train_return": best_return_train,
            "test_return": best_return_test,
            "test_trades": st_trgovanj_test,
            "current_pe": trenutni_pe if trenutni_pe != 999 else 0.0,
            "current_peg": trenutni_peg if trenutni_peg != 999 else 0.0
        }

    except Exception as e:
        print(f"[{ticker}] Napaka pri izvedbi: {e}")
        return None

# ==============================================================================
# 3. GLAVNI PROCES
# ==============================================================================
if not os.path.exists(CSV_DATOTEKA):
    print(f"Napaka: {CSV_DATOTEKA} ne obstaja!")
    # Za testiranje bomo ustvarili dummy listo, če datoteke ni
    tickerji = ["AAPL", "MSFT", "NVDA", "AMZN", "META"]
else:
    df_baza = pd.read_csv(CSV_DATOTEKA)
    tickerji = df_baza['Ticker'].dropna().unique().tolist()[:MAX_DELNIC_ZA_TEST]

rezultati = []
start_time = time.time()

for t in tickerji:
    res = optimize_stock(t)
    if res:
        rezultati.append(res)

# Sortiramo po rezultatu na TESTNEM (OUT-OF-SAMPLE) obdobju
rezultati.sort(key=lambda x: x['test_return'], reverse=True)

trajanje = time.time() - start_time
print(f"\n✅ Optimizacija zaključena v {trajanje:.1f} sekundah.")
print("Generiram HTML poročilo...")

# ==============================================================================
# 4. GENERIRANJE HTML POROČILA
# ==============================================================================
html_vrstice = ""
for r in rezultati:
    test_color = "text-emerald-400" if r['test_return'] > 0 else "text-rose-400"
    html_vrstice += f"""
    <tr class="hover:bg-slate-700/30 transition-colors border-b border-slate-700/50">
        <td class="p-4 font-bold text-blue-400">{r['ticker']}</td>
        <td class="p-4 text-center">
            <span class="block text-xs text-slate-400">RSI < {r['rsi_opt']}</span>
            <span class="block text-xs text-slate-400">MA200 < {r['ma_opt']:.1f}%</span>
        </td>
        <td class="p-4 text-center">
            <span class="block text-xs text-slate-400">P/E do {r['max_pe']} (Trenutno: {r['current_pe']:.1f})</span>
            <span class="block text-xs text-slate-400">PEG do {r['max_peg']:.1f} (Trenutno: {r['current_peg']:.2f})</span>
        </td>
        <td class="p-4 text-center">
            <span class="block text-xs text-emerald-500">TP: +{r['tp_opt']:.1f}%</span>
            <span class="block text-xs text-rose-500">SL: -{r['sl_opt']:.1f}%</span>
        </td>
        <td class="p-4 text-center text-slate-300">+{r['train_return']:.1f}%</td>
        <td class="p-4 text-right">
            <div class="inline-flex items-center justify-center bg-slate-800/50 border border-slate-600 px-3 py-1 rounded-md">
                <span class="font-bold text-lg {test_color}">{r['test_return']:.1f}%</span>
                <span class="ml-2 text-xs text-slate-500">({r['test_trades']} trg.)</span>
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
    <title>OGM Walk-Forward Optimizator</title>
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
                <h1 class="text-3xl font-extrabold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-400">
                    OGM WALK-FORWARD AI
                </h1>
                <p class="text-slate-400 mt-2">Trening: 2015-2021 | Testiranje: 2022-2026 | Upošteva P/E in PEG</p>
            </div>
            <div class="text-right">
                <p class="text-sm text-slate-500">Čas: {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
                <p class="text-sm text-slate-500">Analiziranih: {len(rezultati)} delnic</p>
            </div>
        </div>

        <div class="glass-panel rounded-xl overflow-hidden">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-800 text-slate-300 text-xs uppercase tracking-wider">
                        <th class="p-4 font-semibold">Ticker</th>
                        <th class="p-4 font-semibold text-center">Tech. Pogoji (Vstop)</th>
                        <th class="p-4 font-semibold text-center">Fundamenti (Filter)</th>
                        <th class="p-4 font-semibold text-center">Izhod (TP / SL)</th>
                        <th class="p-4 font-semibold text-center border-l border-slate-700">IN-SAMPLE (15-21)</th>
                        <th class="p-4 font-semibold text-right">OUT-OF-SAMPLE (22-26)</th>
                    </tr>
                </thead>
                <tbody>
                    {html_vrstice}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""

ime_datoteke = "OGM_AI_WALKFORWARD.html"
with open(ime_datoteke, "w", encoding="utf-8") as f:
    f.write(html_content)

url = "file://" + os.path.realpath(ime_datoteke)
webbrowser.open(url)
print(f"Poročilo odprto v brskalniku: {ime_datoteke}")