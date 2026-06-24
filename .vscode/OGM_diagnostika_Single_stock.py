import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

print("=========================================================")
print("🔍 OGM DIAGNOSTIKA: ZAKAJ DELNICA NI NA SEZNAMU?")
print("=========================================================")

# Strategijski filtri iz glavnega radarja
MIN_MARKET_CAP = 20_000_000_000
MIN_REVENUE_GROWTH = 0.10

def formatiraj_mcap(mcap):
    if mcap == 0 or pd.isna(mcap) or mcap is None: return "N/A"
    if mcap >= 1e12: return f"${mcap/1e12:.2f}T"
    if mcap >= 1e9: return f"${mcap/1e9:.2f}B"
    if mcap >= 1e6: return f"${mcap/1e6:.2f}M"
    return f"${mcap}"

def diagnosticiraj_delnico():
    ticker = input("\nVpiši tiker delnice za analizo (npr. SAP.DE, TSLA, AAPL): ").strip().upper()
    print(f"\nPridobivam žive podatke za {ticker}... Prosim počakaj.\n")
    print("-" * 50)
    
    delnica = yf.Ticker(ticker)
    razlogi_za_zavrnitev = []
    
    # 1. OSNOVNI PODATKI IN FUNDAMENTI
    try:
        info = delnica.info
        mcap = info.get('marketCap', None)
        rev_growth = info.get('revenueGrowth', None)
        ime = info.get('shortName') or info.get('longName') or ticker
    except Exception as e:
        print(f"❌ KRITIČNA NAPAKA: Ni mogoče pridobiti osnovnih podatkov z Yahoo Finance ({e}).")
        return

    print(f"🏢 PODJETJE: {ime} ({ticker})")
    
    # Preverjanje Market Cap
    mcap_val = 0 if mcap is None else float(mcap)
    mcap_str = formatiraj_mcap(mcap_val)
    if mcap_val >= MIN_MARKET_CAP:
        print(f"✅ MARKET CAP: {mcap_str} (Ustreza pogoju > 20B $)")
    else:
        print(f"❌ MARKET CAP: {mcap_str} (PREMAJHNO! Zahtevano je > 20B $)")
        razlogi_za_zavrnitev.append("Premajhna tržna kapitalizacija (Market Cap).")

    # Preverjanje Revenue Growth
    rev_growth_val = 0.0 if rev_growth is None else float(rev_growth)
    if rev_growth_val >= MIN_REVENUE_GROWTH:
        print(f"✅ RAST PRIHODKOV: {rev_growth_val*100:.1f} % (Ustreza pogoju > 10 %)")
    else:
        print(f"❌ RAST PRIHODKOV: {rev_growth_val*100:.1f} % (PRENIZKO! Zahtevano je > 10 %)")
        razlogi_za_zavrnitev.append("Pričakovana rast prihodkov je pod 10 % (ali pa podatka ni).")

    # 2. TEHNIČNI PODATKI (Zgodovina)
    data = delnica.history(start="2014-01-01", interval="1wk", actions=False)
    if data is None or data.empty or len(data) < 205:
        print(f"❌ ZGODOVINA: Podjetje nima dovolj dolge zgodovine na borzi (zahtevano 205 tednov, ima {len(data) if data is not None else 0}).")
        razlogi_za_zavrnitev.append("Ni dovolj dolge zgodovine za izračun 200-tedenskega povprečja.")
        izpisi_zakljucek(razlogi_za_zavrnitev)
        return
    else:
        print(f"✅ ZGODOVINA: Na voljo je dovolj podatkov ({len(data)} tednov).")

    # 3. OGM IZRAČUN
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    close_series = data['Close'].dropna()
    
    ma200 = close_series.rolling(window=200).mean()
    ma20 = close_series.rolling(window=4).mean() # 4 tedne = 20 dni
    
    zadnji_ma200 = float(ma200.iloc[-1])
    zadnji_ma20 = float(ma20.iloc[-1])
    trenutna_cena = float(close_series.iloc[-1])
    
    pct_ma = ((close_series - ma200) / ma200) * 100
    delta = close_series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    tocke_ma = np.zeros_like(pct_ma.values)
    pos_mask = pct_ma.values >= 0
    neg_mask = pct_ma.values < 0
    tocke_ma[pos_mask] = np.interp(pct_ma.values[pos_mask], [0, 2, 10, 25, 50], [33.0, 35.0, 22.0, 8.0, 0.0])
    tocke_ma[neg_mask] = np.interp(pct_ma.values[neg_mask], [-20, -10, -5, 0], [0.0, 12.0, 25.0, 33.0])
    tocke_rsi = np.interp(rsi.values, [30, 45, 60, 70, 80], [10.0, 8.0, 5.0, 2.0, 0.0])
    ogm = np.clip(tocke_ma + tocke_rsi + 45.0, 0, 100)
    
    trenutni_ogm = float(ogm[-1])
    trend_ok = (trenutna_cena >= zadnji_ma200)
    is_falling_phase = (zadnji_ma20 < zadnji_ma200)
    
    if trenutni_ogm >= 65.0:
        print(f"✅ OGM SCORE: {trenutni_ogm:.1f} / 100 (Ustreza minimumu 65 točk)")
    else:
        print(f"❌ OGM SCORE: {trenutni_ogm:.1f} / 100 (PRENIZKO! Zahtevano je vsaj 65 točk)")
        razlogi_za_zavrnitev.append(f"Tehnični OGM Score ({trenutni_ogm:.1f}) je pod mejo 65 točk.")
        
    print("-" * 50)
    print("📊 TEHNIČNI TRENDI:")
    print(f"   - Trenutna cena: ${trenutna_cena:.2f}")
    print(f"   - 20-Day MA (Kratkoročni trend): ${zadnji_ma20:.2f}")
    print(f"   - 200-Week MA (Dolgoročni trend): ${zadnji_ma200:.2f}")
    
    if is_falling_phase:
        print("   ⚠️ OPOZORILO: Delnica je v fazi padanja (20-day MA je pod 200-week MA).")
    if not trend_ok:
        print("   ⚠️ OPOZORILO: Cena je prebila dolgoročno 200-tedensko podporo.")

    izpisi_zakljucek(razlogi_za_zavrnitev)

def izpisi_zakljucek(razlogi):
    print("=========================================================")
    print("📝 ZAKLJUČEK DIAGNOSTIKE:")
    if len(razlogi) == 0:
        print("✨ Delnica IZPOLNJUJE VSE POGOJE in SE NAHAJA na tvojem glavnem seznamu!")
    else:
        print("🛑 Delnica NI NA SEZNAMU zaradi naslednjih razlogov:")
        for i, razlog in enumerate(razlogi, 1):
            print(f"   {i}. {razlog}")
    print("=========================================================\n")

if __name__ == "__main__":
    while True:
        diagnosticiraj_delnico()
        se_eno = input("Želiš analizirati še eno delnico? (D/N): ").strip().upper()
        if se_eno != 'D':
            print("Zaključujem diagnostiko. Lep dan!")
            break