"""
data_provider.py — Abstraktni podatkovni sloj

Vsi klici za tržne podatke gredo skozi ta modul.
Trenutno: yfinance + yahooquery
Po FMP migraciji: nastavi USE_FMP=true v .env → vsi klici gredo na fmp.py

backend.py ne kliče yfinance/yahooquery neposredno.
"""
import os, time
import pandas as pd
import yfinance as yf

USE_FMP = os.getenv("USE_FMP", "false").lower() == "true"

if USE_FMP:
    import fmp as _fmp


# ═══════════════════════════════════════════════════════════════════════════════
# FUNDAMENTALI
# ═══════════════════════════════════════════════════════════════════════════════

def get_info(ticker: str) -> dict:
    """
    Vrne dict fundamentalov za delnico (kompatibilen z yfinance .info).
    Polja: marketCap, grossMargins, earningsQuarterlyGrowth, earningsGrowth,
           pegRatio, revenueGrowth, shortName, sector, industry, website,
           longBusinessSummary, freeCashflow, totalRevenue ...
    """
    if USE_FMP:
        return _fmp.get_fundamentals(ticker)
    try:
        return yf.Ticker(ticker.upper()).info or {}
    except Exception:
        return {}


def get_scanner_fundamentals(
    tickers: list[str],
    min_mcap: float = 0,
    min_rev_growth: float = 0,
    progress_cb=None,
) -> list[dict]:
    """
    Phase 1 skeniranja: fundamentali za seznam tickerjev.
    Vrne seznam kandidatov s standardiziranimi polji.
    progress_cb(done, total) — opcijski callback za progress bar.

    Standardizirana polja v vsakem rezultatu:
      ticker, mcap, rev_growth, gross_margin, eps_growth,
      peg, short_name, sector, target_price
    """
    if USE_FMP:
        return _fmp_scanner_fundamentals(min_mcap, min_rev_growth, progress_cb)
    return _yq_scanner_fundamentals(tickers, min_mcap, min_rev_growth, progress_cb)


def _yq_scanner_fundamentals(tickers, min_mcap, min_rev_growth, progress_cb):
    """Yahooquery batch implementacija Phase 1."""
    from yahooquery import Ticker as YQTicker

    def _yqv(d, *keys):
        if not isinstance(d, dict):
            return None
        for k in keys:
            v = d.get(k)
            if v is None:
                continue
            try:
                if not pd.isna(v):
                    return v
            except Exception:
                return v
        return None

    def _s(v):
        try:
            return float(v) if v is not None and not pd.isna(v) else 0.0
        except Exception:
            return 0.0

    YQ_BATCH  = 50
    candidates = []
    total      = len(tickers)

    for pi in range(0, total, YQ_BATCH):
        batch = tickers[pi:pi + YQ_BATCH]
        if progress_cb:
            progress_cb(pi + len(batch), total)
        try:
            yq   = YQTicker(batch, validate=False)
            _fin = yq.financial_data
            _sum = yq.summary_detail
            _kst = yq.key_stats
            _qt  = yq.quote_type
            _ap  = yq.asset_profile
            for tk in batch:
                fd = _fin.get(tk) if isinstance(_fin, dict) else {}
                sd = _sum.get(tk) if isinstance(_sum, dict) else {}
                ks = _kst.get(tk) if isinstance(_kst, dict) else {}
                q  = _qt.get(tk)  if isinstance(_qt,  dict) else {}
                a  = _ap.get(tk)  if isinstance(_ap,  dict) else {}
                for d in (fd, sd, ks, q, a):
                    if not isinstance(d, dict):
                        d = {}
                mc = _yqv(sd, "marketCap") or _yqv(ks, "marketCap")
                if not mc or mc < min_mcap:
                    continue
                rg_raw = _yqv(fd, "revenueGrowth")
                rg = _s(rg_raw)
                # only filter confirmed negative growth; missing data (None) passes through
                if rg_raw is not None and rg <= 0:
                    continue
                candidates.append({
                    "ticker":       tk,
                    "mcap":         mc,
                    "rev_growth":   rg if rg_raw is not None else None,
                    "gross_margin": _s(_yqv(fd, "grossMargins")),
                    "eps_growth":   _s(_yqv(ks, "earningsQuarterlyGrowth") or _yqv(fd, "earningsGrowth")),
                    "peg":          _s(_yqv(ks, "pegRatio")),
                    "short_name":   _yqv(q, "shortName", "longName") or tk,
                    "sector":       _yqv(a, "sector") or "N/A",
                    "target_price": _s(_yqv(fd, "targetMeanPrice")),
                })
        except Exception as e:
            print(f"[DP] YQ batch {pi // YQ_BATCH}: {e}")
        time.sleep(0.3)

    return candidates


def _fmp_scanner_fundamentals(min_mcap, min_rev_growth, progress_cb):
    """FMP screener + per-ticker implementacija Phase 1."""
    tickers = _fmp.get_screener(min_mcap=max(min_mcap, 500_000_000))
    total   = len(tickers)
    candidates = []

    for i, tk in enumerate(tickers, 1):
        if progress_cb:
            progress_cb(i, total)
        try:
            info = _fmp.get_fundamentals(tk)
            mc   = info.get("marketCap") or 0
            rg   = info.get("revenueGrowth") or 0.0
            if mc < min_mcap or rg < min_rev_growth:
                continue
            candidates.append({
                "ticker":       tk,
                "mcap":         mc,
                "rev_growth":   rg,
                "gross_margin": info.get("grossMargins") or 0.0,
                "eps_growth":   info.get("earningsQuarterlyGrowth") or info.get("earningsGrowth") or 0.0,
                "peg":          info.get("pegRatio") or 0.0,
                "short_name":   info.get("shortName") or tk,
                "sector":       info.get("sector") or "N/A",
                "target_price": 0.0,   # FMP: dodati TargetPrice endpoint
            })
        except Exception as e:
            print(f"[DP] FMP fundamentals {tk}: {e}")

    return candidates


# ═══════════════════════════════════════════════════════════════════════════════
# CENOVNI HISTORY
# ═══════════════════════════════════════════════════════════════════════════════

def get_history_weekly(
    ticker: str,
    start: str = "2010-01-01",
    end: str | None = None,
) -> pd.DataFrame:
    """
    Tedenski OHLCV za dani ticker.
    Vrne DataFrame z DatetimeIndex (brez timezone) in stolpci Open/High/Low/Close/Volume.
    """
    if USE_FMP:
        return _fmp.get_history_weekly(ticker, start)
    try:
        kwargs = dict(start=start, interval="1wk", actions=False, auto_adjust=True)
        if end:
            kwargs["end"] = end
        data = yf.Ticker(ticker.upper()).history(**kwargs)
        if data is None or data.empty:
            return pd.DataFrame()
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        if hasattr(data.index, "tz") and data.index.tz is not None:
            data.index = data.index.tz_localize(None)
        return data
    except Exception as e:
        print(f"[DP] history_weekly {ticker}: {e}")
        return pd.DataFrame()


def get_history_daily(
    ticker: str,
    start: str | None = None,
    end:   str | None = None,
    period: str | None = None,
) -> pd.DataFrame:
    """
    Dnevni OHLCV. Podpira start/end ali period ('5d', '1mo', ...).
    """
    if USE_FMP:
        return _fmp.get_history_daily(ticker, start, end, period)
    try:
        kwargs: dict = dict(interval="1d", actions=False, auto_adjust=True)
        if period:
            kwargs["period"] = period
        else:
            kwargs["start"] = start or "2020-01-01"
            if end:
                kwargs["end"] = end
        data = yf.Ticker(ticker.upper()).history(**kwargs)
        if data is None or data.empty:
            return pd.DataFrame()
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        if hasattr(data.index, "tz") and data.index.tz is not None:
            data.index = data.index.tz_localize(None)
        return data
    except Exception as e:
        print(f"[DP] history_daily {ticker}: {e}")
        return pd.DataFrame()


def get_history_weekly_batch(
    tickers: list[str],
    start: str,
) -> dict[str, pd.Series]:
    """
    Batch tedenski history za več tickerjev hkrati (portfolio chart).
    Vrne {ticker: Series(Close)}.
    """
    if USE_FMP:
        out: dict[str, pd.Series] = {}
        for tk in tickers:
            df = _fmp.get_history_weekly(tk, start)
            if not df.empty:
                out[tk] = df["Close"].dropna()
        return out

    result: dict[str, pd.Series] = {}
    for tk in tickers:
        try:
            h = yf.Ticker(tk).history(start=start, interval="1wk",
                                       auto_adjust=True, actions=False)
            if h.empty:
                continue
            if isinstance(h.columns, pd.MultiIndex):
                h.columns = h.columns.get_level_values(0)
            s = h["Close"].dropna()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            result[tk] = s
        except Exception as e:
            print(f"[DP] weekly_batch {tk}: {e}")
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE CENE
# ═══════════════════════════════════════════════════════════════════════════════

def get_live_price(ticker: str) -> float | None:
    """
    Trenutna cena za en ticker.
    Primarno: yahooquery (hitro, manj rate-limited).
    Fallback: yf.download (zanesljivo na Railway).
    """
    if USE_FMP:
        q = _fmp.get_quote_full(ticker)
        return q.get("price")

    # yahooquery primary
    try:
        from yahooquery import Ticker as YQTicker
        yqp = YQTicker(ticker.upper(), validate=False).price.get(ticker.upper())
        if isinstance(yqp, dict):
            p = yqp.get("regularMarketPrice") or yqp.get("regularMarketPreviousClose")
            if p:
                return float(p)
    except Exception:
        pass

    # yfinance fallback
    try:
        h = yf.download(ticker, period="5d", interval="1d",
                        auto_adjust=True, progress=False, multi_level_index=False)
        if not h.empty:
            return float(h["Close"].dropna().iloc[-1])
    except Exception:
        pass

    return None


def get_live_prices_batch(tickers: list[str]) -> dict[str, float]:
    """
    Batch live cene za portfolio pozicije.
    Vrne {TICKER: price}. Manjkajoči tickerji niso v dict-u.
    """
    if USE_FMP:
        return _fmp.get_quotes(tickers)

    result: dict[str, float] = {}

    # yahooquery batch (1 request za vse)
    try:
        from yahooquery import Ticker as YQTicker
        yqb  = YQTicker(tickers, validate=False)
        pmap = yqb.price
        if isinstance(pmap, dict):
            for tk in tickers:
                pd_ = pmap.get(tk)
                if isinstance(pd_, dict):
                    p = pd_.get("regularMarketPrice") or pd_.get("regularMarketPreviousClose")
                    if p:
                        result[tk] = float(p)
    except Exception as e:
        print(f"[DP] YQ batch price: {e}")

    # yfinance fallback za manjkajoče
    for tk in [t for t in tickers if t not in result]:
        try:
            h = yf.Ticker(tk).history(period="5d", interval="1d", auto_adjust=True)
            if not h.empty:
                if isinstance(h.columns, pd.MultiIndex):
                    h.columns = h.columns.get_level_values(0)
                result[tk] = float(h["Close"].dropna().iloc[-1])
        except Exception:
            pass

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# EARNINGS CALENDAR
# ═══════════════════════════════════════════════════════════════════════════════

def get_earnings_calendar(from_date: str, to_date: str) -> list[dict]:
    """
    Earnings calendar za dano obdobje.
    Vrne seznam diktov: ticker, company, date, eps_est, rev_est, market_cap.
    """
    if USE_FMP:
        return _fmp.get_earnings_calendar(from_date, to_date)

    # yfinance nima direktnega range calendar — vrnemo prazen seznam
    # (yfinance calendar dela samo za posamezno delnico, ne za range)
    return []


def get_ticker_calendar(ticker: str) -> dict:
    """
    Earnings calendar za en ticker (naslednji earnings datum, EPS estimate).
    """
    if USE_FMP:
        # Za FMP: poiščemo v earnings_calendar za naslednjih 60 dni
        from datetime import date, timedelta
        today = date.today().isoformat()
        end   = (date.today() + timedelta(days=60)).isoformat()
        events = _fmp.get_earnings_calendar(today, end)
        for e in events:
            if str(e.get("ticker", "")).upper() == ticker.upper():
                return e
        return {}
    try:
        cal = yf.Ticker(ticker.upper()).calendar or {}
        return cal
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# TICKER UNIVERSE (za scanner)
# ═══════════════════════════════════════════════════════════════════════════════

def load_ticker_universe(csv_file: str) -> list[str]:
    """
    Naloži seznam tickerjev za skeniranje.
    yfinance način: bere iz CSV datoteke.
    FMP način: FMP screener (csv_file se ignorira).
    """
    if USE_FMP:
        # FMP: screener znotraj get_scanner_fundamentals, tukaj vrnemo prazen seznam
        return []
    import os
    if not os.path.exists(csv_file):
        print(f"[DP] CSV not found: {csv_file}")
        return []
    try:
        return (pd.read_csv(csv_file)["Ticker"]
                .dropna().astype(str).str.strip().tolist())
    except Exception as e:
        print(f"[DP] load_ticker_universe: {e}")
        return []
