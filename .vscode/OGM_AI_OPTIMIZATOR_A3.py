import yfinance as yf
import pandas as pd
import numpy as np
import optuna
import time
from datetime import datetime
import webbrowser
import os

# Izklopimo opozorila Optune, da je terminal bolj pregleden
optuna.logging.set_verbosity(optuna.logging.WARNING)

print("=========================================================")
print("🧠 OGM AI OPTIMIZATOR v3.0: Lasten izračun P/E in PEG")
print("=========================================================")

CSV_DATOTEKA = "moje_globalne_delnice_50.csv"
MAX_DELNIC_ZA_TEST = 5  # Začnimo s 5 za hitrejši test
STEVILO_ITERACIJ = 200

# Datumi za Walk-Forward
TRAIN_START = "2018-01-01" # Skrajšal sem na 2018, ker so starejši podatki o bilancah preko yfinance pogosto nepopolni
TRAIN_END = "2024-12-31"
TEST_START = "2022-01-01"

# 1. Funkcija za hitro simulacijo (Backtest)
def simuliraj_trgovanje(df, rsi_buy, ma_buy, take_profit, stop_loss, max_pe, max_peg):
    """
    Simulira trgovanje. Tukaj sedaj uporabljamo DataFrame (df),
    saj rabimo dostop do naših izračunanih 'P/E_proxy' in 'PEG_proxy' za vsak dan.
    """
    capital = 100.0
    in_position = False
    entry_price = 0.0
    st_trgovanj = 0
    
    # Preverimo, ali imamo potrebne stolpce (če ni bilanc, jih ne bo)
    if 'P/E_proxy' not in df.columns or 'PEG_proxy' not in df.columns:
        return -100.0, 0

    for i in range(len(df)):
        row = df.iloc[i]
        
        # Preskočimo dneve, kjer nimamo vseh podatkov
        if pd.isna(row['Close']) or pd.isna(row['RSI']) or pd.isna(row['MA_Odmik']) or pd.isna(row['P/E_proxy']):
            continue

        if not in_position:
            # Pogoj za nakup sedaj vključuje NAŠE izračunane fundamente za tisti določen dan
            if (row['RSI'] < rsi_buy and 
                row['MA_Odmik'] < ma_buy and 
                row['P/E_proxy'] > 0 and row['P/E_proxy'] <= max_pe and # P/E mora biti pozitiven in pod mejo
                row['PEG_proxy'] > 0 and row['PEG_proxy'] <= max_peg):  # PEG mora biti pozitiven in pod mejo
                
                in_position = True
                entry_price = row['Close']
        else:
            change = (row['Close'] - entry_price) / entry_price
            if change >= take_profit or change <= -stop_loss:
                capital *= (1 + change)
                in_position = False
                st_trgovanj += 1
                
    if in_position:
        change = (df['Close'].iloc[-1] - entry_price) / entry_price
        capital *= (1 + change)
        st_trgovanj += 1
        
    return capital, st_trgovanj

# 2. Pridobivanje in izračun podatkov
def pripravi_podatke(ticker):
    print(f"[{ticker}] Prenašam cene in bilance...")
    try:
        # Prenašamo cene
        df = yf.download(ticker, start=TRAIN_START, interval="1d", progress=False)
        if df.empty or len(df) < 500:
            return None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # ---------------------------------------------------------
        # IZRAČUN LASTNIH FUNDAMENTOV (Proxy)
        # ---------------------------------------------------------
        t = yf.Ticker(ticker)
        
        # 1. Pridobimo letne izkaze poslovnega izida (Income Statement)
        try:
            # Uporabimo letne podatke, saj so četrtletni za starejša leta pogosto nedostopni
            income_stmt = t.income_stmt 
            if income_stmt.empty:
                 income_stmt = t.financials # Starejša verzija yfinance
        except Exception:
            print(f"[{ticker}] Opozorilo: Ni mogoče pridobiti bilanc.")
            return None

        if income_stmt is None or income_stmt.empty:
            return None
            
        # Iščemo EPS (Earnings Per Share)
        # Imena vrstic se lahko razlikujejo, preverimo nekaj najpogostejših
        eps_row_names = ['Diluted EPS', 'Basic EPS', 'EPS']
        eps_data = None
        
        for name in eps_row_names:
            if name in income_stmt.index:
                eps_data = income_stmt.loc[name]
                break
                
        if eps_data is None:
             print(f"[{ticker}] Opozorilo: Ne najdem EPS podatkov v bilancah.")
             return None

        # Pretvori v DataFrame in uredi po datumu (najstarejši naprej)
        eps_df = pd.DataFrame({'EPS': eps_data}).sort_index()
        
        # Izračunamo letno rast EPS (za PEG)
        eps_df['EPS_Growth'] = eps_df['EPS'].pct_change() * 100 # v odstotkih

        # 2. Združimo EPS z dnevnimi cenami (Forward Fill)
        # Na vsak dan od objave bilance naprej, uporabljamo tisti EPS
        df['EPS'] = np.nan
        df['EPS_Growth'] = np.nan
        
        for date, row in eps_df.iterrows():
            # Poskusimo najti čim bližji datum v našem DataFrameu s cenami
            # (Lahko se zgodi, da datum bilance pade na vikend)
            if date in df.index:
                df.loc[date, 'EPS'] = row['EPS']
                df.loc[date, 'EPS_Growth'] = row['EPS_Growth']
            else:
                 # Če datuma ni, poiščemo najbližjega naslednjega
                 naslednji_dnevi = df.index[df.index > date]
                 if len(naslednji_dnevi) > 0:
                     df.loc[naslednji_dnevi[0], 'EPS'] = row['EPS']
                     df.loc[naslednji_dnevi[0], 'EPS_Growth'] = row['EPS_Growth']

        # Zapolnimo prazna polja vnaprej (ffill = forward fill)
        df['EPS'] = df['EPS'].ffill()
        df['EPS_Growth'] = df['EPS_Growth'].ffill()

        # 3. Končni izračun P/E in PEG za vsak dan
        # Cena / Dobiček na delnico
        df['P/E_proxy'] = df['Close'] / df['EPS'] 
        
        # P/E / Rast dobička (če je rast negativna, ali 0, bomo dobili napačne/neskončne vrednosti, 
        # zato bomo negativne in nan zamenjali z nečim visokim, da jih filter izloči)
        df['PEG_proxy'] = np.where((df['EPS_Growth'] > 0) & (df['P/E_proxy'] > 0), 
                                   df['P/E_proxy'] / df['EPS_Growth'], 
                                   999) 

        # ---------------------------------------------------------
        # IZRAČUN TEHNIČNIH INDIKATORJEV
        # ---------------------------------------------------------
        df['MA200'] = df['Close'].rolling(window=200).mean()
        df['MA_Odmik'] = ((df['Close'] - df['MA200']) / df['MA200']) * 100
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        return df

    except Exception as e:
        print(f"[{ticker}] Napaka: {e}")
        return None

# 3. Optimizacija
def optimize_stock(ticker):
    df = pripravi_podatke(ticker)
    if df is None:
        return None

    # Razdelitev na Train in Test
    df_train = df.loc[TRAIN_START:TRAIN_END].copy()
    df_test = df.loc[TEST_START:].copy()

    if len(df_train) < 200 or len(df_test) < 100:
         print(f"[{ticker}] Premalo podatkov po izračunih za Train/Test.")
         return None

    print(f"[{ticker}] Učim AI na obdobju {TRAIN_START} do {TRAIN_END}...")

    def objective(trial):
        rsi_buy = trial.suggest_int('rsi_buy', 20, 50)
        ma_buy = trial.suggest_float('ma_buy', -40.0, 5.0)
        take_profit = trial.suggest_float('take_profit', 0.10, 1.50)
        stop_loss = trial.suggest_float('stop_loss', 0.05, 0.30)
        
        # AI zdaj preverja različne meje za NAŠ izračunan P/E in PEG
        max_pe = trial.suggest_int('max_pe', 10, 100)
        max_peg = trial.suggest_float('max_peg', 0.5, 5.0)

        koncni_kapital, st_trgovanj = simuliraj_trgovanje(df_train, rsi_buy, ma_buy, take_profit, stop_loss, max_pe, max_peg)
        
        if st_trgovanj < 2:
            return -50.0

        return koncni_kapital

    # Trening (In-Sample)
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=STEVILO_ITERACIJ)
    
    best = study.best_params
    best_return_train = study.best_value - 100 
    
    if best_return_train <= 0:
         print(f"   -> [FAIL] AI ni našel profitabilne poti.")
         return None

    # Testiranje (Out-of-Sample)
    kapital_test, st_trgovanj_test = simuliraj_trgovanje(
        df_test, best['rsi_buy'], best['ma_buy'], best['take_profit'], best['stop_loss'], best['max_pe'], best['max_peg']
    )
    
    best_return_test = kapital_test - 100

    # Pridobimo "Trenutni" P/E in PEG iz naših izračunov na zadnji dan (za prikaz)
    zadnji_dan = df.iloc[-1]
    trenutni_pe_prikaz = zadnji_dan['P/E_proxy'] if zadnji_dan['P/E_proxy'] != 999 else 0.0
    trenutni_peg_prikaz = zadnji_dan['PEG_proxy'] if zadnji_dan['PEG_proxy'] != 999 else 0.0

    print(f"   -> USPEH! Test donos: {best_return_test:.1f}%")

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
        "current_pe": trenutni_pe_prikaz,
        "current_peg": trenutni_peg_prikaz
    }

# ==============================================================================
# GLAVNI PROCES IN HTML
# ==============================================================================
if not os.path.exists(CSV_DATOTEKA):
    print(f"Napaka: {CSV_DATOTEKA} ne obstaja! Uporabljam testni seznam.")
    tickerji = ["AAPL", "MSFT", "TSLA", "META", "AMZN"]
else:
    df_baza = pd.read_csv(CSV_DATOTEKA)
    tickerji = df_baza['Ticker'].dropna().unique().tolist()[:MAX_DELNIC_ZA_TEST]

rezultati = []
start_time = time.time()

for t in tickerji:
    res = optimize_stock(t)
    if res:
        rezultati.append(res)

rezultati.sort(key=lambda x: x['test_return'], reverse=True)

trajanje = time.time() - start_time
print(f"\n✅ Optimizacija zaključena v {trajanje:.1f} sekundah.")

# Generiranje HTML-ja...
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
            <span class="block text-xs text-amber-200">MAX P/E {r['max_pe']} (Zadnji: {r['current_pe']:.1f})</span>
            <span class="block text-xs text-amber-200">MAX PEG {r['max_peg']:.1f} (Zadnji: {r['current_peg']:.2f})</span>
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
    <title>OGM Custom Fundamental Optimizator</title>
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
                <h1 class="text-3xl font-extrabold bg-clip-text text-transparent bg-gradient-to-r from-amber-400 to-orange-400">
                    OGM CUSTOM FUNDAMENTAL AI
                </h1>
                <p class="text-slate-400 mt-2">Dnevni izračun P/E in PEG | Trening: 18-21 | Testiranje: 22-26</p>
            </div>
            <div class="text-right">
                <p class="text-sm text-slate-500">Čas: {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
                <p class="text-sm text-slate-500">Uspešno analiziranih: {len(rezultati)} delnic</p>
            </div>
        </div>

        <div class="glass-panel rounded-xl overflow-hidden">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-800 text-slate-300 text-xs uppercase tracking-wider">
                        <th class="p-4 font-semibold">Ticker</th>
                        <th class="p-4 font-semibold text-center">Tech. Pogoji (Vstop)</th>
                        <th class="p-4 font-semibold text-center">Izračunani Fundamenti (Filter)</th>
                        <th class="p-4 font-semibold text-center">Izhod (TP / SL)</th>
                        <th class="p-4 font-semibold text-center border-l border-slate-700">IN-SAMPLE (18-21)</th>
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

ime_datoteke = "OGM_AI_CUSTOM_FUNDAMENTALS.html"
with open(ime_datoteke, "w", encoding="utf-8") as f:
    f.write(html_content)

url = "file://" + os.path.realpath(ime_datoteke)
try:
    webbrowser.open(url)
except:
    pass
print(f"Poročilo shranjeno kot: {ime_datoteke}")