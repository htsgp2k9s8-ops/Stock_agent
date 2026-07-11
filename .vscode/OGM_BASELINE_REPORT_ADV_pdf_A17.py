import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime
import webbrowser
import os
import json

print("=========================================================")
print("AI OGM LIVE DASHBOARD - MASTER VALUE-GROWTH SKENER (MOAT V3)")
print("=========================================================")

CSV_DATOTEKA = "moje_globalne_delnice.csv"

# ==============================================================================
# STRATEŠKI INSTITUCIONALNI FILTRI
# ==============================================================================
MIN_MARKET_CAP = 20_000_000_000
MEGA_CAP_THRESHOLD = 200_000_000_000
MIN_REVENUE_GROWTH = 0.1
SUPER_GROWTH_THRESHOLD = 0.50

SECTOR_ETF_MAP = {
    "Technology":            "XLK",
    "Financial Services":    "XLF",
    "Communication Services":"XLC",
    "Consumer Cyclical":     "XLY",
    "Consumer Defensive":    "XLP",
    "Healthcare":            "XLV",
    "Energy":                "XLE",
    "Utilities":             "XLU",
    "Real Estate":           "XLRE",
    "Basic Materials":       "XLB",
    "Industrials":           "XLI",
}

def berem_sektor_podatke():
    """Downloads sector ETF data and returns performance metrics for each sector."""
    print("[INFO] Nalagam sektorske ETF podatke...")
    etfs = list(SECTOR_ETF_MAP.values())
    try:
        raw_data = yf.download(etfs, period="13mo", interval="1wk", progress=False)
        if isinstance(raw_data.columns, pd.MultiIndex):
            data = raw_data['Close']
        else:
            data = raw_data
    except Exception as e:
        print(f"[OPOZORILO] Sektorski ETF prenos ni uspel: {e}")
        return {}

    sektor_data = {}
    leto = datetime.now().year

    for sektor, etf in SECTOR_ETF_MAP.items():
        try:
            col = etf if etf in data.columns else None
            if col is None:
                continue
            prices = data[col].dropna()
            if len(prices) < 10:
                continue

            cena = float(prices.iloc[-1])
            d_1m  = float((prices.iloc[-1] / prices.iloc[-5]  - 1) * 100) if len(prices) >= 5  else 0.0
            d_3m  = float((prices.iloc[-1] / prices.iloc[-14] - 1) * 100) if len(prices) >= 14 else 0.0
            d_1y  = float((prices.iloc[-1] / prices.iloc[-53] - 1) * 100) if len(prices) >= 53 else 0.0

            ytd_prices = prices[prices.index.year == leto]
            d_ytd = float((prices.iloc[-1] / ytd_prices.iloc[0] - 1) * 100) if len(ytd_prices) > 0 else 0.0

            delta = prices.diff()
            gain  = delta.where(delta > 0, 0).rolling(14).mean()
            loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs    = gain / loss
            rsi_s = 100 - (100 / (1 + rs))
            rsi   = float(rsi_s.iloc[-1]) if not pd.isna(rsi_s.iloc[-1]) else 50.0

            sektor_data[sektor] = {
                "etf":       etf,
                "cena":      round(cena, 2),
                "donos_1m":  round(d_1m,  1),
                "donos_3m":  round(d_3m,  1),
                "donos_ytd": round(d_ytd, 1),
                "donos_1y":  round(d_1y,  1),
                "rsi":       round(rsi,   1),
            }
        except Exception:
            continue

    print(f"[INFO] Sektorski podatki naloženi za {len(sektor_data)} sektorjev.")
    return sektor_data


def formatiraj_mcap(mcap):
    if mcap == 0 or pd.isna(mcap) or mcap is None: return "N/A"
    if mcap >= 1e12: return f"${mcap/1e12:.2f}T"
    if mcap >= 1e9: return f"${mcap/1e9:.2f}B"
    if mcap >= 1e6: return f"${mcap/1e6:.2f}M"
    return f"${mcap}"

def safe_float(val, default=0.0):
    try:
        if val is None or pd.isna(val):
            return default
        return float(val)
    except:
        return default

if not os.path.exists(CSV_DATOTEKA):
    print(f"[NAPAKA] Datoteka '{CSV_DATOTEKA}' ne obstaja! Najprej zaženi Korak 1.")
    os._exit(0)

df_baza = pd.read_csv(CSV_DATOTEKA)
tickerji_v_obdelavi = df_baza['Ticker'].dropna().astype(str).str.strip().tolist()

strong_buy_podatki_za_graf = {}

# ==============================================================================
# 2. ŽIVI SKENER
# ==============================================================================
def skeniraj_trg():
    print(f"\n[START] Začenjam skeniranje za {len(tickerji_v_obdelavi)} delnic...")
    print("        -> Filtri kakovosti aktivirani.")
    print("        -> V3 Mega-Cap & High-Margin Moat pravila AKTIVIRANA.")
    print("---------------------------------------------------------")

    trenutno_leto = datetime.now().year
    rezultati = []

    for krog, ticker in enumerate(tickerji_v_obdelavi, 1):
        if krog % 20 == 0:
            print(f"    ... obdelano {krog} / {len(tickerji_v_obdelavi)} delnic ...")

        try:
            delnica = yf.Ticker(ticker)

            try:
                info_podatki = delnica.info
                mcap = info_podatki.get('marketCap')
                rev_growth = info_podatki.get('revenueGrowth')
                ime_podjetja = info_podatki.get('shortName') or info_podatki.get('longName') or ticker

                sektor = info_podatki.get('sector', 'Neznano')
                target_price = safe_float(info_podatki.get('targetMeanPrice'))
                if target_price == 0.0:
                    target_price = safe_float(info_podatki.get('targetMedianPrice'))

                pe_ratio = safe_float(info_podatki.get('trailingPE'))
                if pe_ratio == 0.0:
                    pe_ratio = safe_float(info_podatki.get('forwardPE'))

                eps_growth = info_podatki.get('earningsQuarterlyGrowth') or info_podatki.get('earningsGrowth')
                peg_ratio = info_podatki.get('pegRatio')
                gross_margin = info_podatki.get('grossMargins')

            except Exception as e:
                print(f"    [!] Yahoo API blokada pri {ticker}. Hladim (1s)...")
                time.sleep(1)
                continue

            if mcap is None or pd.isna(mcap) or mcap < MIN_MARKET_CAP:
                continue

            rev_growth_val = safe_float(rev_growth)
            mcap_prikaz = formatiraj_mcap(mcap)
            is_mega_cap = mcap >= MEGA_CAP_THRESHOLD

            data = delnica.history(start="2010-01-01", interval="1wk", actions=False)
            if data is None or data.empty or len(data) < 205:
                continue

            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            close_series = data['Close'].dropna()
            if close_series.empty or len(close_series) < 205:
                continue

            # ==================================================================
            # ŽIVA FUNDAMENTALNA INTERPOLACIJA (Max 45 Točk Skupaj)
            # ==================================================================
            eps_growth_pct = safe_float(eps_growth) * 100
            gross_margin_pct = safe_float(gross_margin) * 100
            peg_ratio_val = safe_float(peg_ratio, default=2.0)
            if peg_ratio_val == 0.0: peg_ratio_val = 2.0

            is_high_margin_moat = (not is_mega_cap) and (gross_margin_pct >= 50.0)

            tocke_eps = np.interp(eps_growth_pct, [0.0, 8.0, 16.5, 22.0, 30.0], [0.0, 5.0, 14.0, 20.0, 20.0])
            tocke_peg = np.interp(peg_ratio_val, [0.4, 0.8, 1.2, 1.6, 2.0], [15.0, 13.0, 10.0, 5.0, 0.0])
            tocke_margin = np.interp(gross_margin_pct, [25, 35, 45, 55, 65], [0.0, 2.0, 5.0, 8.0, 10.0])

            base_fundament_score = min(45.0, tocke_eps + tocke_peg + tocke_margin)

            # ==================================================================
            # TEHNIČNI TAJMING (Max 55 Točk Skupaj)
            # ==================================================================
            ma200 = close_series.rolling(window=200).mean()
            ma50 = close_series.rolling(window=50).mean()
            ma20 = close_series.rolling(window=4).mean()

            ma_target = ma50 if is_mega_cap else ma200
            tip_ma = "50w MA (Mega-Cap)" if is_mega_cap else ("200w MA (Moat)" if is_high_margin_moat else "200w MA")

            zadnji_ma_target = float(ma_target.iloc[-1])
            zadnji_ma20_weekly = float(ma20.iloc[-1])

            if zadnji_ma_target == 0 or pd.isna(zadnji_ma_target): continue

            pct_ma = ((close_series - ma_target) / ma_target) * 100

            delta = close_series.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))

            oddaljenost_arr = pct_ma.values
            rsi_arr = rsi.values

            tocke_ma = np.zeros_like(oddaljenost_arr)
            pos_mask = oddaljenost_arr >= 0
            neg_mask = oddaljenost_arr < 0

            W_MA = 40.0
            W_RSI = 15.0

            if is_mega_cap:
                tocke_ma[pos_mask] = np.interp(oddaljenost_arr[pos_mask], [0, 2, 8, 15], [W_MA*(32/35), W_MA, W_MA*(15/35), 0.0])
                tocke_ma[neg_mask] = np.interp(oddaljenost_arr[neg_mask], [-40, -15, -2, 0], [W_MA, W_MA, W_MA*(34/35), W_MA*(32/35)])
            elif is_high_margin_moat:
                tocke_ma[pos_mask] = np.interp(oddaljenost_arr[pos_mask], [0, 2, 10, 25, 50], [W_MA*(33/35), W_MA, W_MA*(22/35), W_MA*(8/35), 0.0])
                tocke_ma[neg_mask] = np.interp(oddaljenost_arr[neg_mask], [-35, -20, -15, -5, 0], [0.0, 35.0, 40.0, 38.0, W_MA*(33/35)])
            else:
                tocke_ma[pos_mask] = np.interp(oddaljenost_arr[pos_mask], [0, 2, 10, 25, 50], [W_MA*(33/35), W_MA, W_MA*(22/35), W_MA*(8/35), 0.0])
                tocke_ma[neg_mask] = np.interp(oddaljenost_arr[neg_mask], [-20, -10, -5, 0], [0.0, W_MA*(12/35), W_MA*(25/35), W_MA*(33/35)])

            tocke_rsi = np.interp(rsi_arr, [30, 45, 60, 70, 80], [W_RSI, W_RSI*0.8, W_RSI*0.5, W_RSI*0.2, 0.0])

            ogm_zgodovina = np.clip(tocke_ma + tocke_rsi + base_fundament_score, 0, 100.0)

            trenutna_cena = float(close_series.iloc[-1])
            oddaljenost_ma_trenutna = float(oddaljenost_arr[-1])
            trenutni_ogm = min(100.0, float(ogm_zgodovina[-1]))

            if pd.isna(oddaljenost_ma_trenutna) or pd.isna(trenutni_ogm):
                continue

            # Glavni Filter
            if trenutni_ogm < 65.0 or rev_growth_val < MIN_REVENUE_GROWTH:
                continue

            # ==================================================================
            # IZRACUN SEZONSKOSTI IN TRENDOV
            # ==================================================================
            close_series.index = pd.to_datetime(close_series.index)

            monthly_prices = close_series.groupby([close_series.index.year, close_series.index.month]).last()
            monthly_returns = monthly_prices.pct_change() * 100

            yearly_prices = close_series.groupby(close_series.index.year).last()
            yearly_returns = yearly_prices.pct_change() * 100

            yearly_data = [{"leto": int(y), "donos": float(val)} for y, val in yearly_returns.dropna().items()]
            monthly_data = {}
            for (y, m), val in monthly_returns.dropna().items():
                y, m = int(y), int(m)
                if y not in monthly_data: monthly_data[y] = {}
                monthly_data[y][m] = float(val)

            trend_ok = oddaljenost_ma_trenutna >= 0
            is_falling_phase = zadnji_ma20_weekly < zadnji_ma_target
            donos_1m = ((trenutna_cena - float(close_series.iloc[-5])) / float(close_series.iloc[-5])) * 100

            vsi_datumi = close_series.index
            datumi_trenutnega_leta = vsi_datumi[vsi_datumi.year == trenutno_leto]
            try:
                if len(datumi_trenutnega_leta) > 0: cena_zacetek_leta = float(close_series.loc[datumi_trenutnega_leta[0]])
                else: cena_zacetek_leta = float(close_series.iloc[-22])
                donos_ytd = ((trenutna_cena - cena_zacetek_leta) / cena_zacetek_leta) * 100
            except Exception: donos_ytd = 0.0

            if trenutni_ogm >= 80.0: status = "STRONG BUY"
            elif is_falling_phase: status = "WARNING (FALLING PHASE)"
            elif not trend_ok: status = "WARNING (POD MA)"
            elif rev_growth_val >= SUPER_GROWTH_THRESHOLD: status = "SUPER-GROWTH TARGET"
            else: status = "BUY"

            datumi_str = [d.strftime("%Y-%m-%d") for d in close_series.index]
            zgodovina_tabela = []
            zadnji_indeks_signala = -999

            for i in range(len(ogm_zgodovina)):
                if ogm_zgodovina[i] >= 80.0 and (i - zadnji_indeks_signala) > 26:
                    cena_ob_signalu = close_series.iloc[i]
                    if i + 52 < len(close_series): max_cena_12m = close_series.iloc[i:i+52].max()
                    else: max_cena_12m = close_series.iloc[i:].max() if i + 1 < len(close_series) else cena_ob_signalu
                    donos = ((max_cena_12m - cena_ob_signalu) / cena_ob_signalu) * 100
                    if i + 52 < len(close_series): min_cena_12m = close_series.iloc[i:i+52].min()
                    else: min_cena_12m = close_series.iloc[i:].min() if i + 1 < len(close_series) else cena_ob_signalu
                    izguba = ((min_cena_12m - cena_ob_signalu) / cena_ob_signalu) * 100
                    if i + 52 < len(close_series):
                        zgodovina_tabela.append({"datum": datumi_str[i], "cena": round(cena_ob_signalu, 2), "max_cena": round(max_cena_12m, 2), "max_donos": round(donos, 1), "min_cena": round(min_cena_12m, 2), "max_izguba": round(izguba, 1)})
                    zadnji_indeks_signala = i

            ma50_list = [0.0 if pd.isna(v) else round(float(v), 2) for v in ma50.values]
            ma200_list = [0.0 if pd.isna(v) else round(float(v), 2) for v in ma200.values]
            vol_buy = [int(data['Volume'].iloc[i]) if data['Close'].iloc[i] >= data['Open'].iloc[i] else 0 for i in range(len(data))]
            vol_sell = [int(data['Volume'].iloc[i]) if data['Close'].iloc[i] < data['Open'].iloc[i] else 0 for i in range(len(data))]

            strong_buy_podatki_za_graf[ticker] = {
                "ime": ime_podjetja,
                "cena": round(trenutna_cena, 2),
                "donos_1m": round(donos_1m, 2),
                "donos_ytd": round(donos_ytd, 2),
                "status": status,
                "mcap": mcap_prikaz,
                "rev_growth": round(rev_growth_val * 100, 1),
                "target_price": round(target_price, 2) if target_price > 0 else 0,
                "sektor": sektor,
                "dates": datumi_str,
                "prices": np.round(close_series.values, 2).tolist(),
                "ma50": ma50_list,
                "ma200": ma200_list,
                "volume_buy": vol_buy,
                "volume_sell": vol_sell,
                "ogm": np.round(ogm_zgodovina, 1).tolist(),
                "history": zgodovina_tabela,
                "yearly": yearly_data[-10:],
                "monthly": monthly_data,
                "components": {
                    "eps_growth_raw": eps_growth_pct, "eps_growth_score": float(tocke_eps),
                    "peg_raw": peg_ratio_val, "peg_score": float(tocke_peg),
                    "pe_raw": pe_ratio,
                    "margin_raw": gross_margin_pct, "margin_score": float(tocke_margin),
                    "rsi_raw": float(rsi_arr[-1]), "rsi_score": float(tocke_rsi[-1]),
                    "ma_dist_raw": oddaljenost_ma_trenutna, "ma_dist_score": float(tocke_ma[-1]),
                    "total_score": float(trenutni_ogm),
                    "ma_type": tip_ma
                }
            }

            rezultati.append({
                "Ticker": ticker, "Ime": ime_podjetja, "Sektor": sektor, "TargetPrice": target_price,
                "Cena": trenutna_cena, "OGM": trenutni_ogm,
                "Status": status, "1M_Donos": donos_1m, "YTD_Donos": donos_ytd,
                "MarketCap": mcap_prikaz, "Mcap_Raw": mcap, "RevGrowth": rev_growth_val * 100,
                "Dist200w": oddaljenost_ma_trenutna,
                "MaType": tip_ma
            })

            time.sleep(0.04)
        except Exception as e:
            continue

    sektor_primerjava = berem_sektor_podatke()
    generiraj_html_porocilo(rezultati, sektor_primerjava)

# ==============================================================================
# 3. HTML GENERATOR POROČILA
# ==============================================================================
def generiraj_html_porocilo(podatki, sektor_primerjava=None):
    df_html = pd.DataFrame(podatki)
    if not df_html.empty:
        df_html = df_html.sort_values(by=["OGM"], ascending=[False])

    datum_danes = datetime.now().strftime("%d.%m.%Y")
    graf_json = json.dumps(strong_buy_podatki_za_graf)
    sektor_json = json.dumps(sektor_primerjava or {})

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>OGM Živi Radar</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@1.2.1/dist/chartjs-plugin-zoom.min.js"></script>
<style>
/* ── MAIN PAGE ── */
html {{ overflow-x: hidden; }}
body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #cbd5e1; background-color: #060d1a; margin: 0; padding: 22px 12px 50px; min-height: 100vh; }}
.page-wrap {{ max-width: 1480px; margin: 0 auto; }}
.header {{ background: linear-gradient(135deg, #0c1628 0%, #112244 55%, #1d4ed8 100%); color: #fff; padding: 26px 30px; border-radius: 12px; border: 1px solid rgba(255,255,255,.07); box-shadow: 0 8px 40px rgba(0,0,0,.55); }}
.header h1 {{ margin: 0; font-size: 22pt; font-weight: 800; letter-spacing: .3px; }}
.header p {{ margin: 5px 0 0 0; color: #bfdbfe; font-size: 10.5pt; }}
.table-wrap {{ margin-top: 18px; border-radius: 12px; overflow-x: auto; border: 1px solid rgba(255,255,255,.06); box-shadow: 0 4px 28px rgba(0,0,0,.45); }}
table {{ width: 100%; border-collapse: collapse; background: transparent; table-layout: auto; }}
th {{ background: #09152a; color: #475569; text-align: left; padding: 10px 8px; font-size: 7.5pt; font-weight: 700; text-transform: uppercase; letter-spacing: .8px; border-bottom: 1px solid rgba(255,255,255,.06); white-space: nowrap; }}
td {{ padding: 11px 8px; border-bottom: 1px solid rgba(255,255,255,.035); font-size: 9.5pt; background: #0b1526; color: #94a3b8; vertical-align: middle; }}
tr:nth-child(even) td {{ background: #0e1d32; }}
tr:hover td {{ background: #152338 !important; transition: background .08s; }}
.badge {{ padding: 4px 11px; border-radius: 20px; font-weight: 700; font-size: 8pt; display: inline-block; white-space: nowrap; }}
.super-growth {{ background: #2d004a; color: #e879f9; border: 1.5px solid #a855f7; }}
.strong-buy {{ background: #052e16; color: #4ade80; border: 1.5px solid #16a34a; }}
.buy {{ background: #0c1a3a; color: #60a5fa; border: 1.5px solid #2563eb; }}
.warning-falling {{ background: #2d0f00; color: #fb923c; border: 1.5px solid #ea580c; }}
.warning-ma {{ background: #2d0505; color: #f87171; border: 1.5px solid #ef4444; }}
.pos-return {{ color: #4ade80; font-weight: 700; }}
.neg-return {{ color: #f87171; font-weight: 700; }}
.mcap-text {{ color: #64748b; font-weight: 600; font-size: 9pt; }}
.growth-text {{ font-weight: 700; color: #60a5fa; }}
.dist-green {{ color: #4ade80; background: rgba(74,222,128,.1); font-weight: 700; padding: 3px 8px; border-radius: 5px; border: 1px solid rgba(74,222,128,.2); white-space: nowrap; }}
.dist-orange {{ color: #f87171; background: rgba(248,113,113,.1); font-weight: 700; padding: 3px 8px; border-radius: 5px; border: 1px solid rgba(248,113,113,.2); white-space: nowrap; }}
.dist-normal {{ color: #64748b; font-weight: 500; }}
.ticker-btn {{ background: #0c1a3a; border: 1.5px solid #1e3a8a; color: #60a5fa; padding: 7px 13px; border-radius: 7px; font-weight: 800; font-size: 11pt; cursor: pointer; transition: all .15s; font-family: 'Segoe UI', Arial, sans-serif; white-space: nowrap; display: inline-flex; align-items: center; gap: 5px; }}
.ticker-btn:hover {{ background: #1e3a8a; color: #f1f5f9; border-color: #3b82f6; transform: translateY(-1px); box-shadow: 0 4px 14px rgba(59,130,246,.3); }}
.ogm-cell {{ display: flex; align-items: center; gap: 8px; white-space: nowrap; }}
.ogm-num {{ color: #f1f5f9; font-weight: 800; font-size: 11pt; min-width: 36px; }}
.ogm-bar-bg {{ width: 44px; height: 5px; background: #1e293b; border-radius: 3px; overflow: hidden; }}
.ogm-bar-fill {{ height: 100%; border-radius: 3px; background: linear-gradient(90deg, #2563eb, #38bdf8); }}
.ogm-max {{ color: #334155; font-size: 8pt; }}
.rank-num {{ color: #334155; font-weight: 700; font-size: 10.5pt; }}
.cena-cell {{ color: #f1f5f9; font-weight: 700; }}
.tp-cell {{ color: #64748b; font-weight: 600; }}
.sektor-cell {{ color: #475569; font-size: 8.5pt; }}
.ime-podjetja {{ max-width: 170px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #475569; font-size: 8.5pt; }}

/* ── DARK MODAL ── */
.modal {{ display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; overflow: hidden; background: rgba(0,0,0,.80); backdrop-filter: blur(6px); }}
.modal-content {{ background: #0b1526; margin: 1.5% auto; border-radius: 14px; width: 93%; max-width: 1160px; box-shadow: 0 28px 90px rgba(0,0,0,.65); position: relative; max-height: 94vh; overflow: hidden; display: flex; flex-direction: column; color: #f8fafc; border: 1px solid rgba(255,255,255,.07); }}

/* Hero */
.modal-hero {{ background: linear-gradient(135deg, #0c1628 0%, #112040 60%, #1a3560 100%); padding: 20px 28px 16px; border-bottom: 1px solid rgba(255,255,255,.07); flex-shrink: 0; display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; position: relative; }}
.hero-close {{ position: absolute; right: 14px; top: 12px; background: none; border: none; color: #475569; font-size: 20pt; cursor: pointer; padding: 2px 8px; border-radius: 6px; line-height: 1; transition: .15s; }}
.hero-close:hover {{ color: #f1f5f9; background: rgba(255,255,255,.1); }}
.hero-left {{ flex: 1; }}
.hero-ticker-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 4px; flex-wrap: wrap; }}
.hero-rank {{ color: #475569; font-size: 12pt; font-weight: 600; }}
.hero-ticker {{ color: #fff; font-size: 28pt; font-weight: 900; letter-spacing: 2px; line-height: 1; }}
.hero-company {{ color: #94a3b8; font-size: 10.5pt; margin-bottom: 7px; }}
.hero-meta {{ display: flex; gap: 8px; align-items: center; color: #475569; font-size: 8.5pt; flex-wrap: wrap; }}
.hero-meta-dot {{ color: #334155; }}
.hero-right {{ text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 9px; padding-right: 40px; }}
.hero-price {{ color: #f1f5f9; font-size: 28pt; font-weight: 700; line-height: 1; }}
.hero-returns {{ display: flex; gap: 14px; }}
.hero-ret-lbl {{ color: #475569; font-size: 7.5pt; margin-right: 2px; }}
.hero-ret-pos {{ color: #4ade80; font-weight: 700; font-size: 9.5pt; }}
.hero-ret-neg {{ color: #f87171; font-weight: 700; font-size: 9.5pt; }}
.conf-wrap {{ display: flex; align-items: center; gap: 12px; }}
.conf-bar-outer {{ width: 110px; }}
.conf-bar-lbl {{ color: #475569; font-size: 7.5pt; margin-bottom: 4px; }}
.conf-bar-bg {{ height: 7px; background: #1e293b; border-radius: 4px; overflow: hidden; }}
.conf-bar-fill {{ height: 100%; background: linear-gradient(90deg, #22c55e, #86efac); border-radius: 4px; transition: width .5s ease; }}
.conf-pct {{ color: #4ade80; font-size: 14pt; font-weight: 700; min-width: 50px; text-align: center; }}
.conf-badge {{ background: #0c1f45; border: 2px solid #2563eb; border-radius: 10px; padding: 8px 14px; text-align: center; min-width: 72px; }}
.conf-badge-lbl {{ color: #60a5fa; font-size: 6.5pt; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; }}
.conf-badge-score {{ color: #fff; font-size: 22pt; font-weight: 900; line-height: 1; }}
.conf-badge-max {{ color: #475569; font-size: 8pt; }}

/* Status pill variants */
.status-sb {{ background: #052e16; color: #4ade80; border: 1.5px solid #16a34a; padding: 4px 12px; border-radius: 20px; font-size: 8.5pt; font-weight: 700; }}
.status-buy {{ background: #0c1a3a; color: #60a5fa; border: 1.5px solid #2563eb; padding: 4px 12px; border-radius: 20px; font-size: 8.5pt; font-weight: 700; }}
.status-sg {{ background: #2d004a; color: #e879f9; border: 1.5px solid #a855f7; padding: 4px 12px; border-radius: 20px; font-size: 8.5pt; font-weight: 700; }}
.status-warn {{ background: #2d0f00; color: #fb923c; border: 1.5px solid #ea580c; padding: 4px 12px; border-radius: 20px; font-size: 8.5pt; font-weight: 700; }}

/* Metrics strip */
.modal-metrics {{ background: #070e1c; border-bottom: 1px solid rgba(255,255,255,.05); padding: 8px 28px; display: flex; gap: 0; overflow-x: auto; flex-shrink: 0; scrollbar-width: none; }}
.modal-metrics::-webkit-scrollbar {{ display: none; }}
.mbar-item {{ padding: 5px 18px; border-right: 1px solid rgba(255,255,255,.05); text-align: center; flex: 1; min-width: 90px; }}
.mbar-item:last-child {{ border-right: none; }}
.mbar-lbl {{ color: #334155; font-size: 6.5pt; text-transform: uppercase; letter-spacing: .5px; margin-bottom: 3px; }}
.mbar-val {{ font-size: 10pt; font-weight: 700; }}
.mv-pos {{ color: #4ade80; }}
.mv-neg {{ color: #f87171; }}
.mv-neu {{ color: #94a3b8; }}
.mv-blue {{ color: #60a5fa; }}
.mv-purp {{ color: #c084fc; }}

/* Tab navigation */
.modal-tab-bar {{ background: #070e1c; border-bottom: 1px solid rgba(255,255,255,.05); padding: 0 20px; display: flex; gap: 0; overflow-x: auto; flex-shrink: 0; scrollbar-width: none; }}
.modal-tab-bar::-webkit-scrollbar {{ display: none; }}
.tab-btn {{ background: none; border: none; border-bottom: 3px solid transparent; color: #334155; padding: 11px 14px; font-size: 9pt; font-weight: 600; cursor: pointer; white-space: nowrap; transition: all .15s; margin-bottom: -1px; font-family: 'Segoe UI', Arial, sans-serif; }}
.tab-btn:hover:not(.tab-soon) {{ color: #64748b; border-bottom-color: rgba(59,130,246,.3); }}
.tab-btn.active {{ color: #f1f5f9; border-bottom-color: #3b82f6; }}
.tab-btn.tab-soon {{ color: #1e293b; cursor: default; font-style: italic; }}
.tab-btn.tab-soon:hover {{ color: #334155; border-bottom-color: transparent; }}
/* ── SEKTOR TAB ── */
.sec-hero {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; padding: 16px 20px; background: #0e1d32; border-radius: 10px; border: 1px solid rgba(255,255,255,.06); }}
.sec-name {{ font-size: 15pt; font-weight: 800; color: #f1f5f9; }}
.sec-sub  {{ font-size: 8.5pt; color: #475569; margin-top: 4px; }}
.trend-bull {{ background: #052e16; color: #4ade80; border: 1.5px solid #16a34a; padding: 5px 15px; border-radius: 20px; font-weight: 700; font-size: 8.5pt; white-space: nowrap; }}
.trend-bear {{ background: #2d0505; color: #f87171; border: 1.5px solid #ef4444; padding: 5px 15px; border-radius: 20px; font-weight: 700; font-size: 8.5pt; white-space: nowrap; }}
.trend-neu  {{ background: #1a1f2e; color: #94a3b8; border: 1.5px solid #475569; padding: 5px 15px; border-radius: 20px; font-weight: 700; font-size: 8.5pt; white-space: nowrap; }}
.sec-metrics {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 20px; }}
.sec-met {{ background: #0e1d32; padding: 12px 8px; border-radius: 8px; border: 1px solid rgba(255,255,255,.05); text-align: center; }}
.sec-met-lbl {{ font-size: 7pt; color: #475569; text-transform: uppercase; letter-spacing: .7px; margin-bottom: 5px; }}
.sec-met-val {{ font-size: 13pt; font-weight: 800; color: #f1f5f9; }}
.sec-chart-wrap {{ background: #0b1526; border-radius: 10px; padding: 16px 18px; border: 1px solid rgba(255,255,255,.06); margin-bottom: 20px; }}
.sec-table {{ width: 100%; border-collapse: collapse; font-size: 9pt; }}
.sec-table th {{ background: #09152a; color: #475569; padding: 9px 10px; text-align: left; border-bottom: 1px solid rgba(255,255,255,.06); font-size: 7pt; text-transform: uppercase; letter-spacing: .7px; font-weight: 700; }}
.sec-table td {{ padding: 9px 10px; border-bottom: 1px solid rgba(255,255,255,.03); color: #94a3b8; }}
.sec-table tr.sec-row-active td {{ background: rgba(59,130,246,.08); }}
.sec-table tr:hover td {{ background: #152338 !important; }}

/* Tab panes */
.modal-body {{ overflow-y: auto; flex: 1; background: #0b1526; }}
.tab-pane {{ display: none; padding: 22px 28px 28px; min-height: 300px; }}
.tab-pane.active {{ display: block; }}
.chart-container {{ position: relative; height: 390px; width: 100%; }}
.tab-section-lbl {{ color: #475569; font-size: 8pt; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 16px; }}

/* Dark table — override global table/tr/td styles that bleed white into dark modal */
.dark-tbl {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; background: transparent !important; box-shadow: none !important; border: 1px solid #1e293b !important; }}
.dark-tbl th {{ background: #111d33 !important; color: #475569; padding: 10px 14px; text-align: left; font-size: 8pt; text-transform: uppercase; letter-spacing: .5px; border-bottom: 1px solid #1e293b; }}
.dark-tbl td {{ padding: 10px 14px; border-bottom: 1px solid #0d1526; color: #cbd5e1; background: #0b1526 !important; }}
.dark-tbl tr:nth-child(even) td {{ background: #0e1c30 !important; }}
.dark-tbl tr:hover td {{ background: #1a2d4a !important; }}
.dark-tbl .val-em {{ color: #f1f5f9; font-weight: 700; }}
.dark-tbl .total-row td {{ background: #0f2754 !important; color: #f1f5f9; font-weight: 700; font-size: 11pt; }}
/* Heatmap table — same fix */
.hm-tbl {{ background: transparent !important; box-shadow: none !important; }}
.hm-tbl td {{ background: transparent !important; }}
.hm-tbl tr:nth-child(even) td {{ background: transparent !important; }}
.hm-tbl tr:hover td {{ background: transparent !important; }}
.score-bar-wrap {{ display: flex; align-items: center; gap: 8px; }}
.score-bar-bg {{ flex: 1; height: 6px; background: #1e293b; border-radius: 3px; overflow: hidden; max-width: 100px; }}
.score-bar-fill {{ height: 100%; border-radius: 3px; background: linear-gradient(90deg,#3b82f6,#60a5fa); }}
/* Chart pan cursor */
.chart-container canvas {{ cursor: grab; }}
.chart-container canvas:active {{ cursor: grabbing; }}
.chart-reset-btn {{ position: absolute; top: 8px; right: 8px; background: #1e293b; color: #64748b; border: 1px solid #334155; padding: 4px 10px; border-radius: 4px; font-size: 8pt; cursor: pointer; z-index: 10; font-family: 'Segoe UI', Arial, sans-serif; transition: .15s; }}
.chart-reset-btn:hover {{ background: #334155; color: #94a3b8; }}

/* Yearly cards */
.yearly-flex {{ display: flex; flex-wrap: wrap; gap: 10px; }}
.yr-card {{ background: #111d33; border: 1px solid #1e293b; border-radius: 8px; padding: 12px 16px; text-align: center; min-width: 76px; transition: transform .15s; }}
.yr-card:hover {{ transform: translateY(-2px); }}
.yr-lbl {{ color: #475569; font-size: 8pt; margin-bottom: 5px; }}
.yr-val {{ font-size: 12pt; font-weight: 700; }}
.yr-pos {{ border-color: #166534; background: #041a0e; }}
.yr-neg {{ border-color: #7f1d1d; background: #150505; }}
.yr-pos .yr-val {{ color: #4ade80; }}
.yr-neg .yr-val {{ color: #f87171; }}

/* Heatmap */
.hm-tbl {{ width: 100%; border-collapse: collapse; font-size: 8pt; }}
.hm-tbl th {{ color: #334155; padding: 6px 4px; text-align: center; font-weight: 600; font-size: 7.5pt; border-bottom: 1px solid #1e293b; }}
.hm-tbl td {{ padding: 5px 4px; text-align: center; border-radius: 2px; font-weight: 500; }}
.hm-yr {{ color: #64748b; font-weight: 700; text-align: left; padding-left: 6px !important; }}

/* Coming soon */
.coming-soon {{ display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 70px 20px; }}
.cs-icon {{ font-size: 28pt; margin-bottom: 14px; color: #1e293b; }}
.cs-title {{ color: #334155; font-size: 13pt; font-weight: 700; margin-bottom: 6px; }}
.cs-sub {{ color: #1e293b; font-size: 9.5pt; }}

@media print {{
    body {{ background-color: #060d1a; margin: 0; padding: 10px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .btn-pdf, #navodilo-klik {{ display: none !important; }}
    .table-wrap {{ box-shadow: none; border: 1px solid rgba(255,255,255,.1); }}
    table {{ box-shadow: none; page-break-inside: auto; }}
    tr {{ page-break-inside: avoid; page-break-after: auto; }}
    thead {{ display: table-header-group; }}
    .modal {{ display: none !important; }}
}}
</style>
</head>
<body>
<div class="page-wrap">

<div class="header">
    <h1>OVNICEK GROWTH MATRIX &mdash; VALUE-GROWTH RADAR</h1>
    <p style="margin:6px 0 0; color:#93c5fd; font-size:9.5pt;">Osveženo: {datum_danes}</p>
</div>

<div class="table-wrap">
<table>
    <thead>
        <tr>
            <th>#</th>
            <th>Ticker</th>
            <th>Ime podjetja</th>
            <th>Sektor</th>
            <th>Market Cap</th>
            <th>Rast Prihodkov</th>
            <th>&#x394; MA</th>
            <th>Cena</th>
            <th>Ciljna Cena</th>
            <th>OGM</th>
            <th>Status</th>
            <th>1M</th>
            <th>YTD</th>
        </tr>
    </thead>
    <tbody>
"""

    if not df_html.empty:
        for rank, (_, row) in enumerate(df_html.iterrows(), 1):
            if row['Status'] == "SUPER-GROWTH TARGET": badge_class = "super-growth"
            elif row['Status'] == "STRONG BUY": badge_class = "strong-buy"
            elif row['Status'] == "BUY": badge_class = "buy"
            elif row['Status'] == "WARNING (FALLING PHASE)": badge_class = "warning-falling"
            else: badge_class = "warning-ma"

            dist_val = row['Dist200w']
            if 0.0 <= dist_val <= 5.0: dist_class = "dist-green"
            elif dist_val < 0.0: dist_class = "dist-orange"
            else: dist_class = "dist-normal"

            class_1m = "pos-return" if row['1M_Donos'] >= 0 else "neg-return"
            class_ytd = "pos-return" if row['YTD_Donos'] >= 0 else "neg-return"

            ticker_display = f'<button class="ticker-btn" onclick="openAnalysis(\'{row["Ticker"]}\', {rank})">&#x1F4CA; {row["Ticker"]}</button>'

            tp_display = f"${row['TargetPrice']:.2f}" if row['TargetPrice'] > 0 else "N/A"
            ogm_pct = min(row['OGM'], 100)
            ogm_display = f'<div class="ogm-cell"><span class="ogm-num">{row["OGM"]:.1f}</span><div class="ogm-bar-bg"><div class="ogm-bar-fill" style="width:{ogm_pct:.1f}%"></div></div><span class="ogm-max">/100</span></div>'

            html_content += f"""
            <tr>
                <td class="rank-num">#{rank}</td>
                <td>{ticker_display}</td>
                <td><div class="ime-podjetja" title="{row['Ime']}">{row['Ime']}</div></td>
                <td class="sektor-cell">{row['Sektor']}</td>
                <td class="mcap-text">{row['MarketCap']}</td>
                <td class="growth-text">{row['RevGrowth']:.1f} %</td>
                <td><span class="{dist_class}">{row['Dist200w']:+.1f} %</span><br><span style="font-size:7pt; color:#334155;">({row['MaType']})</span></td>
                <td class="cena-cell">${row['Cena']:.2f}</td>
                <td class="tp-cell">{tp_display}</td>
                <td>{ogm_display}</td>
                <td><span class="badge {badge_class}">{row['Status']}</span></td>
                <td class="{class_1m}">{row['1M_Donos']:+.1f} %</td>
                <td class="{class_ytd}">{row['YTD_Donos']:+.1f} %</td>
            </tr>
            """
    else:
        html_content += """<tr><td colspan="13" style="text-align:center; padding:30px; color:#94a3b8;">Trenutno ni delnic, ki ustrezajo kriterijem.</td></tr>"""

    html_content += f"""
    </tbody>
</table>
</div><!-- /table-wrap -->

</div><!-- /page-wrap -->

<!-- ═══════════════════════════════════════════════════════════════
     DARK ANALYSIS MODAL
═══════════════════════════════════════════════════════════════ -->
<div id="analysisModal" class="modal">
  <div class="modal-content">

    <!-- HERO HEADER -->
    <div class="modal-hero">
      <button class="hero-close" onclick="closeModal()">&#x2715;</button>
      <div class="hero-left">
        <div class="hero-ticker-row">
          <span class="hero-rank" id="heroRank">#1</span>
          <span class="hero-ticker" id="heroTicker">-</span>
          <span id="heroStatusBadge"></span>
        </div>
        <div class="hero-company" id="heroCompany">-</div>
        <div class="hero-meta">
          <span id="heroSector">-</span>
          <span class="hero-meta-dot">&bull;</span>
          <span id="heroMcap">-</span>
          <span class="hero-meta-dot">&bull;</span>
          <span id="heroRevGrowth">-</span>
        </div>
      </div>
      <div class="hero-right">
        <div class="hero-price" id="heroPrice">$-</div>
        <div class="hero-returns">
          <span id="hero1m"></span>
          <span id="heroYtd"></span>
        </div>
        <div class="conf-wrap">
          <div class="conf-bar-outer">
            <div class="conf-bar-lbl">OGM Verjetnost</div>
            <div class="conf-bar-bg"><div class="conf-bar-fill" id="heroConfBar" style="width:0%"></div></div>
          </div>
          <div class="conf-pct" id="heroConfPct">-</div>
          <div class="conf-badge">
            <div class="conf-badge-lbl">OGM</div>
            <div class="conf-badge-score" id="heroConfScore">-</div>
            <div class="conf-badge-max">/100</div>
          </div>
        </div>
      </div>
    </div>

    <!-- METRICS STRIP -->
    <div class="modal-metrics" id="modalMetrics"></div>

    <!-- TAB NAVIGATION -->
    <div class="modal-tab-bar">
      <button class="tab-btn active" id="tab-btn-summary" onclick="switchTab(this,'tab-summary')">Pregled</button>
      <button class="tab-btn" onclick="switchTab(this,'tab-ogm')">OGM Analiza</button>
      <button class="tab-btn" onclick="switchTab(this,'tab-yearly')">Letni Donosi</button>
      <button class="tab-btn" onclick="switchTab(this,'tab-seasonal')">Sezonskost</button>
      <button class="tab-btn" onclick="switchTab(this,'tab-signals')">Signali</button>
      <button class="tab-btn" onclick="switchTab(this,'tab-sector')">Sektor</button>
      <button class="tab-btn tab-soon" onclick="switchTab(this,'tab-soon')">Fundamentals</button>
      <button class="tab-btn tab-soon" onclick="switchTab(this,'tab-soon')">Earnings</button>
      <button class="tab-btn tab-soon" onclick="switchTab(this,'tab-soon')">Dividends</button>
      <button class="tab-btn tab-soon" onclick="switchTab(this,'tab-soon')">Valuation</button>
      <button class="tab-btn tab-soon" onclick="switchTab(this,'tab-soon')">Growth</button>
      <button class="tab-btn tab-soon" onclick="switchTab(this,'tab-soon')">Profitability</button>
      <button class="tab-btn tab-soon" onclick="switchTab(this,'tab-soon')">Momentum</button>
      <button class="tab-btn tab-soon" onclick="switchTab(this,'tab-soon')">Peers</button>
    </div>

    <!-- TAB PANES -->
    <div class="modal-body">

      <!-- PREGLED -->
      <div class="tab-pane active" id="tab-summary">
        <div class="tab-section-lbl">Graf cene &amp; OGM Score (tedenski) &nbsp;<span style="color:#334155; font-weight:400;">&#8212; scroll to zoom &bull; drag to pan &bull; dblclick to reset</span></div>
        <div class="chart-container" style="position:relative;">
          <canvas id="ogmChart"></canvas>
          <button class="chart-reset-btn" onclick="resetChartZoom()">&#x21BA; Reset Zoom</button>
        </div>
      </div>

      <!-- OGM ANALIZA -->
      <div class="tab-pane" id="tab-ogm">
        <div class="tab-section-lbl">Sestava OGM Koeficienta</div>
        <div id="componentsBody"></div>
      </div>

      <!-- LETNI DONOSI -->
      <div class="tab-pane" id="tab-yearly">
        <div class="tab-section-lbl">Letni Donosi &mdash; Zadnjih 10 let</div>
        <div id="yearlyBody"></div>
      </div>

      <!-- SEZONSKOST -->
      <div class="tab-pane" id="tab-seasonal">
        <div class="tab-section-lbl">Mesečna Sezonskost (Heatmap)</div>
        <div id="monthlyBody" style="overflow-x:auto;"></div>
      </div>

      <!-- SIGNALI -->
      <div class="tab-pane" id="tab-signals">
        <div class="tab-section-lbl">Zgodovina Prebojnih Signalov OGM &gt; 80</div>
        <table class="dark-tbl">
          <thead>
            <tr>
              <th>Datum preboja</th>
              <th>Cena ob signalu</th>
              <th>Maks cena v 12m</th>
              <th>Maks 12m donos</th>
              <th>Min cena v 12m</th>
              <th>Maks 12m izguba</th>
            </tr>
          </thead>
          <tbody id="historyBody"></tbody>
        </table>
      </div>

      <!-- COMING SOON (shared placeholder) -->
      <!-- SEKTOR TAB -->
      <div class="tab-pane" id="tab-sector">
        <div id="sector-content"></div>
      </div>

      <div class="tab-pane" id="tab-soon">
        <div class="coming-soon">
          <div class="cs-icon">&#x1F527;</div>
          <div class="cs-title">Kmalu na voljo</div>
          <div class="cs-sub">Ta razdelek bo dodan v naslednji verziji.</div>
        </div>
      </div>

    </div><!-- /modal-body -->
  </div><!-- /modal-content -->
</div><!-- /modal -->

<script>
const chartData = {graf_json};
const sektorData = {sektor_json};
let currentChart = null;

function openAnalysis(ticker, rank) {{
    const data = chartData[ticker];
    if (!data) return;

    // Reset to first tab
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    document.getElementById('tab-btn-summary').classList.add('active');
    document.getElementById('tab-summary').classList.add('active');

    // ── Hero ──────────────────────────────────────────────────
    document.getElementById('heroRank').textContent = '#' + (rank || '');
    document.getElementById('heroTicker').textContent = ticker;
    document.getElementById('heroCompany').textContent = data.ime || ticker;
    document.getElementById('heroSector').textContent = data.sektor || 'N/A';
    document.getElementById('heroMcap').textContent = data.mcap || 'N/A';
    document.getElementById('heroRevGrowth').textContent = (data.rev_growth >= 0 ? '+' : '') + (data.rev_growth || 0).toFixed(1) + '% Rev Growth';
    document.getElementById('heroPrice').textContent = '$' + (data.cena || 0).toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});

    const d1m = data.donos_1m || 0;
    const dytd = data.donos_ytd || 0;
    document.getElementById('hero1m').innerHTML = '<span class="hero-ret-lbl">1M </span><span class="' + (d1m >= 0 ? 'hero-ret-pos' : 'hero-ret-neg') + '">' + (d1m >= 0 ? '+' : '') + d1m.toFixed(1) + '%</span>';
    document.getElementById('heroYtd').innerHTML = '<span class="hero-ret-lbl">YTD </span><span class="' + (dytd >= 0 ? 'hero-ret-pos' : 'hero-ret-neg') + '">' + (dytd >= 0 ? '+' : '') + dytd.toFixed(1) + '%</span>';

    const ogm = data.components.total_score || 0;
    document.getElementById('heroConfPct').textContent = ogm.toFixed(1) + '%';
    document.getElementById('heroConfScore').textContent = Math.round(ogm);
    document.getElementById('heroConfBar').style.width = Math.min(100, ogm) + '%';

    const statusEl = document.getElementById('heroStatusBadge');
    const statusMap = {{'STRONG BUY': 'status-sb', 'BUY': 'status-buy', 'SUPER-GROWTH TARGET': 'status-sg', 'WARNING (FALLING PHASE)': 'status-warn', 'WARNING (POD MA)': 'status-warn'}};
    statusEl.className = statusMap[data.status] || 'status-buy';
    statusEl.textContent = data.status || '';

    // ── Metrics strip ─────────────────────────────────────────
    const tp = data.target_price > 0 ? '$' + data.target_price.toFixed(2) : 'N/A';
    const madist = data.components.ma_dist_raw;
    document.getElementById('modalMetrics').innerHTML =
        '<div class="mbar-item"><div class="mbar-lbl">1M Donos</div><div class="mbar-val ' + (d1m>=0?'mv-pos':'mv-neg') + '">' + (d1m>=0?'+':'') + d1m.toFixed(1) + '%</div></div>' +
        '<div class="mbar-item"><div class="mbar-lbl">YTD Donos</div><div class="mbar-val ' + (dytd>=0?'mv-pos':'mv-neg') + '">' + (dytd>=0?'+':'') + dytd.toFixed(1) + '%</div></div>' +
        '<div class="mbar-item"><div class="mbar-lbl">Market Cap</div><div class="mbar-val mv-neu">' + (data.mcap||'N/A') + '</div></div>' +
        '<div class="mbar-item"><div class="mbar-lbl">Rev Rast</div><div class="mbar-val mv-pos">+' + (data.rev_growth||0).toFixed(1) + '%</div></div>' +
        '<div class="mbar-item"><div class="mbar-lbl">OGM Score</div><div class="mbar-val mv-blue">' + ogm.toFixed(1) + '</div></div>' +
        '<div class="mbar-item"><div class="mbar-lbl">Ciljna Cena</div><div class="mbar-val mv-neu">' + tp + '</div></div>' +
        '<div class="mbar-item"><div class="mbar-lbl">MA Razdalja</div><div class="mbar-val ' + (madist>=0?'mv-pos':'mv-neg') + '">' + (madist>=0?'+':'') + madist.toFixed(1) + '%</div></div>' +
        '<div class="mbar-item"><div class="mbar-lbl">RSI (14w)</div><div class="mbar-val mv-purp">' + data.components.rsi_raw.toFixed(1) + '</div></div>';

    buildChart(data);
    buildComponents(data);
    buildYearly(data);
    buildMonthly(data);
    buildSignals(data);


    // ── Populate Sektor tab ──
    (function() {{
        const sektor   = data.sektor || '';
        const sd       = sektorData[sektor] || {{}};
        const allSec   = Object.entries(sektorData).sort((a,b) => (b[1].donos_ytd||0)-(a[1].donos_ytd||0));
        const rank     = allSec.findIndex(e => e[0] === sektor) + 1;
        const clr      = v => v >= 0 ? '#4ade80' : '#f87171';
        const fmt      = v => (v > 0 ? '+' : '') + (v||0).toFixed(1) + '%';
        const rsi      = sd.rsi || 50;
        const trendCls = rsi > 55 ? 'trend-bull' : (rsi < 45 ? 'trend-bear' : 'trend-neu');
        const trendLbl = rsi > 55 ? 'BULLISH'    : (rsi < 45 ? 'BEARISH'    : 'NEVTRALNO');

        const rows = allSec.map((e, idx) => {{
            const [sN, sD] = e;
            const act = sN === sektor ? 'sec-row-active' : '';
            return '<tr class="' + act + '">' +
                '<td style="color:#334155;font-weight:700">' + (idx+1) + '</td>' +
                '<td style="color:#f1f5f9;font-weight:700">' + sN + '</td>' +
                '<td style="color:#60a5fa">' + (sD.etf||'-') + '</td>' +
                '<td style="color:' + clr(sD.donos_1m||0) + '">' + fmt(sD.donos_1m||0) + '</td>' +
                '<td style="color:' + clr(sD.donos_3m||0) + '">' + fmt(sD.donos_3m||0) + '</td>' +
                '<td style="color:' + clr(sD.donos_ytd||0) + ';font-weight:700">' + fmt(sD.donos_ytd||0) + '</td>' +
                '<td style="color:' + clr(sD.donos_1y||0) + '">' + fmt(sD.donos_1y||0) + '</td>' +
                '<td style="color:#60a5fa">' + (sD.rsi||0).toFixed(1) + '</td></tr>';
        }}).join('');

        document.getElementById('sector-content').innerHTML =
            '<div class="sec-hero">' +
              '<div><div class="sec-name">' + (sektor||'N/A') + '</div>' +
              '<div class="sec-sub">ETF: ' + (sd.etf||'N/A') + ' &bull; $' + (sd.cena||0).toFixed(2) + ' &bull; Rank #' + rank + ' / ' + allSec.length + '</div></div>' +
              '<div class="' + trendCls + '">' + trendLbl + '</div></div>' +
            '<div class="sec-metrics">' +
              '<div class="sec-met"><div class="sec-met-lbl">1M</div><div class="sec-met-val" style="color:' + clr(sd.donos_1m||0) + '">' + fmt(sd.donos_1m||0) + '</div></div>' +
              '<div class="sec-met"><div class="sec-met-lbl">3M</div><div class="sec-met-val" style="color:' + clr(sd.donos_3m||0) + '">' + fmt(sd.donos_3m||0) + '</div></div>' +
              '<div class="sec-met"><div class="sec-met-lbl">YTD</div><div class="sec-met-val" style="color:' + clr(sd.donos_ytd||0) + '">' + fmt(sd.donos_ytd||0) + '</div></div>' +
              '<div class="sec-met"><div class="sec-met-lbl">1Y</div><div class="sec-met-val" style="color:' + clr(sd.donos_1y||0) + '">' + fmt(sd.donos_1y||0) + '</div></div>' +
              '<div class="sec-met"><div class="sec-met-lbl">RSI</div><div class="sec-met-val" style="color:#60a5fa">' + rsi.toFixed(1) + '</div></div>' +
              '<div class="sec-met"><div class="sec-met-lbl">Cena ETF</div><div class="sec-met-val">$' + (sd.cena||0).toFixed(2) + '</div></div>' +
            '</div>' +
            '<div class="sec-chart-wrap">' +
              '<div class="tab-section-lbl">Primerjava sektorjev — YTD (%)</div>' +
              '<div style="position:relative;height:240px;margin-top:10px;"><canvas id="sectorCompareChart"></canvas></div>' +
            '</div>' +
            '<div class="tab-section-lbl" style="margin-bottom:10px;">Razvrstitev sektorjev</div>' +
            '<table class="sec-table"><thead><tr><th>#</th><th>Sektor</th><th>ETF</th><th>1M</th><th>3M</th><th>YTD</th><th>1Y</th><th>RSI</th></tr></thead><tbody>' + rows + '</tbody></table>';

        if (window._sectorChart) {{ window._sectorChart.destroy(); }}
        const sCtx = document.getElementById('sectorCompareChart');
        if (sCtx) {{
            const bgColors = allSec.map(e => e[0]===sektor ? 'rgba(59,130,246,.85)' : (e[1].donos_ytd>=0 ? 'rgba(74,222,128,.4)' : 'rgba(248,113,113,.4)'));
            const bColors  = allSec.map(e => e[0]===sektor ? '#60a5fa' : 'transparent');
            window._sectorChart = new Chart(sCtx.getContext('2d'), {{
                type: 'bar',
                data: {{
                    labels: allSec.map(e => e[1].etf||e[0]),
                    datasets: [{{ label: 'YTD (%)', data: allSec.map(e => e[1].donos_ytd||0),
                        backgroundColor: bgColors, borderColor: bColors, borderWidth: 2, borderRadius: 4 }}]
                }},
                options: {{
                    responsive: true, maintainAspectRatio: false,
                    plugins: {{ legend: {{ display: false }},
                        tooltip: {{ callbacks: {{ title: ctx => allSec[ctx[0].dataIndex][0], label: ctx => fmt(ctx.raw) }} }} }},
                    scales: {{
                        x: {{ ticks: {{ color: '#6b7280', font: {{ size: 10 }} }}, grid: {{ display: false }} }},
                        y: {{ ticks: {{ color: '#6b7280', callback: v => (v>0?'+':'')+v+'%' }}, grid: {{ color: 'rgba(255,255,255,.05)' }} }}
                    }}
                }}
            }});
        }}
    }})();

    document.getElementById('analysisModal').style.display = 'block';
    document.body.style.overflow = 'hidden';
}}

function buildChart(data) {{
    const ctx = document.getElementById('ogmChart').getContext('2d');
    if (currentChart) {{ currentChart.destroy(); }}
    currentChart = new Chart(ctx, {{
        type: 'bar',
        data: {{
            labels: data.dates,
            datasets: [
                {{ type: 'bar', label: 'Volumen BUY', data: data.volume_buy || [], yAxisID: 'yVol', backgroundColor: 'rgba(34,197,94,.45)', borderWidth: 0, maxBarThickness: 5 }},
                {{ type: 'bar', label: 'Volumen SELL', data: data.volume_sell || [], yAxisID: 'yVol', backgroundColor: 'rgba(239,68,68,.45)', borderWidth: 0, maxBarThickness: 5 }},
                {{ type: 'line', label: 'Cena ($)', data: data.prices, yAxisID: 'y', borderColor: '#38bdf8', backgroundColor: 'rgba(56,189,248,.06)', borderWidth: 2, pointRadius: 0, tension: 0.1, fill: false }},
                {{ type: 'line', label: 'SMA 50', data: data.ma50 || [], yAxisID: 'y', borderColor: '#fb923c', borderWidth: 1.5, pointRadius: 0, borderDash: [4,4], fill: false }},
                {{ type: 'line', label: 'SMA 200', data: data.ma200 || [], yAxisID: 'y', borderColor: '#a78bfa', borderWidth: 1.5, pointRadius: 0, borderDash: [2,5], fill: false }},
                {{ type: 'line', label: 'OGM Score', data: data.ogm, yAxisID: 'y1', borderColor: '#4ade80', borderWidth: 2, pointRadius: 0, tension: 0.3, borderDash: [6,3], fill: false }}
            ]
        }},
        options: {{
            responsive: true, maintainAspectRatio: false,
            interaction: {{ mode: 'index', intersect: false }},
            scales: {{
                x: {{ ticks: {{ maxTicksLimit: 10, color: '#475569', font: {{size:9}} }}, grid: {{ color: 'rgba(255,255,255,.03)' }} }},
                y: {{ type: 'linear', position: 'left', title: {{ display: true, text: 'Cena ($)', color: '#475569', font: {{size:9}} }}, ticks: {{ color: '#475569', font: {{size:9}} }}, grid: {{ color: 'rgba(255,255,255,.05)' }} }},
                y1: {{ type: 'linear', position: 'right', min: 0, max: 100, title: {{ display: true, text: 'OGM', color: '#475569', font: {{size:9}} }}, ticks: {{ color: '#475569', font: {{size:9}} }}, grid: {{ drawOnChartArea: false }} }},
                yVol: {{ type: 'linear', position: 'right', ticks: {{ display: false }}, grid: {{ drawOnChartArea: false }} }}
            }},
            plugins: {{
                legend: {{ position: 'top', labels: {{ color: '#94a3b8', boxWidth: 12, font: {{size:9}} }} }},
                zoom: {{
                    zoom: {{ wheel: {{ enabled: true }}, pinch: {{ enabled: true }}, mode: 'x' }},
                    pan: {{ enabled: false }}
                }}
            }}
        }}
    }});
    document.getElementById('ogmChart').ondblclick = function() {{ resetChartZoom(); }};
}}

function buildComponents(data) {{
    const c = data.components;
    function scoreBar(val, max) {{
        return '<div class="score-bar-wrap"><span class="val-em">' + val.toFixed(1) + '</span><div class="score-bar-bg"><div class="score-bar-fill" style="width:' + Math.min(100,(val/max)*100) + '%"></div></div><span style="color:#334155;font-size:8pt;">/' + max + '</span></div>';
    }}
    document.getElementById('componentsBody').innerHTML =
        '<table class="dark-tbl"><thead><tr><th>Faktor</th><th>Vrednost</th><th>Točke</th></tr></thead><tbody>' +
        '<tr><td>Rast EPS</td><td>' + c.eps_growth_raw.toFixed(1) + '%</td><td>' + scoreBar(c.eps_growth_score,20) + '</td></tr>' +
        '<tr><td>PEG Ratio</td><td>' + c.peg_raw.toFixed(2) + '</td><td>' + scoreBar(c.peg_score,15) + '</td></tr>' +
        '<tr><td>Bruto Marža</td><td>' + c.margin_raw.toFixed(1) + '%</td><td>' + scoreBar(c.margin_score,10) + '</td></tr>' +
        '<tr><td>RSI (14w)</td><td>' + c.rsi_raw.toFixed(1) + '</td><td>' + scoreBar(c.rsi_score,15) + '</td></tr>' +
        '<tr><td>Razdalja od ' + c.ma_type + '</td><td>' + c.ma_dist_raw.toFixed(1) + '%</td><td>' + scoreBar(c.ma_dist_score,40) + '</td></tr>' +
        '<tr><td style="color:#334155;">P/E (info)</td><td style="color:#334155;">' + c.pe_raw.toFixed(1) + '</td><td style="color:#1e293b;">—</td></tr>' +
        '<tr class="total-row"><td colspan="2">SKUPAJ OGM</td><td><span style="font-size:14pt;">' + c.total_score.toFixed(1) + '</span><span style="color:#475569;"> / 100</span></td></tr>' +
        '</tbody></table>';
}}

function buildYearly(data) {{
    let html = '<div class="yearly-flex">';
    data.yearly.forEach(function(y) {{
        const cls = y.donos >= 0 ? 'yr-pos' : 'yr-neg';
        html += '<div class="yr-card ' + cls + '"><div class="yr-lbl">' + y.leto + '</div><div class="yr-val">' + (y.donos>0?'+':'') + y.donos.toFixed(1) + '%</div></div>';
    }});
    html += '</div>';
    document.getElementById('yearlyBody').innerHTML = html;
}}

function buildMonthly(data) {{
    const meseci = ['Jan','Feb','Mar','Apr','Maj','Jun','Jul','Avg','Sep','Okt','Nov','Dec'];
    let html = '<table class="hm-tbl"><thead><tr><th>Leto</th>';
    meseci.forEach(function(m) {{ html += '<th>' + m + '</th>'; }});
    html += '</tr></thead><tbody>';
    const years = Object.keys(data.monthly).map(Number).sort(function(a,b){{return b-a;}});
    years.slice(0,10).forEach(function(y) {{
        html += '<tr><td class="hm-yr">' + y + '</td>';
        for(let m=1;m<=12;m++) {{
            const val = data.monthly[y] && data.monthly[y][m];
            if (val !== undefined) {{
                const c = val>=0 ? '#4ade80':'#f87171';
                const bg = val>=0 ? 'rgba(74,222,128,.13)':'rgba(248,113,113,.13)';
                html += '<td style="color:'+c+';background:'+bg+';">'+(val>0?'+':'')+val.toFixed(1)+'%</td>';
            }} else {{ html += '<td style="color:#1e293b;">-</td>'; }}
        }}
        html += '</tr>';
    }});
    html += '</tbody></table>';
    document.getElementById('monthlyBody').innerHTML = html;
}}

function buildSignals(data) {{
    const tbody = document.getElementById('historyBody');
    tbody.innerHTML = '';
    if (!data.history || data.history.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#334155;padding:30px;">Ni zabeleženih preteklih signalov.</td></tr>';
        return;
    }}
    data.history.forEach(function(row) {{
        const color = row.max_donos >= 0 ? '#4ade80' : '#f87171';
        const tr = document.createElement('tr');
        const lossColor = '#f87171';
        tr.innerHTML = '<td>' + row.datum + '</td><td>$' + row.cena.toFixed(2) + '</td><td>$' + row.max_cena.toFixed(2) + '</td><td style="color:' + color + ';font-weight:700;">+' + row.max_donos.toFixed(1) + '%</td><td>$' + (row.min_cena||0).toFixed(2) + '</td><td style="color:' + lossColor + ';font-weight:700;">' + (row.max_izguba||0).toFixed(1) + '%</td>';
        tbody.appendChild(tr);
    }});
}}

function switchTab(btnEl, tabId) {{
    document.querySelectorAll('.tab-btn').forEach(function(b) {{ b.classList.remove('active'); }});
    document.querySelectorAll('.tab-pane').forEach(function(p) {{ p.classList.remove('active'); }});
    btnEl.classList.add('active');
    const pane = document.getElementById(tabId);
    if (pane) pane.classList.add('active');
}}

function closeModal() {{
    document.getElementById('analysisModal').style.display = 'none';
    document.body.style.overflow = '';
}}
window.onclick = function(e) {{
    if (e.target === document.getElementById('analysisModal')) closeModal();
}};
document.addEventListener('keydown', function(e) {{ if (e.key === 'Escape') closeModal(); }});

function resetChartZoom() {{
    if (!currentChart) return;
    currentChart.options.scales.x.min = undefined;
    currentChart.options.scales.x.max = undefined;
    if (currentChart.resetZoom) currentChart.resetZoom();
    else currentChart.update();
}}

// ── Manual drag-to-pan (replaces chartjs-plugin-zoom pan which conflicts on mixed charts) ──
(function() {{
    var canvas = document.getElementById('ogmChart');
    var dragActive = false;
    var dragStartX = 0;
    var rangeAtStart = null;

    canvas.addEventListener('mousedown', function(e) {{
        if (e.button !== 0 || !currentChart) return;
        if (document.getElementById('analysisModal').style.display !== 'block') return;
        var xScale = currentChart.scales.x;
        var totalLen = currentChart.data.labels.length;
        var curMin = (xScale.min !== undefined && xScale.min !== null) ? xScale.min : 0;
        var curMax = (xScale.max !== undefined && xScale.max !== null) ? xScale.max : totalLen - 1;
        var visibleRange = curMax - curMin;
        // Only pan when zoomed in (at least 5% zoom applied)
        if (visibleRange >= totalLen * 0.97) return;
        dragActive = true;
        dragStartX = e.clientX;
        rangeAtStart = {{ min: curMin, max: curMax, range: visibleRange }};
        // Suppress tooltip interaction while dragging
        currentChart.options.interaction = {{ mode: 'none', intersect: false }};
        canvas.style.cursor = 'grabbing';
        e.preventDefault();
    }});

    document.addEventListener('mousemove', function(e) {{
        if (!dragActive || !currentChart || !rangeAtStart) return;
        var xScale = currentChart.scales.x;
        var totalLen = currentChart.data.labels.length;
        var pixelWidth = xScale.right - xScale.left;
        if (pixelWidth <= 0) return;
        var pxPerUnit = pixelWidth / rangeAtStart.range;
        var delta = -(e.clientX - dragStartX) / pxPerUnit;
        var newMin = rangeAtStart.min + delta;
        var newMax = rangeAtStart.max + delta;
        // Clamp to data bounds
        if (newMin < 0) {{ newMin = 0; newMax = rangeAtStart.range; }}
        if (newMax > totalLen - 1) {{ newMax = totalLen - 1; newMin = newMax - rangeAtStart.range; }}
        currentChart.options.scales.x.min = newMin;
        currentChart.options.scales.x.max = newMax;
        currentChart.update('none');
    }});

    document.addEventListener('mouseup', function() {{
        if (!dragActive) return;
        dragActive = false;
        rangeAtStart = null;
        if (currentChart) {{
            // Restore tooltip interaction
            currentChart.options.interaction = {{ mode: 'index', intersect: false }};
            canvas.style.cursor = 'grab';
        }}
    }});
}})();
</script>
</body>
</html>
"""

    html_content = html_content.replace("NaN", "0.0")
    ime_datoteke = "index.html"  # A16
    with open(ime_datoteke, "w", encoding="utf-8") as f: f.write(html_content)
    print(f"Poročilo ustvarjeno: {ime_datoteke}")
    if os.environ.get("CI") != "true":
        webbrowser.open(f"file://{os.path.abspath(ime_datoteke)}")

skeniraj_trg()
