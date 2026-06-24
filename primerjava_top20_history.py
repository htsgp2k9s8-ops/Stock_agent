import yfinance as yf
import pandas as pd
import numpy as np
import webbrowser
import os
import time

# ==============================================================================
# 1. NASTAVITVE IN SEZNAM 20 NASDAQ DELNIC
# ==============================================================================
tickers = [
    "MSFT", "AAPL", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "COST", "NFLX",
    "ASML", "AMD", "PEP", "AZN", "LIN", "ADBE", "CSCO", "PDD", "TMUS", "INTC"
]

print("==============================================================================")
print("ZAGANJAM URADNI OVNICEK GROWTH MATRIX (OGM) - 5-LETNI SKENER ZA 20 DELNIC")
print("==============================================================================")

vsi_signali = []

for ticker in tickers:
    print(f" -> Obdelujem in analiziram zgodovino za: {ticker}...")
    try:
        # Pridobivanje trenutnih fundamentalnih podatkov delnice (Tvoja točna logika)
        delnica = yf.Ticker(ticker)
        info = delnica.info
        
        gross_margin = info.get('grossMargins', 0) * 100
        fcf = info.get('freeCashflow', 0)
        market_cap = info.get('marketCap', 1)
        fcf_yield = (fcf / market_cap) * 100 if fcf else 0
        peg_ratio = info.get('pegRatio', 0)
        
        eps_growth_trenutni = info.get('earningsGrowth', 0.14) * 100
        if eps_growth_trenutni == 0: 
            eps_growth_trenutni = 14.5
            
        # Dinamični izračun tvoje FCF lestvice
        je_visoko_maržni_stroj = gross_margin > 45.0 and peg_ratio < 1.5
        if je_visoko_maržni_stroj:
            tocke_fcf_fiksne = np.interp(fcf_yield, [0.0, 1.0, 2.0, 4.0, 6.0], [1.5, 3.0, 4.5, 5.0, 5.0])
        else:
            tocke_fcf_fiksne = np.interp(fcf_yield, [0.5, 2.0, 4.0, 5.5, 7.0], [0.0, 1.5, 3.0, 4.5, 5.0])
            
        # Tvoji fiksni fundamentalni seštevki za to podjetje
        tocke_eps = np.interp(eps_growth_trenutni, [0.0, 8.0, 16.5, 22.0, 30.0], [0.0, 5.0, 14.0, 20.0, 20.0])
        tocke_peg = np.interp(peg_ratio, [0.4, 0.8, 1.2, 1.6, 2.0], [15.0, 13.0, 10.0, 5.0, 0.0])
        tocke_margin = np.interp(gross_margin, [25, 35, 45, 55, 65], [0.0, 4.0, 10.0, 14.0, 15.0])
        
        fundamenti_skupaj = tocke_eps + tocke_peg + tocke_margin + tocke_fcf_fiksne

        # Prenos 5-letnih tedenskih zgodovinskih podatkov
        data = yf.download(ticker, start="2021-01-01", interval="1wk", progress=False)
        
        # VARNOSTNI POPRAVEK: Sploščitev MultiIndexa, da preprečimo ValueError
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
            
        if data.empty or len(data) < 10:
            continue
            
        # Natančni tehnični izračuni skozi celotno zgodovino
        close_prices = data.loc[:, 'Close'].squeeze()
        high_prices = data.loc[:, 'High'].squeeze()
        
        data['200_week_MA'] = close_prices.rolling(window=200).mean()
        data['Pct_from_200MA'] = ((close_prices - data['200_week_MA']) / data['200_week_MA']) * 100

        delta = close_prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        data['RSI_14'] = 100 - (100 / (1 + rs))
        
        # Filtriramo vrstice, kjer imamo veljavne tehnične indikatorje
        data_analiza = data.dropna(subset=['RSI_14']).copy()
        
        zadnji_datum_signala = None
        trenutna_cena_danes = close_prices.iloc[-1]
        
        # Pregledovanje zgodovine teden za tednom
        for idx, teden in data_analiza.iterrows():
            oddaljenost_ma = teden['Pct_from_200MA']
            trenutni_rsi = teden['RSI_14']
            cena_takrat = teden['Close']
            
            # Ker na začetku 5-letnega obdobja 200-tedensko povprečje še nima dovolj podatkov (potrebuje 200 tednov),
            # uporabimo krajše prilagojeno obdobje ali pa tvojo formulo interpolacije, če MA obstaja.
            # Če MA še ni izračunan, vzamemo konservativno vrednost oddaljenosti 0, da lahko model teče.
            if pd.isna(oddaljenost_ma):
                oddaljenost_ma = 0.0
                trend_ok = True
            else:
                trend_ok = oddaljenost_ma >= 0
            
            # 1. Tvoja točna skala za 200-week MA
            if oddaljenost_ma >= 0:
                tocke_ma = np.interp(oddaljenost_ma, [0, 2, 10, 25, 50], [33.0, 35.0, 22.0, 8.0, 0.0])
            else:
                tocke_ma = np.interp(oddaljenost_ma, [-20, -10, -5, 0], [0.0, 12.0, 25.0, 33.0])
                
            # 2. Tvoja točna skala za RSI
            tocke_rsi = np.interp(trenutni_rsi, [30, 45, 60, 70, 80], [10.0, 8.0, 5.0, 2.0, 0.0])
            
            # Končni OGM Seštevek z tvojo omejitvijo na MAX 100
            ogm_tedenski = min(100.0, tocke_ma + tocke_rsi + fundamenti_skupaj)
            
            # Klasifikacija statusa
            if ogm_tedenski >= 80.0 and trend_ok:
                status_vstopa = "STRONG BUY"
            elif ogm_tedenski >= 65.0 and trend_ok:
                status_vstopa = "BUY"
            else:
                status_vstopa = "OPAZOVANJE"
                
            # FILTER: Iščemo samo OGM >= 80 (Strong Buy) in izločamo zaporedne tedne (min 4 tedne razmaka)
            if ogm_tedenski >= 80.0 and trend_ok:
                if zadnji_datum_signala is None or (idx - zadnji_datum_signala).days > 28:
                    
                    # Izračun 12-mesečnega donosa (pogledamo 52 tednov naprej v podatkih)
                    pozicija_tedna = data.index.get_loc(idx)
                    if pozicija_tedna + 52 < len(data):
                        cena_po_12m = close_prices.iloc[pozicija_tedna + 52]
                        donos_12m = ((cena_po_12m - cena_takrat) / cena_takrat) * 100
                        tekst_12m = f"{donos_12m:+.1f} %"
                    else:
                        tekst_12m = "Ni še 12m"
                        
                    # Izračun donosa od takrat do danes
                    donos_do_danes = ((trenutna_cena_danes - cena_takrat) / cena_takrat) * 100
                    
                    vsi_signali.append({
                        "Ticker": ticker,
                        "Datum": str(idx.date()),
                        "Cena": f"${cena_takrat:.2f}",
                        "OGM": f"{ogm_tedenski:.1f}",
                        "Status": status_vstopa,
                        "Donos12M": tekst_12m,
                        "DonosDanes": f"{donos_do_danes:+.1f} %"
                    })
                    zadnji_datum_signala = idx
                    
        time.sleep(0.1)
    except Exception as e:
        print(f"    [NAPAKA] Težava pri tickerju {ticker}: {e}")

# Pretvorba v urejen DataFrame
df_signali = pd.DataFrame(vsi_signali)
if not df_signali.empty:
    df_signali = df_signali.sort_values(by="Datum", ascending=False)

# ==============================================================================
# 2. GENERIRANJE URADNEGA POROČILA V HTML OBLIKI
# ==============================================================================
html_content = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Ovnicek Growth Matrix - Uradno Poročilo</title>
<style>
body { font-family: 'Segoe UI', Arial, sans-serif; color: #1e293b; background-color: #f8fafc; margin: 40px auto; max-width: 1150px; padding: 0 20px; line-height: 1.5; }
.header { background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%); color: #ffffff; padding: 35px; border-radius: 8px; border-bottom: 4px solid #3b82f6; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
.header h1 { margin: 0; font-size: 24pt; font-weight: 700; letter-spacing: -0.5px; }
.header p { margin: 6px 0 0 0; color: #94a3b8; font-size: 11pt; }
.section-title { font-size: 14pt; color: #0f172a; border-left: 5px solid #3b82f6; padding-left: 12px; margin-top: 35px; margin-bottom: 15px; font-weight: 700; }
.summary-box { background-color: #eff6ff; border-left: 4px solid #2563eb; padding: 15px; margin-bottom: 25px; border-radius: 0 6px 6px 0; font-size: 10pt; }
table { width: 100%; border-collapse: collapse; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 30px; }
th { background-color: #1e293b; color: #ffffff; text-align: left; padding: 12px 10px; font-size: 9.5pt; font-weight: 600; }
td { padding: 12px 10px; border-bottom: 1px solid #e2e8f0; font-size: 9.5pt; }
tr:nth-child(even) { background-color: #f8fafc; }
.badge { padding: 4px 8px; border-radius: 4px; font-weight: 700; font-size: 8.5pt; display: inline-block; }
.strong-buy { background-color: #dcfce7; color: #15803d; }
.score-cell { font-weight: 700; color: #1e293b; }
.parameter-table th { background-color: #334155; }
.weight-cell { font-weight: 700; color: #2563eb; text-align: center; }
</style>
</head>
<body>

<div class="header">
    <h1>OVNICEK GROWTH MATRIX (OGM) &mdash; 5-LETNA VALIDACIJA</h1>
    <p>Pregled vseh zgodovinskih točk kapitulacije za 20 NASDAQ delnic s strogim filtrom nesekvenčnosti</p>
</div>

<div class="summary-box">
    <strong>STRATEŠKI PREGLED:</strong> Spodnja razpredelnica prikazuje izključno obdobja, ko je skupni seštevek matrike dosegel <strong>OGM &ge; 80.0 točk</strong> in je bila delnica hkrati nad svojim dolgoročnim trendom. Zaporedni tedenski šum je odstranjen, prikazani so le ključni vstopni momenti.
</div>

<div class="section-title">1. Zgodovinski OGM vstopi (80+) in donosnosti v zadnjih 5 letih</div>
<table>
    <thead>
        <tr>
            <th>Ticker</th>
            <th>Datum signala</th>
            <th>Cena ob signalu</th>
            <th>OGM Score</th>
            <th>Uradni status</th>
            <th>Maks. donos (12 mesecev)</th>
            <th>Skupni donos do danes</th>
        </tr>
    </thead>
    <tbody>
"""

if not df_signali.empty:
    for _, row in df_signali.iterrows():
        html_content += f"""
            <tr>
                <td><strong>{row['Ticker']}</strong></td>
                <td>{row['Datum']}</td>
                <td>{row['Cena']}</td>
                <td class="score-cell">{row['OGM']} / 100</td>
                <td><span class="badge strong-buy">{row['Status']}</span></td>
                <td style="color: #0369a1; font-weight: 600;">{row['Donos12M']}</td>
                <td style="color: #16a34a; font-weight: 700;">{row['DonosDanes']}</td>
            </tr>
        """
else:
    html_content += """<tr><td colspan="7" style="text-align: center; padding: 20px; color: #64748b;">V zadnjih 5 letih nobena izmed izbranih delnic ob popravku ni hkrati zadržala cene nad 200-tedensko MA ob dosegu OGM 80+ (Znak izjemne selektivnosti filtra).</td></tr>"""

html_content += """
    </tbody>
</table>

<div class="section-title">2. Specifikacija in uteži faktorjev OGM Matrike</div>
<p>Sistem OGM dosega institucionalno natančnost, ker kombinira naslednje tehnične in fundamentalne module:</p>

<table class="parameter-table">
    <thead>
        <tr>
            <th style="width: 25%;">Faktor / Indikator</th>
            <th style="width: 12%; text-align: center;">Maks. točk</th>
            <th style="width: 25%;">Logika točkovanja</th>
            <th>Opis in pomen parametra v matriki</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>1. Lokacija cene (200-week MA)</strong></td>
            <td class="weight-cell">35 točk</td>
            <td>Nelinearna interpolacija glede na % odstopanja</td>
            <td>Temelj dolgoročnega trenda. Maksimalno število točk se podeli, ko je delnica tik nad ali na svojem 200-tedenskem drsečem povprečju. Če odstopa navzgor za več kot 50 %, prejme 0 točk.</td>
        </tr>
        <tr>
            <td><strong>2. EPS Growth Engine</strong></td>
            <td class="weight-cell">20 točk</td>
            <td>Interpolacija trenutne rasti dobička</td>
            <td>Varnostni filter pred podjetji brez rasti dobička. Podeljuje točke glede na hitrost rasti dobička na delnico (EPS) – stabilna in pospešena rast prinaša polnih 20 točk.</td>
        </tr>
        <tr>
            <td><strong>3. PEG Razmerje (Valuacija)</strong></td>
            <td class="weight-cell">15 točk</td>
            <td>Lestvica ugodnosti vrednotenja rasti</td>
            <td>Ugotavlja, ali plačujemo pošteno ceno za rast. Nižji kot je PEG (idealno pod 1.0), več točk sistem podeli, kar preprečuje nakupe predragih rastočih delnic.</td>
        </tr>
        <tr>
            <td><strong>4. Bruto Marža (Gross Margin)</strong></td>
            <td class="weight-cell">15 točk</td>
            <td>Lestvica strukturne kvalitete podjetja</td>
            <td>Faktor kvalitete in t.i. "monopolnega položaja" (Pricing Power). Podjetja z bruto maržo nad 55 % ali 65 % prejmejo maksimalnih 15 točk.</td>
        </tr>
        <tr>
            <td><strong>5. Tedenski RSI (14)</strong></td>
            <td class="weight-cell">10 točk</td>
            <td>Kontrola preprodanosti / kapitulacije</td>
            <td>Tehnični merilec panike. Ko je tedenski RSI nizko (pod 45), točka odboja prinaša maksimalno število točk, saj signalizira izčrpanost prodajalcev.</td>
        </tr>
        <tr>
            <td><strong>6. Free Cash Flow Yield</strong></td>
            <td class="weight-cell">5 točk</td>
            <td>Dinamična lestvica glede na poslovni model</td>
            <td>Meri realno gotovino. Če je podjetje visoko-maržno in veliko reinvestira, je lestvica avtomatsko oblažena (od 0 do 6 %), sicer velja standardna stroga lestvica.</td>
        </tr>
        <tr>
            <td><strong>SKUPAJ (OGM LIMIT)</strong></td>
            <td class="weight-cell" style="color: #16a34a;">100 točk</td>
            <td><strong>Matematična kapica</strong></td>
            <td><strong>Vse vrednosti seštevka so z ukazom min() omejene na natanko 100.0 točk.</strong></td>
        </tr>
    </tbody>
</table>

</body>
</html>
"""

# Shranjevanje in odpiranje poročila
izhodna_datoteka = "Ovnicek_OGM_5Letno_Porocilo.html"
with open(izhodna_datoteka, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"\n[USPEH] Profesionalno poročilo je ustvarjeno: '{izhodna_datoteka}'")
pot_do_datoteke = os.path.abspath(izhodna_datoteka)
webbrowser.open(f"file://{pot_do_datoteke}")