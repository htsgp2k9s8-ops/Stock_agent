import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
import sys
import webbrowser
from datetime import datetime, date, timedelta

print("=========================================================")
print("OGM VIRTUAL PORTFOLIO TRACKER - LIVE vs S&P500 & NASDAQ")
print("=========================================================")

PORTFOLIO_FILE = "ogm_virtual_portfolio.json"
STARTING_CASH  = 50_000.0
OUTPUT_FILE    = "OGM_VIRTUAL_PORTFOLIO.html"
MIN_DATE       = "2024-01-01"
TODAY          = date.today().isoformat()

# ── Load / create portfolio ───────────────────────────────────────────────────
def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            p = json.load(f)
        # Migrate old format (single dict per ticker) → list of lots
        for ticker, val in p.get("positions", {}).items():
            if isinstance(val, dict):
                p["positions"][ticker] = [val]
        if "starting_cash"     not in p: p["starting_cash"]     = STARTING_CASH
        if "closed_positions"  not in p: p["closed_positions"]  = []
        return p
    return {"cash": STARTING_CASH, "starting_cash": STARTING_CASH,
            "created": TODAY, "positions": {}, "closed_positions": []}

def save_portfolio(p):
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2)

def get_historical_price(ticker, date_str):
    try:
        end_dt = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
        hist = yf.Ticker(ticker).history(start=date_str, end=end_dt, auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[0]), hist.index[0].strftime("%Y-%m-%d")
    except Exception:
        pass
    return None, None

def get_live_price(ticker):
    try:
        info = yf.Ticker(ticker).info
        price = (info.get("regularMarketPrice") or info.get("currentPrice")
                 or info.get("previousClose"))
        if not price:
            hist = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
            price = float(hist["Close"].iloc[-1]) if not hist.empty else None
        return price, info
    except Exception:
        return None, {}

portfolio = load_portfolio()

# ══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════════════════════════
while True:
    total_lots    = sum(len(lots) for lots in portfolio["positions"].values())
    total_tickers = len(portfolio["positions"])
    print(f"\n---------------------------------------------------------")
    print(f"  Gotovina   : ${portfolio['cash']:,.2f}")
    print(f"  Pozicije   : {total_tickers} delnic  ({total_lots} lotov)")
    print(f"---------------------------------------------------------")
    print("  1  Dodaj nakup  (historični ali danes)")
    print("  2  Prodaj pozicijo  (delno ali vse)")
    print("  3  Generiraj porocilo  (odpre HTML)")
    print("  4  Dodaj historično prodajo  (popravi graf za A3 preteklost)")
    print("  5  Izbriši napačen vnos prodaje")
    print("  0  Izhod brez porocila")
    print()

    choice = input("Izbira (0/1/2/3/4/5): ").strip()

    # ── Exit ─────────────────────────────────────────────────────────────────
    if choice == "0":
        print("Izhod.")
        sys.exit(0)

    # ── Report ────────────────────────────────────────────────────────────────
    elif choice == "3":
        break

    # ── Buy ───────────────────────────────────────────────────────────────────
    elif choice == "1":
        ticker = input("Ticker (npr. NVDA): ").strip().upper()
        if not ticker:
            print("[Prekinjeno]")
        else:
            print(f"Razpoložljiva gotovina: ${portfolio['cash']:,.2f}")
            print()
            print(f"Datum nakupa — vnesi retroaktivni datum ali pritisni Enter za danes ({TODAY}).")
            print(f"Veljaven razpon: {MIN_DATE}  →  {TODAY}")
            date_input = input("Datum nakupa [YYYY-MM-DD | Enter = danes]: ").strip()

            if not date_input:
                purchase_date  = TODAY
                is_retroactive = False
            elif MIN_DATE <= date_input <= TODAY:
                purchase_date  = date_input
                is_retroactive = (purchase_date < TODAY)
            else:
                print(f"[Napaka] Datum mora biti med {MIN_DATE} in {TODAY}.")
                purchase_date = None

            if purchase_date:
                try:
                    raw    = input(f"Znesek $ za {ticker} na {purchase_date}: ").strip().replace(",", "")
                    amount = float(raw)
                except ValueError:
                    print("[Napaka] Neveljaven znesek.")
                    amount = 0

                if 0 < amount <= portfolio["cash"]:
                    try:
                        if is_retroactive:
                            print(f"  Pridobivam historično ceno za {ticker} na {purchase_date} ...")
                            price, actual_date = get_historical_price(ticker, purchase_date)
                            if price is None:
                                print(f"[Napaka] Ne najdem historične cene za {ticker} po {purchase_date}.")
                            else:
                                if actual_date != purchase_date:
                                    print(f"  [Info] Naslednji trading dan: {actual_date}  →  cena ${price:.2f}")
                                    purchase_date = actual_date
                                try:    info = yf.Ticker(ticker).info
                                except: info = {}
                        else:
                            price, info = get_live_price(ticker)

                        if price and price > 0:
                            shares  = amount / price
                            company = info.get("shortName") or info.get("longName") or ticker
                            sector  = info.get("sector", "N/A")

                            lot = {
                                "shares"    : round(shares, 6),
                                "cost_basis": round(price, 4),
                                "invested"  : round(amount, 2),
                                "open_date" : purchase_date,
                                "company"   : company,
                                "sector"    : sector,
                            }
                            portfolio["positions"].setdefault(ticker, []).append(lot)
                            portfolio["cash"] = round(portfolio["cash"] - amount, 2)
                            save_portfolio(portfolio)

                            tag = "RETROAKTIVNO" if is_retroactive else "DANES"
                            print(f"\n[OK] [{tag}] {shares:.4f} del. {ticker} @ ${price:.2f}"
                                  f" na {purchase_date}  ({company})")
                        elif price is not None:
                            print(f"[Napaka] Cena je 0 ali negativna za {ticker}.")
                    except Exception as e:
                        print(f"[Napaka] {e}")

                elif amount > portfolio["cash"]:
                    print(f"[Napaka] Premalo gotovine (${portfolio['cash']:,.2f}).")
                else:
                    print("[Prekinjeno]")

    # ── Sell ──────────────────────────────────────────────────────────────────
    elif choice == "2":
        if not portfolio["positions"]:
            print("[Info] Ni odprtih pozicij.")
        else:
            print("Odprte pozicije:", ", ".join(portfolio["positions"].keys()))
            ticker = input("Kateri ticker prodati? ").strip().upper()
            if ticker not in portfolio["positions"]:
                print(f"[Napaka] {ticker} ni v portfelju.")
            else:
                price, _ = get_live_price(ticker)
                if not price or price <= 0:
                    print("[Napaka] Ne morem pridobiti tržne cene.")
                else:
                    lots         = portfolio["positions"][ticker]
                    total_shares = sum(l["shares"]  for l in lots)
                    total_inv    = sum(l["invested"] for l in lots)
                    total_val    = round(total_shares * price, 2)
                    avg_cost     = total_inv / total_shares if total_shares > 0 else 0

                    print(f"\n  {ticker}  |  {total_shares:.4f} del.  |  avg nakup ${avg_cost:.2f}"
                          f"  |  tržna ${price:.2f}  |  vrednost ${total_val:,.2f}")
                    print(f"  Loti ({len(lots)}) — FIFO vrstni red:")
                    for i, lot in enumerate(sorted(lots, key=lambda x: x["open_date"]), 1):
                        lv   = round(lot["shares"] * price, 2)
                        lpnl = round(lv - lot["invested"], 2)
                        sign = "+" if lpnl >= 0 else ""
                        print(f"    Lot {i}: {lot['open_date']}  "
                              f"{lot['shares']:.4f} del. @ ${lot['cost_basis']:.2f}  "
                              f"= ${lv:,.2f}  (P&L: {sign}${lpnl:,.2f})")

                    print()
                    print(f"  Vnesi količino za prodajo:")
                    print(f"    [število]   delnice, npr.  5.5          (max {total_shares:.4f})")
                    print(f"    $[znesek]   vrednost v $,  npr.  $2500   (max ${total_val:,.2f})")
                    print(f"    vse         proda vse lote")
                    print()
                    sell_input = input("Prodaj: ").strip()

                    if sell_input.lower() == "vse":
                        shares_to_sell = total_shares
                    elif sell_input.startswith("$"):
                        try:
                            sell_usd       = float(sell_input[1:].replace(",", ""))
                            shares_to_sell = min(sell_usd / price, total_shares)
                        except ValueError:
                            print("[Napaka] Neveljaven $ znesek.")
                            shares_to_sell = 0
                    else:
                        try:
                            shares_to_sell = float(sell_input.replace(",", ""))
                        except ValueError:
                            print("[Napaka] Neveljaven vnos.")
                            shares_to_sell = 0

                    if shares_to_sell <= 0:
                        print("[Prekinjeno]")
                    elif shares_to_sell > total_shares + 1e-6:
                        print(f"[Napaka] Preveč delnic. Imaš {total_shares:.4f}.")
                    else:
                        shares_to_sell = min(shares_to_sell, total_shares)
                        sell_value     = round(shares_to_sell * price, 2)

                        remaining    = shares_to_sell
                        cost_of_sold = 0.0
                        new_lots     = []
                        closed_log   = []   # records each consumed lot for historical chart

                        for lot in sorted(lots, key=lambda x: x["open_date"]):
                            if remaining <= 0:
                                new_lots.append(lot)
                                continue
                            if lot["shares"] <= remaining + 1e-8:
                                # Entire lot consumed
                                sold_shares   = lot["shares"]
                                cost_of_sold += lot["invested"]
                                remaining    -= lot["shares"]
                                closed_log.append({
                                    "ticker"   : ticker,
                                    "buy_date" : lot["open_date"],
                                    "sell_date": TODAY,
                                    "shares"   : round(sold_shares, 6),
                                    "buy_price": lot["cost_basis"],
                                    "sell_price": round(price, 4),
                                    "invested" : lot["invested"],
                                    "proceeds" : round(sold_shares * price, 2),
                                })
                            else:
                                # Partial lot
                                frac          = remaining / lot["shares"]
                                sold_shares   = remaining
                                cost_of_sold += lot["invested"] * frac
                                new_lot       = dict(lot)
                                new_lot["shares"]   = round(lot["shares"]   - remaining, 6)
                                new_lot["invested"] = round(lot["invested"] * (1 - frac), 2)
                                new_lots.append(new_lot)
                                closed_log.append({
                                    "ticker"   : ticker,
                                    "buy_date" : lot["open_date"],
                                    "sell_date": TODAY,
                                    "shares"   : round(sold_shares, 6),
                                    "buy_price": lot["cost_basis"],
                                    "sell_price": round(price, 4),
                                    "invested" : round(lot["invested"] * frac, 2),
                                    "proceeds" : round(sold_shares * price, 2),
                                })
                                remaining = 0

                        # Persist open lots + closed log
                        if new_lots:
                            portfolio["positions"][ticker] = new_lots
                        else:
                            del portfolio["positions"][ticker]

                        portfolio["closed_positions"].extend(closed_log)
                        portfolio["cash"] = round(portfolio["cash"] + sell_value, 2)
                        save_portfolio(portfolio)

                        pnl  = round(sell_value - cost_of_sold, 2)
                        sign = "+" if pnl >= 0 else ""
                        print(f"\n[OK] Prodano {shares_to_sell:.4f} del. {ticker} @ ${price:.2f}"
                              f"  =  ${sell_value:,.2f}  (P&L: {sign}${pnl:,.2f})")
                        print(f"     Gotovina: ${portfolio['cash']:,.2f}")
                        if new_lots:
                            rem_s = sum(l["shares"] for l in new_lots)
                            print(f"     Ostalo  : {rem_s:.4f} del. v {len(new_lots)} lotu/lotih")

    # ── Historical sell (retroactive A3 correction) ───────────────────────────
    elif choice == "4":
        print()
        print("  Vnesi historično prodajo iz A3 preteklosti.")
        print("  Gotovina se NE spremeni — samo graf se popravi.")
        print("  Podpira delno (partial) in celotno prodajo.")
        print()
        ticker = input("  Ticker (npr. TSLA): ").strip().upper()
        if not ticker:
            print("[Prekinjeno]")
        else:
            buy_date_in  = input("  Datum nakupa  [YYYY-MM-DD]: ").strip()
            sell_date_in = input("  Datum prodaje [YYYY-MM-DD]: ").strip()
            if not (MIN_DATE <= buy_date_in <= sell_date_in <= TODAY):
                print(f"[Napaka] Neveljavna datuma (nakup ≤ prodaja, oba v [{MIN_DATE}, {TODAY}]).")
            else:
                print(f"  Pridobivam historične cene za {ticker} ...")
                buy_price,  actual_buy_date  = get_historical_price(ticker, buy_date_in)
                sell_price, actual_sell_date = get_historical_price(ticker, sell_date_in)

                if not buy_price:
                    print(f"[Napaka] Ne najdem nakupne cene za {ticker} na {buy_date_in}.")
                elif not sell_price:
                    print(f"[Napaka] Ne najdem prodajne cene za {ticker} na {sell_date_in}.")
                else:
                    print(f"  Nakupna cena  {actual_buy_date}: ${buy_price:.2f}")
                    print(f"  Prodajna cena {actual_sell_date}: ${sell_price:.2f}")
                    print()
                    print(f"  Vnesi prodano količino:")
                    print(f"    [število]   delnice, npr.  5.5")
                    print(f"    $[znesek]   izkupiček v $, npr.  $2500")
                    print()
                    sell_input = input("  Prodaj: ").strip()

                    shares_sold = 0.0
                    if sell_input.startswith("$"):
                        try:
                            proceeds_entered = float(sell_input[1:].replace(",", ""))
                            shares_sold = proceeds_entered / sell_price
                        except ValueError:
                            print("[Napaka] Neveljaven $ znesek.")
                    else:
                        try:
                            shares_sold = float(sell_input.replace(",", ""))
                        except ValueError:
                            print("[Napaka] Neveljaven vnos.")

                    if shares_sold > 0:
                        invested_sold = round(shares_sold * buy_price, 2)
                        proceeds      = round(shares_sold * sell_price, 2)
                        pnl           = round(proceeds - invested_sold, 2)
                        sign          = "+" if pnl >= 0 else ""
                        print(f"\n  {ticker}: {shares_sold:.4f} del."
                              f"  nakup {actual_buy_date} @ ${buy_price:.2f}  (cost: ${invested_sold:,.2f})")
                        print(f"  Prodano @ ${sell_price:.2f} ({actual_sell_date})"
                              f"  =  ${proceeds:,.2f}  (P&L: {sign}${pnl:,.2f})")
                        confirm = input("  Potrdi vnos? [d/n]: ").strip().lower()
                        if confirm == "d":
                            portfolio["closed_positions"].append({
                                "ticker"    : ticker,
                                "buy_date"  : actual_buy_date,
                                "sell_date" : actual_sell_date,
                                "shares"    : round(shares_sold, 6),
                                "buy_price" : round(buy_price, 4),
                                "sell_price": round(sell_price, 4),
                                "invested"  : invested_sold,
                                "proceeds"  : proceeds,
                            })
                            save_portfolio(portfolio)
                            print(f"[OK] Historična prodaja dodana. Graf bo sedaj točnejši.")
                        else:
                            print("[Prekinjeno]")

    # ── Delete a wrongly entered closed position ──────────────────────────────
    elif choice == "5":
        cp = portfolio.get("closed_positions", [])
        if not cp:
            print("[Info] Ni vnesenih historičnih prodaj.")
        else:
            print()
            print(f"  {'#':>3}  {'Ticker':<6}  {'Nakup':<12}  {'Prodaja':<12}  {'Del.':<10}  {'Investirano':>12}  {'Izkupiček':>12}  P&L")
            print(f"  {'-'*3}  {'-'*6}  {'-'*12}  {'-'*12}  {'-'*10}  {'-'*12}  {'-'*12}  {'-'*10}")
            for i, cl in enumerate(cp, 1):
                pnl  = round(cl["proceeds"] - cl["invested"], 2)
                sign = "+" if pnl >= 0 else ""
                print(f"  {i:>3}  {cl['ticker']:<6}  {cl['buy_date']:<12}  {cl['sell_date']:<12}"
                      f"  {cl['shares']:<10.4f}  ${cl['invested']:>11,.2f}  ${cl['proceeds']:>11,.2f}"
                      f"  {sign}${pnl:,.2f}")
            print()
            raw = input("  Številka vnosa za izbris (Enter = prekini): ").strip()
            if not raw:
                print("[Prekinjeno]")
            else:
                try:
                    idx = int(raw) - 1
                    if 0 <= idx < len(cp):
                        removed = cp[idx]
                        confirm = input(f"  Izbriši {removed['ticker']} "
                                        f"{removed['buy_date']}→{removed['sell_date']} "
                                        f"{removed['shares']:.4f} del.? [d/n]: ").strip().lower()
                        if confirm == "d":
                            portfolio["closed_positions"].pop(idx)
                            save_portfolio(portfolio)
                            print("[OK] Vnos izbrisan. Vnesi popravljen zapis z opcijo 4.")
                        else:
                            print("[Prekinjeno]")
                    else:
                        print(f"[Napaka] Številka mora biti med 1 in {len(cp)}.")
                except ValueError:
                    print("[Napaka] Vnesi veljavno številko.")

    else:
        print("[Napaka] Neveljaven vnos. Izberi 0, 1, 2, 3, 4 ali 5.")

# end while True ───────────────────────────────────────────────────────────────

# ═══════════════════════════════════════════════════════════════════════════════
# REPORT GENERATION  (reached only when choice == "3")
# ═══════════════════════════════════════════════════════════════════════════════
print("\nPridobivam tržne podatke za porocilo ...")

# Chart start: earliest date across open AND closed lots
all_dates = [portfolio.get("created", TODAY)]
for lots in portfolio["positions"].values():
    for lot in lots:
        all_dates.append(lot.get("open_date", TODAY))
for cl in portfolio.get("closed_positions", []):
    all_dates.append(cl.get("buy_date", TODAY))
earliest_date = min(all_dates)
chart_start   = min(earliest_date, (date.today() - timedelta(days=365)).isoformat())

# All tickers ever held (open + closed) for price download
open_tickers   = list(portfolio["positions"].keys())
closed_tickers = list({cl["ticker"] for cl in portfolio.get("closed_positions", [])})
all_tickers    = list(set(open_tickers + closed_tickers)) + ["^GSPC", "^NDX"]

try:
    raw = yf.download(all_tickers, start=chart_start, interval="1d",
                      progress=False, auto_adjust=True)
    price_data = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
    if isinstance(price_data, pd.Series):
        price_data = price_data.to_frame(name=all_tickers[0])
    price_data = price_data.ffill().bfill()
except Exception as e:
    print(f"[Napaka pri prenosu] {e}")
    price_data = pd.DataFrame()

# ── Current holdings stats ────────────────────────────────────────────────────
holdings = []
today_ts = date.today()

for ticker, lots in portfolio["positions"].items():
    total_shares = sum(l["shares"]   for l in lots)
    total_inv    = sum(l["invested"] for l in lots)
    avg_cost     = total_inv / total_shares if total_shares > 0 else 0
    earliest_lot = min(l["open_date"] for l in lots)
    company      = lots[0]["company"]
    sector       = lots[0]["sector"]
    num_lots     = len(lots)

    if not price_data.empty and ticker in price_data.columns:
        current_price = float(price_data[ticker].iloc[-1])
    else:
        cp, _ = get_live_price(ticker)
        current_price = cp if cp else avg_cost

    current_value = total_shares * current_price
    pnl           = current_value - total_inv
    pnl_pct       = (pnl / total_inv * 100) if total_inv > 0 else 0

    ytd_pct = 0.0
    if not price_data.empty and ticker in price_data.columns:
        ytd_s = price_data[ticker].dropna()
        ytd_s.index = pd.to_datetime(ytd_s.index)
        yr_rows = ytd_s[ytd_s.index.year == today_ts.year]
        if len(yr_rows) > 0:
            ytd_pct = round(((current_price - float(yr_rows.iloc[0])) / float(yr_rows.iloc[0])) * 100, 2)

    holdings.append({
        "ticker"       : ticker,
        "company"      : company,
        "sector"       : sector,
        "shares"       : total_shares,
        "avg_cost"     : round(avg_cost, 4),
        "current_price": round(current_price, 2),
        "invested"     : total_inv,
        "current_value": round(current_value, 2),
        "pnl"          : round(pnl, 2),
        "pnl_pct"      : round(pnl_pct, 2),
        "weight_pct"   : 0,
        "ytd_pct"      : ytd_pct,
        "open_date"    : earliest_lot,
        "num_lots"     : num_lots,
        "lots"         : lots,
    })

total_pos_value    = sum(h["current_value"] for h in holdings)
total_portfolio_v  = total_pos_value + portfolio["cash"]
total_invested     = sum(h["invested"]      for h in holdings)
total_pnl          = total_pos_value - total_invested
total_pnl_pct      = (total_pnl / total_invested * 100) if total_invested > 0 else 0

for h in holdings:
    h["weight_pct"] = round(h["current_value"] / total_portfolio_v * 100, 1) if total_portfolio_v > 0 else 0

holdings.sort(key=lambda x: x["current_value"], reverse=True)

# ── Time-series: reconstruct full portfolio value including cash ───────────────
# At every date we compute:
#   hist_cash  = starting_cash
#              - invested in open lots opened on/before dt
#              - invested in closed lots bought on/before dt
#              + proceeds from closed lots sold on/before dt
#   pos_val    = market value of open lots opened on/before dt
#              + market value of closed lots active on dt (buy_date <= dt < sell_date)
chart_labels    = []
chart_portfolio = []
chart_sp500     = []
chart_ndx       = []

closed_positions = portfolio.get("closed_positions", [])

if not price_data.empty:
    base_candidates = price_data[price_data.index >= pd.Timestamp(chart_start)]
    if not base_candidates.empty:
        base_row   = base_candidates.iloc[0]
        sp500_base = float(base_row["^GSPC"]) if "^GSPC" in price_data.columns else 1
        ndx_base   = float(base_row["^NDX"])  if "^NDX"  in price_data.columns else 1

        for dt in price_data.index:
            dt_str    = dt.strftime("%Y-%m-%d")
            hist_cash = portfolio["starting_cash"]
            pos_val   = 0.0

            # Open lots ──────────────────────────────────────────────────────
            # If lot exists at t: deduct from cash, add market value.
            # If lot was bought AFTER t: its invested amount is still in cash
            # (handled implicitly — we just don't subtract it).
            for ticker, lots in portfolio["positions"].items():
                for lot in lots:
                    if dt_str >= lot["open_date"]:
                        hist_cash -= lot["invested"]
                        if ticker in price_data.columns:
                            p = float(price_data[ticker].loc[dt])
                            pos_val += lot["shares"] * (p if not np.isnan(p) else lot["cost_basis"])
                        else:
                            pos_val += lot["shares"] * lot["cost_basis"]

            # Closed (sold) lots — A4 tracked ────────────────────────────────
            # Before buy_date: lot doesn't exist yet, cash unchanged.
            # buy_date ≤ t < sell_date: active position, show market value.
            # t ≥ sell_date: sold, add proceeds back to cash.
            for cl in closed_positions:
                if dt_str >= cl["buy_date"]:
                    hist_cash -= cl["invested"]
                    if dt_str < cl["sell_date"]:
                        t = cl["ticker"]
                        if t in price_data.columns:
                            p = float(price_data[t].loc[dt])
                            pos_val += cl["shares"] * (p if not np.isnan(p) else cl["buy_price"])
                        else:
                            pos_val += cl["shares"] * cl["buy_price"]
                    else:
                        hist_cash += cl["proceeds"]   # position sold → value converts to cash

            port_val = max(0.0, hist_cash) + pos_val

            sp500_val = (float(price_data["^GSPC"].loc[dt]) / sp500_base * STARTING_CASH
                         if "^GSPC" in price_data.columns else STARTING_CASH)
            ndx_val   = (float(price_data["^NDX"].loc[dt]) / ndx_base * STARTING_CASH
                         if "^NDX"  in price_data.columns else STARTING_CASH)

            chart_labels.append(dt_str)
            chart_portfolio.append(round(port_val, 2))
            chart_sp500.append(round(sp500_val, 2))
            chart_ndx.append(round(ndx_val, 2))

        # ── Force today's point to use live prices ───────────────────────────
        # price_data may already contain today with partial session prices,
        # or may end at yesterday.  Either way, overwrite/append so the chart
        # endpoint always equals the stat-card value exactly.
        try:
            sp500_live  = float(yf.Ticker("^GSPC").history(period="1d")["Close"].iloc[-1])
            ndx_live    = float(yf.Ticker("^NDX" ).history(period="1d")["Close"].iloc[-1])
            sp500_today = round(sp500_live / sp500_base * STARTING_CASH, 2)
            ndx_today   = round(ndx_live   / ndx_base  * STARTING_CASH, 2)
        except Exception:
            sp500_today = chart_sp500[-1] if chart_sp500 else STARTING_CASH
            ndx_today   = chart_ndx[-1]   if chart_ndx   else STARTING_CASH

        if chart_labels and chart_labels[-1] == TODAY:
            chart_portfolio[-1] = round(total_portfolio_v, 2)
            chart_sp500[-1]     = sp500_today
            chart_ndx[-1]       = ndx_today
        else:
            chart_labels.append(TODAY)
            chart_portfolio.append(round(total_portfolio_v, 2))
            chart_sp500.append(sp500_today)
            chart_ndx.append(ndx_today)


# ── Yearly comparison ─────────────────────────────────────────────────────────
yearly_data = []
if chart_labels:
    df_c = pd.DataFrame({"date": pd.to_datetime(chart_labels),
                         "portfolio": chart_portfolio, "sp500": chart_sp500, "ndx": chart_ndx})
    df_c = df_c.set_index("date")
    for yr in sorted(df_c.index.year.unique()):
        yr_df = df_c[df_c.index.year == yr]
        if len(yr_df) < 2:
            continue
        def yr_ret(col, d=yr_df):
            return round(((d[col].iloc[-1] - d[col].iloc[0]) / d[col].iloc[0]) * 100, 2)
        yearly_data.append({"year": int(yr), "portfolio": yr_ret("portfolio"),
                             "sp500": yr_ret("sp500"), "ndx": yr_ret("ndx")})

sp500_return_pct     = round(((chart_sp500[-1]   - STARTING_CASH) / STARTING_CASH) * 100, 2) if chart_sp500 else 0
ndx_return_pct       = round(((chart_ndx[-1]     - STARTING_CASH) / STARTING_CASH) * 100, 2) if chart_ndx    else 0
portfolio_return_pct = round(((total_portfolio_v - STARTING_CASH) / STARTING_CASH) * 100, 2)

alloc_labels = [h["ticker"] for h in holdings]
alloc_values = [h["current_value"] for h in holdings]
if portfolio["cash"] > 0:
    alloc_labels.append("Gotovina")
    alloc_values.append(round(portfolio["cash"], 2))

datum_danes = datetime.now().strftime("%d.%m.%Y %H:%M")

def sign_cls(v): return "pos-return" if v >= 0 else "neg-return"
def fmt_pct(v):  return f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"
def fmt_dollar(v): return f"+${abs(v):,.2f}" if v >= 0 else f"-${abs(v):,.2f}"

# ── Holdings rows ─────────────────────────────────────────────────────────────
holdings_rows = ""
for i, h in enumerate(holdings, 1):
    lot_badge = (f'<span style="font-size:7.5pt;color:#475569;"> ({h["num_lots"]} loti)</span>'
                 if h["num_lots"] > 1 else "")
    holdings_rows += f"""
        <tr>
            <td class="rank-num">#{i}</td>
            <td><span class="ticker-btn-static">{h['ticker']}</span>{lot_badge}</td>
            <td><div class="ime-podjetja" title="{h['company']}">{h['company']}</div></td>
            <td class="sektor-cell">{h['sector']}</td>
            <td style="color:#f1f5f9;font-weight:700;">${h['avg_cost']:.2f}</td>
            <td style="color:#f1f5f9;font-weight:700;">${h['current_price']:.2f}</td>
            <td style="color:#94a3b8;">{h['shares']:.4f}</td>
            <td style="color:#60a5fa;font-weight:700;">${h['current_value']:,.2f}</td>
            <td class="{sign_cls(h['pnl'])}">{fmt_dollar(h['pnl'])}<br><span style="font-size:8pt;">{fmt_pct(h['pnl_pct'])}</span></td>
            <td class="{sign_cls(h['ytd_pct'])}">{fmt_pct(h['ytd_pct'])}</td>
            <td style="color:#64748b;">{h['weight_pct']:.1f}%</td>
            <td style="color:#475569;font-size:8.5pt;">{h['open_date']}</td>
        </tr>"""

if not holdings_rows:
    holdings_rows = '<tr><td colspan="12" style="text-align:center;padding:30px;color:#94a3b8;">Portfolio je prazen. Dodaj delnice z možnostjo 1.</td></tr>'

# ── Open lot rows ─────────────────────────────────────────────────────────────
lot_rows = ""
all_lots_flat = []
for h in holdings:
    for lot in h["lots"]:
        lot_price = h["current_price"]
        lot_val   = round(lot["shares"] * lot_price, 2)
        lot_pnl   = round(lot_val - lot["invested"], 2)
        lot_pnl_p = round(lot_pnl / lot["invested"] * 100, 2) if lot["invested"] > 0 else 0
        all_lots_flat.append({
            "ticker": h["ticker"], "open_date": lot["open_date"], "close_date": "—",
            "cost_basis": lot["cost_basis"], "cur_price": lot_price,
            "shares": lot["shares"], "invested": lot["invested"],
            "cur_val": lot_val, "pnl": lot_pnl, "pnl_pct": lot_pnl_p, "status": "OPEN",
        })

# Closed lots
for cl in sorted(closed_positions, key=lambda x: x["buy_date"]):
    proceeds  = cl["proceeds"]
    invested  = cl["invested"]
    cl_pnl    = round(proceeds - invested, 2)
    cl_pnl_p  = round(cl_pnl / invested * 100, 2) if invested > 0 else 0
    all_lots_flat.append({
        "ticker": cl["ticker"], "open_date": cl["buy_date"], "close_date": cl["sell_date"],
        "cost_basis": cl["buy_price"], "cur_price": cl["sell_price"],
        "shares": cl["shares"], "invested": invested,
        "cur_val": proceeds, "pnl": cl_pnl, "pnl_pct": cl_pnl_p, "status": "SOLD",
    })

all_lots_flat.sort(key=lambda x: x["open_date"])
for lot in all_lots_flat:
    status_style = ("color:#4ade80;font-weight:700;" if lot["status"] == "OPEN"
                    else "color:#94a3b8;font-style:italic;")
    close_display = lot["close_date"]
    lot_rows += f"""
        <tr>
            <td style="color:#475569;font-size:8.5pt;">{lot['open_date']}</td>
            <td style="color:#475569;font-size:8.5pt;">{close_display}</td>
            <td><span class="ticker-btn-static" style="font-size:9pt;padding:3px 8px;">{lot['ticker']}</span></td>
            <td style="color:#94a3b8;">${lot['cost_basis']:.2f}</td>
            <td style="color:#f1f5f9;font-weight:700;">${lot['cur_price']:.2f}</td>
            <td style="color:#94a3b8;">{lot['shares']:.4f}</td>
            <td style="color:#64748b;">${lot['invested']:,.2f}</td>
            <td style="color:#60a5fa;font-weight:700;">${lot['cur_val']:,.2f}</td>
            <td class="{sign_cls(lot['pnl'])}">{fmt_dollar(lot['pnl'])}<br><span style="font-size:7.5pt;">{fmt_pct(lot['pnl_pct'])}</span></td>
            <td style="{status_style}">{lot['status']}</td>
        </tr>"""

if not lot_rows:
    lot_rows = '<tr><td colspan="10" style="text-align:center;padding:20px;color:#475569;">Ni lotov.</td></tr>'

# ── Yearly rows ───────────────────────────────────────────────────────────────
yearly_rows = ""
for yr in yearly_data:
    diff = round(yr["portfolio"] - yr["sp500"], 2)
    yearly_rows += f"""
        <tr>
            <td style="color:#94a3b8;font-weight:700;">{yr['year']}</td>
            <td class="{sign_cls(yr['portfolio'])}">{fmt_pct(yr['portfolio'])}</td>
            <td class="{sign_cls(yr['sp500'])}">{fmt_pct(yr['sp500'])}</td>
            <td class="{sign_cls(yr['ndx'])}">{fmt_pct(yr['ndx'])}</td>
            <td class="{sign_cls(diff)}">{fmt_pct(diff)}</td>
        </tr>"""
if not yearly_rows:
    yearly_rows = '<tr><td colspan="5" style="text-align:center;color:#475569;padding:20px;">Premalo podatkov.</td></tr>'

cash_weight = round(portfolio["cash"] / total_portfolio_v * 100, 1) if total_portfolio_v > 0 else 100
sp_final    = chart_sp500[-1] if chart_sp500 else STARTING_CASH
ndx_final   = chart_ndx[-1]   if chart_ndx    else STARTING_CASH

chart_json = json.dumps({"labels": chart_labels, "portfolio": chart_portfolio,
                          "sp500": chart_sp500, "ndx": chart_ndx})
alloc_json = json.dumps({"labels": alloc_labels, "values": alloc_values})

# ── HTML ──────────────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>OGM Virtual Portfolio</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@1.2.1/dist/chartjs-plugin-zoom.min.js"></script>
<style>
html {{ overflow-x:hidden; }}
body {{ font-family:'Segoe UI',Arial,sans-serif; color:#cbd5e1; background-color:#060d1a; margin:0; padding:22px 12px 50px; min-height:100vh; }}
.page-wrap {{ max-width:1480px; margin:0 auto; }}
.header {{ background:linear-gradient(135deg,#0c1628 0%,#112244 55%,#1d4ed8 100%); color:#fff; padding:26px 30px; border-radius:12px; border:1px solid rgba(255,255,255,.07); box-shadow:0 8px 40px rgba(0,0,0,.55); margin-bottom:20px; }}
.header h1 {{ margin:0; font-size:22pt; font-weight:800; }}
.header p  {{ margin:5px 0 0; color:#bfdbfe; font-size:10.5pt; }}
.stats-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-bottom:20px; }}
@media(max-width:900px) {{ .stats-grid {{ grid-template-columns:1fr; }} }}
.stat-card {{ background:#0b1526; border:1px solid rgba(255,255,255,.06); border-radius:12px; padding:20px 24px; box-shadow:0 4px 20px rgba(0,0,0,.4); }}
.stat-lbl  {{ color:#475569; font-size:8pt; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px; }}
.stat-val  {{ font-size:22pt; font-weight:800; line-height:1.1; }}
.stat-sub  {{ font-size:9pt; margin-top:4px; }}
.val-blue  {{ color:#60a5fa; }}
.val-white {{ color:#f1f5f9; }}
.chart-wrap {{ background:#0b1526; border:1px solid rgba(255,255,255,.06); border-radius:12px; padding:20px; margin-bottom:20px; }}
.chart-wrap h3 {{ margin:0 0 14px; color:#64748b; font-size:9.5pt; font-weight:700; text-transform:uppercase; letter-spacing:.8px; }}
.chart-container {{ height:420px; position:relative; }}
#perfChart {{ cursor:grab; }}
.chart-hint {{ text-align:center; font-size:8pt; color:#334155; margin-top:6px; letter-spacing:.3px; }}
.alloc-container {{ height:300px; position:relative; }}
.two-col {{ display:grid; grid-template-columns:2fr 1fr; gap:16px; margin-bottom:20px; }}
@media(max-width:1000px) {{ .two-col {{ grid-template-columns:1fr; }} }}
.section-title {{ color:#475569; font-size:8pt; font-weight:700; text-transform:uppercase; letter-spacing:1.2px; margin:22px 0 12px; }}
.lot-accordion {{ margin:22px 0 20px; border-radius:12px; border:1px solid rgba(255,255,255,.06); }}
.lot-accordion-header {{ display:flex; justify-content:space-between; align-items:center; padding:12px 18px; cursor:pointer; color:#475569; font-size:8pt; font-weight:700; text-transform:uppercase; letter-spacing:1.2px; background:#0b1526; border-radius:12px; list-style:none; user-select:none; }}
.lot-accordion-header::-webkit-details-marker {{ display:none; }}
.lot-accordion-header:hover {{ color:#64748b; background:#0f1e35; }}
.lot-accordion-arrow {{ font-size:8pt; transition:transform .2s; color:#334155; }}
.lot-accordion[open] .lot-accordion-header {{ border-radius:12px 12px 0 0; }}
.lot-accordion[open] .lot-accordion-arrow {{ transform:rotate(90deg); }}
.table-wrap {{ border-radius:12px; overflow-x:auto; border:1px solid rgba(255,255,255,.06); box-shadow:0 4px 28px rgba(0,0,0,.45); margin-bottom:20px; }}
table {{ width:100%; border-collapse:collapse; background:transparent; }}
th {{ background:#09152a; color:#475569; text-align:left; padding:10px 8px; font-size:7.5pt; font-weight:700; text-transform:uppercase; letter-spacing:.8px; border-bottom:1px solid rgba(255,255,255,.06); white-space:nowrap; }}
td {{ padding:11px 8px; border-bottom:1px solid rgba(255,255,255,.035); font-size:9.5pt; background:#0b1526; color:#94a3b8; vertical-align:middle; }}
tr:nth-child(even) td {{ background:#0e1d32; }}
tr:hover td {{ background:#152338 !important; transition:background .08s; }}
.rank-num {{ color:#334155; font-weight:700; font-size:10.5pt; }}
.ticker-btn-static {{ background:#0c1a3a; border:1.5px solid #1e3a8a; color:#60a5fa; padding:5px 11px; border-radius:7px; font-weight:800; font-size:11pt; display:inline-block; white-space:nowrap; }}
.ime-podjetja {{ max-width:160px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:#475569; font-size:8.5pt; }}
.sektor-cell {{ color:#475569; font-size:8.5pt; }}
.cash-row td  {{ background:#091420 !important; }}
.total-row td {{ background:#0f2754 !important; color:#f1f5f9; font-weight:700; font-size:10pt; }}
.pos-return {{ color:#4ade80; font-weight:700; }}
.neg-return {{ color:#f87171; font-weight:700; }}
.chart-reset-btn {{ position:absolute; top:8px; right:8px; background:#1e293b; color:#64748b; border:1px solid #334155; padding:4px 10px; border-radius:4px; font-size:8pt; cursor:pointer; z-index:10; font-family:'Segoe UI',Arial,sans-serif; transition:.15s; }}
.chart-reset-btn:hover {{ background:#334155; color:#94a3b8; }}
.legend-row {{ display:flex; gap:20px; margin-bottom:10px; font-size:9pt; color:#64748b; align-items:center; flex-wrap:wrap; }}
.legend-dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:5px; }}
</style>
</head>
<body>
<div class="page-wrap">

<div class="header">
    <h1>OGM VIRTUAL PORTFOLIO &mdash; LIVE TRACKER</h1>
    <p>Začetni kapital: $50,000 &nbsp;&bull;&nbsp; Retroaktivni nakupi od {chart_start} &nbsp;&bull;&nbsp; S&amp;P 500 &amp; NASDAQ 100 &nbsp;&bull;&nbsp; Osveženo: {datum_danes}</p>
</div>

<div class="stats-grid">
    <div class="stat-card">
        <div class="stat-lbl">OGM Portfolio Vrednost (pozicije + gotovina)</div>
        <div class="stat-val val-blue">${total_portfolio_v:,.2f}</div>
        <div class="stat-sub {sign_cls(portfolio_return_pct)}">{fmt_pct(portfolio_return_pct)} od začetka &nbsp;&bull;&nbsp; P&amp;L: {fmt_dollar(total_pnl)}</div>
    </div>
    <div class="stat-card">
        <div class="stat-lbl">S&amp;P 500 (enaka investicija $50k)</div>
        <div class="stat-val val-white">${sp_final:,.2f}</div>
        <div class="stat-sub {sign_cls(sp500_return_pct)}">{fmt_pct(sp500_return_pct)} od {chart_start}</div>
    </div>
    <div class="stat-card">
        <div class="stat-lbl">NASDAQ 100 (enaka investicija $50k)</div>
        <div class="stat-val val-white">${ndx_final:,.2f}</div>
        <div class="stat-sub {sign_cls(ndx_return_pct)}">{fmt_pct(ndx_return_pct)} od {chart_start}</div>
    </div>
</div>

<div class="two-col">
    <div class="chart-wrap">
        <h3>Krivulja Rasti &mdash; OGM Portfolio vs S&amp;P 500 vs NASDAQ 100</h3>
        <div class="legend-row">
            <span><span class="legend-dot" style="background:#38bdf8;"></span>OGM Portfolio (pozicije + gotovina)</span>
            <span><span class="legend-dot" style="background:#f87171;"></span>S&amp;P 500 ($50k)</span>
            <span><span class="legend-dot" style="background:#a78bfa;"></span>NASDAQ 100 ($50k)</span>
        </div>
        <div class="chart-container" style="position:relative;">
            <canvas id="perfChart"></canvas>
            <button class="chart-reset-btn" id="resetBtn">&#x21BA; Reset Zoom</button>
        </div>
        <div class="chart-hint">&#x2194; Drži in vleci za premikanje &nbsp;&middot;&nbsp; &#x1F6DE; Kolešček za zoom &nbsp;&middot;&nbsp; Dvoklik za ponastavitev</div>
    </div>
    <div class="chart-wrap">
        <h3>Alokacija Portfelja</h3>
        <div class="alloc-container">
            <canvas id="allocChart"></canvas>
        </div>
    </div>
</div>

<div class="section-title">Odprte Pozicije &mdash; Povzetek po Delnicah</div>
<div class="table-wrap">
<table>
    <thead>
        <tr>
            <th>#</th><th>Ticker</th><th>Podjetje</th><th>Sektor</th>
            <th>Avg Nakup</th><th>Trenutna Cena</th><th>Delnice</th>
            <th>Vrednost</th><th>P&amp;L</th><th>YTD</th><th>Utež</th><th>1. Nakup</th>
        </tr>
    </thead>
    <tbody>
        {holdings_rows}
        <tr class="cash-row">
            <td></td>
            <td><span class="ticker-btn-static" style="color:#94a3b8;border-color:#334155;">CASH</span></td>
            <td colspan="5" style="color:#475569;">Razpoložljiva gotovina</td>
            <td style="color:#94a3b8;font-weight:700;">${portfolio['cash']:,.2f}</td>
            <td>—</td><td>—</td>
            <td style="color:#64748b;">{cash_weight}%</td><td>—</td>
        </tr>
        <tr class="total-row">
            <td colspan="7" style="text-align:right;padding-right:16px;">SKUPAJ PORTFOLIO</td>
            <td>${total_portfolio_v:,.2f}</td>
            <td class="{sign_cls(total_pnl)}">{fmt_dollar(total_pnl)}<br><span style="font-size:8pt;">{fmt_pct(total_pnl_pct)}</span></td>
            <td>—</td><td>100%</td><td>—</td>
        </tr>
    </tbody>
</table>
</div>

<details class="lot-accordion">
    <summary class="lot-accordion-header">
        Zgodovina Lotov &mdash; Odprti &amp; Zaprti
        <span class="lot-accordion-arrow">&#9654;</span>
    </summary>
    <div class="table-wrap" style="margin-top:0;border-top-left-radius:0;border-top-right-radius:0;">
    <table>
        <thead>
            <tr>
                <th>Datum nakupa</th><th>Datum prodaje</th><th>Ticker</th>
                <th>Nakupna Cena</th><th>Prodajna / Tržna Cena</th>
                <th>Delnice</th><th>Investirano</th><th>Vrednost / Izkupiček</th><th>P&amp;L</th><th>Status</th>
            </tr>
        </thead>
        <tbody>{lot_rows}</tbody>
    </table>
    </div>
</details>

<div class="section-title">Letna Primerjava Donosov</div>
<div class="table-wrap">
<table>
    <thead>
        <tr>
            <th>Leto</th><th>OGM Portfolio</th><th>S&amp;P 500</th>
            <th>NASDAQ 100</th><th>Razlika OGM vs S&amp;P500</th>
        </tr>
    </thead>
    <tbody>{yearly_rows}</tbody>
</table>
</div>

</div>
<script>
const chartData = {chart_json};
const allocData = {alloc_json};
let   perfChart = null;

(function() {{
    const ctx = document.getElementById('perfChart').getContext('2d');
    perfChart = new Chart(ctx, {{
        type:'line',
        data:{{
            labels: chartData.labels,
            datasets:[
                {{ label:'OGM Portfolio ($)', data:chartData.portfolio, borderColor:'#38bdf8', backgroundColor:'rgba(56,189,248,.08)', borderWidth:2.5, pointRadius:0, fill:true,  tension:0.1 }},
                {{ label:'S&P 500 ($)',       data:chartData.sp500,     borderColor:'#f87171', borderWidth:1.8, pointRadius:0, borderDash:[5,4], fill:false, tension:0.1 }},
                {{ label:'NASDAQ 100 ($)',    data:chartData.ndx,       borderColor:'#a78bfa', borderWidth:1.8, pointRadius:0, borderDash:[3,5], fill:false, tension:0.1 }}
            ]
        }},
        options:{{
            responsive:true, maintainAspectRatio:false,
            interaction:{{ mode:'index', intersect:false }},
            scales:{{
                x:{{ ticks:{{ maxTicksLimit:12, color:'#475569', font:{{size:9}} }}, grid:{{ color:'rgba(255,255,255,.03)' }} }},
                y:{{ ticks:{{ color:'#475569', font:{{size:9}}, callback: v => '$' + v.toLocaleString() }}, grid:{{ color:'rgba(255,255,255,.05)' }} }}
            }},
            plugins:{{
                legend:{{ position:'top', labels:{{ color:'#94a3b8', boxWidth:12, font:{{size:9}} }} }},
                zoom:{{ zoom:{{ wheel:{{ enabled:true }}, pinch:{{ enabled:true }}, mode:'x' }},
                        pan:{{ enabled:false }} }}
            }}
        }}
    }});
    const canvas = document.getElementById('perfChart');
    document.getElementById('resetBtn').onclick = () => perfChart && perfChart.resetZoom();
    canvas.addEventListener('dblclick', () => perfChart && perfChart.resetZoom());

    // ── Manual drag-to-pan (copied from A18 — works reliably) ──
    (function() {{
        var dragActive = false;
        var dragStartX = 0;
        var rangeAtStart = null;

        canvas.addEventListener('mousedown', function(e) {{
            if (e.button !== 0 || !perfChart) return;
            var xScale = perfChart.scales.x;
            var totalLen = perfChart.data.labels.length;
            var curMin = (xScale.min !== undefined && xScale.min !== null) ? xScale.min : 0;
            var curMax = (xScale.max !== undefined && xScale.max !== null) ? xScale.max : totalLen - 1;
            var visibleRange = curMax - curMin;
            // Only pan when zoomed in (at least 5% zoom applied)
            if (visibleRange >= totalLen * 0.97) return;
            dragActive = true;
            dragStartX = e.clientX;
            rangeAtStart = {{ min: curMin, max: curMax, range: visibleRange }};
            // Suppress tooltip interaction while dragging
            perfChart.options.interaction = {{ mode: 'none', intersect: false }};
            canvas.style.cursor = 'grabbing';
            e.preventDefault();
        }});

        document.addEventListener('mousemove', function(e) {{
            if (!dragActive || !perfChart || !rangeAtStart) return;
            var xScale = perfChart.scales.x;
            var totalLen = perfChart.data.labels.length;
            var pixelWidth = xScale.right - xScale.left;
            if (pixelWidth <= 0) return;
            var pxPerUnit = pixelWidth / rangeAtStart.range;
            var delta = -(e.clientX - dragStartX) / pxPerUnit;
            var newMin = rangeAtStart.min + delta;
            var newMax = rangeAtStart.max + delta;
            // Clamp to data bounds
            if (newMin < 0) {{ newMin = 0; newMax = rangeAtStart.range; }}
            if (newMax > totalLen - 1) {{ newMax = totalLen - 1; newMin = newMax - rangeAtStart.range; }}
            perfChart.options.scales.x.min = newMin;
            perfChart.options.scales.x.max = newMax;
            perfChart.update('none');
        }});

        document.addEventListener('mouseup', function() {{
            if (!dragActive) return;
            dragActive = false;
            rangeAtStart = null;
            if (perfChart) {{
                // Restore tooltip interaction
                perfChart.options.interaction = {{ mode: 'index', intersect: false }};
                canvas.style.cursor = 'grab';
            }}
        }});
    }})();
}})();

(function() {{
    const COLORS = ['#38bdf8','#4ade80','#f97316','#a78bfa','#fb7185','#facc15','#34d399','#60a5fa','#f472b6','#94a3b8','#fbbf24','#6ee7b7'];
    const ctx = document.getElementById('allocChart').getContext('2d');
    new Chart(ctx, {{
        type:'doughnut',
        data:{{
            labels: allocData.labels,
            datasets:[{{ data:allocData.values,
                         backgroundColor: allocData.labels.map((_,i) => COLORS[i % COLORS.length]),
                         borderColor:'#060d1a', borderWidth:2 }}]
        }},
        options:{{
            responsive:true, maintainAspectRatio:false, cutout:'62%',
            plugins:{{
                legend:{{ position:'right', labels:{{ color:'#94a3b8', font:{{size:9}}, boxWidth:12, padding:10 }} }},
                tooltip:{{ callbacks:{{ label: ctx => ctx.label + ': $' + ctx.raw.toLocaleString('en-US',{{minimumFractionDigits:2}}) }} }}
            }}
        }}
    }});
}})();
</script>
</body>
</html>"""

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\n[OK] Porocilo: {OUTPUT_FILE}")
print(f"     OGM Portfolio  : ${total_portfolio_v:,.2f}  ({fmt_pct(portfolio_return_pct)})")
print(f"     S&P 500 ($50k) : ${sp_final:,.2f}  ({fmt_pct(sp500_return_pct)})")
print(f"     NASDAQ 100     : ${ndx_final:,.2f}  ({fmt_pct(ndx_return_pct)})")

if os.environ.get("CI") != "true":
    webbrowser.open(f"file://{os.path.abspath(OUTPUT_FILE)}")
