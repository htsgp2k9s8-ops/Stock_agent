"""
OGM Stock Scanner — FastAPI Backend
────────────────────────────────────
Install:  pip install fastapi uvicorn[standard]
Run:      uvicorn backend:app --reload --port 8000
Docs:     http://localhost:8000/docs

Endpoints:
  GET  /                      health + cache status
  GET  /api/results           all scored stocks (sorted by OGM)
  GET  /api/stock/{ticker}    full chart + detail data for one stock
  GET  /api/sectors           sector ETF comparison
  GET  /api/scan/status       is a scan running? when last ran?
  POST /api/scan              trigger a new background scan
                              optional query param: ?date=2024-01-15
"""

from __future__ import annotations

import json
import os
import threading
import time
import json
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ─── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="OGM Scanner API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restrict to your domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Constants (must match A18) ───────────────────────────────────────────────
CSV_FILE          = "moje_globalne_delnice.csv"
MIN_MARKET_CAP    = 20_000_000_000
MEGA_CAP          = 200_000_000_000
MIN_REV_GROWTH    = 0.10
SUPER_GROWTH      = 0.50
CACHE_FILE        = "ogm_cache.json"

POSTS_FILE        = "ogm_posts.json"
ADMIN_PASSWORD    = os.environ.get("OGM_ADMIN_PASSWORD", "ogm2026")

# ─── Posts storage ────────────────────────────────────────────────────────────
def _load_posts() -> list:
    if Path(POSTS_FILE).exists():
        try:
            return json.loads(Path(POSTS_FILE).read_text(encoding="utf-8")).get("posts", [])
        except Exception:
            pass
    return []

def _save_posts(posts: list) -> None:
    Path(POSTS_FILE).write_text(json.dumps({"posts": posts}, ensure_ascii=False, indent=2), encoding="utf-8")

class PostIn(BaseModel):
    password: str
    title: str
    content: str
    category: str = "Analysis"
    author: str = "OGM Team"

class DeleteIn(BaseModel):
    password: str

SECTOR_ETF_MAP = {
    "Technology":             "XLK",
    "Financial Services":     "XLF",
    "Communication Services": "XLC",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    "Healthcare":             "XLV",
    "Energy":                 "XLE",
    "Utilities":              "XLU",
    "Real Estate":            "XLRE",
    "Basic Materials":        "XLB",
    "Industrials":            "XLI",
}

SECTOR_STOCKS: dict[str, list[str]] = {
    "Technology":             ["AAPL","MSFT","NVDA","AVGO","AMD","ORCL","ADBE","CRM","QCOM","INTC"],
    "Financial Services":     ["BRK-B","JPM","V","MA","BAC","WFC","GS","MS","AXP","BLK"],
    "Communication Services": ["GOOG","META","NFLX","DIS","CMCSA","T","VZ","TMUS","CHTR","EA"],
    "Consumer Cyclical":      ["AMZN","TSLA","HD","MCD","NKE","LOW","SBUX","TJX","BKNG","ABNB"],
    "Consumer Defensive":     ["WMT","PG","KO","PEP","COST","PM","MO","CL","GIS","KMB"],
    "Healthcare":             ["LLY","UNH","JNJ","ABT","TMO","DHR","MRK","AMGN","ISRG","SYK"],
    "Energy":                 ["XOM","CVX","COP","EOG","SLB","MPC","VLO","PSX","OXY","HES"],
    "Utilities":              ["NEE","SO","DUK","AEP","XEL","SRE","WEC","ED","EXC","PCG"],
    "Real Estate":            ["PLD","AMT","EQIX","SPG","WELL","DLR","O","CCI","PSA","SBAC"],
    "Basic Materials":        ["LIN","APD","SHW","FCX","ECL","NEM","VMC","MLM","CF","DOW"],
    "Industrials":            ["GE","CAT","UNP","RTX","LMT","HON","BA","DE","UPS","ETN"],
}

_sector_stocks_cache: dict = {}

# ─── Calendar ─────────────────────────────────────────────────────────────────

_CALENDAR_TICKERS: list[str] = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","BRK-B",
    "AMD","ORCL","ADBE","CRM","QCOM","INTC","MU","PANW","CRWD","DDOG","NET","PLTR",
    "JPM","V","MA","BAC","WFC","GS","MS","AXP","BLK","SCHW","C",
    "LLY","UNH","JNJ","ABT","TMO","MRK","AMGN","ISRG","SYK",
    "HD","MCD","NKE","SBUX","BKNG","COST","WMT","TJX","ABNB",
    "NFLX","DIS","CMCSA","SPOT","ROKU",
    "XOM","CVX","COP","SLB","MPC",
    "GE","CAT","UNP","RTX","LMT","HON","BA","DE","UPS","FDX",
    "MELI","SHOP","PYPL","COIN","HOOD","IBKR","SPGI","CME",
    "KO","PEP","PG","PM","MO","GIS",
    "PLD","AMT","EQIX","NEE","SO",
    "LIN","SHW","FCX","DOW",
    "SNPS","CDNS","TXN","AMAT","LRCX","KLAC","ADI","MRVL",
]

_TICKER_NAMES: dict[str, str] = {
    "AAPL":"Apple Inc.","MSFT":"Microsoft Corp.","NVDA":"NVIDIA Corp.",
    "AMZN":"Amazon.com Inc.","META":"Meta Platforms","GOOGL":"Alphabet Inc.",
    "TSLA":"Tesla Inc.","AVGO":"Broadcom Inc.","BRK-B":"Berkshire Hathaway",
    "AMD":"Advanced Micro Devices","ORCL":"Oracle Corp.","ADBE":"Adobe Inc.",
    "CRM":"Salesforce Inc.","QCOM":"Qualcomm Inc.","INTC":"Intel Corp.",
    "MU":"Micron Technology","PANW":"Palo Alto Networks","CRWD":"CrowdStrike",
    "DDOG":"Datadog Inc.","NET":"Cloudflare Inc.","PLTR":"Palantir Technologies",
    "JPM":"JPMorgan Chase","V":"Visa Inc.","MA":"Mastercard Inc.",
    "BAC":"Bank of America","WFC":"Wells Fargo","GS":"Goldman Sachs",
    "MS":"Morgan Stanley","AXP":"American Express","BLK":"BlackRock Inc.",
    "SCHW":"Charles Schwab","C":"Citigroup Inc.",
    "LLY":"Eli Lilly and Co.","UNH":"UnitedHealth Group","JNJ":"Johnson & Johnson",
    "ABT":"Abbott Laboratories","TMO":"Thermo Fisher Scientific","MRK":"Merck & Co.",
    "AMGN":"Amgen Inc.","ISRG":"Intuitive Surgical","SYK":"Stryker Corp.",
    "HD":"Home Depot","MCD":"McDonald's Corp.","NKE":"Nike Inc.",
    "SBUX":"Starbucks Corp.","BKNG":"Booking Holdings","COST":"Costco Wholesale",
    "WMT":"Walmart Inc.","TJX":"TJX Companies","ABNB":"Airbnb Inc.",
    "NFLX":"Netflix Inc.","DIS":"Walt Disney Co.","CMCSA":"Comcast Corp.",
    "SPOT":"Spotify Technology","ROKU":"Roku Inc.",
    "XOM":"Exxon Mobil","CVX":"Chevron Corp.","COP":"ConocoPhillips",
    "SLB":"SLB (Schlumberger)","MPC":"Marathon Petroleum",
    "GE":"GE Aerospace","CAT":"Caterpillar Inc.","UNP":"Union Pacific",
    "RTX":"RTX Corp.","LMT":"Lockheed Martin","HON":"Honeywell Intl.",
    "BA":"Boeing Co.","DE":"Deere & Co.","UPS":"United Parcel Service","FDX":"FedEx Corp.",
    "MELI":"MercadoLibre","SHOP":"Shopify Inc.","PYPL":"PayPal Holdings",
    "COIN":"Coinbase Global","HOOD":"Robinhood Markets","IBKR":"Interactive Brokers",
    "SPGI":"S&P Global Inc.","CME":"CME Group Inc.",
    "KO":"Coca-Cola Co.","PEP":"PepsiCo Inc.","PG":"Procter & Gamble",
    "PM":"Philip Morris Intl.","MO":"Altria Group","GIS":"General Mills",
    "PLD":"Prologis Inc.","AMT":"American Tower","EQIX":"Equinix Inc.",
    "NEE":"NextEra Energy","SO":"Southern Co.",
    "LIN":"Linde plc","SHW":"Sherwin-Williams","FCX":"Freeport-McMoRan","DOW":"Dow Inc.",
    "SNPS":"Synopsys Inc.","CDNS":"Cadence Design Systems","TXN":"Texas Instruments",
    "AMAT":"Applied Materials","LRCX":"Lam Research","KLAC":"KLA Corp.",
    "ADI":"Analog Devices","MRVL":"Marvell Technology",
    # Communication
    "GOOG":"Alphabet Inc.","T":"AT&T Inc.","VZ":"Verizon Comm.","TMUS":"T-Mobile US",
    "CHTR":"Charter Comm.","EA":"Electronic Arts",
    # Consumer Cyclical
    "LOW":"Lowe's Companies",
    # Consumer Defensive
    "CL":"Colgate-Palmolive","KMB":"Kimberly-Clark",
    # Healthcare
    "DHR":"Danaher Corp.",
    # Energy
    "EOG":"EOG Resources","VLO":"Valero Energy","PSX":"Phillips 66",
    "OXY":"Occidental Petroleum","HES":"Hess Corp.",
    # Utilities
    "DUK":"Duke Energy","AEP":"American Electric Power","XEL":"Xcel Energy",
    "SRE":"Sempra Energy","WEC":"WEC Energy Group","ED":"Consolidated Edison",
    "EXC":"Exelon Corp.","PCG":"PG&E Corp.",
    # Real Estate
    "SPG":"Simon Property Group","WELL":"Welltower Inc.","DLR":"Digital Realty",
    "O":"Realty Income Corp.","PSA":"Public Storage","SBAC":"SBA Comm.",
    # Basic Materials
    "APD":"Air Products & Chem.","ECL":"Ecolab Inc.","NEM":"Newmont Corp.",
    "VMC":"Vulcan Materials","MLM":"Martin Marietta","CF":"CF Industries",
    # Industrials
    "ETN":"Eaton Corp.",
}

_ECONOMIC_EVENTS: list[dict] = [
    # FOMC Rate Decisions 2026
    {"date":"2026-01-28","time":"20:00","name":"FOMC Rate Decision","importance":"high","category":"central_bank"},
    {"date":"2026-03-18","time":"20:00","name":"FOMC Rate Decision","importance":"high","category":"central_bank"},
    {"date":"2026-05-06","time":"20:00","name":"FOMC Rate Decision","importance":"high","category":"central_bank"},
    {"date":"2026-06-17","time":"20:00","name":"FOMC Rate Decision","importance":"high","category":"central_bank"},
    {"date":"2026-07-29","time":"20:00","name":"FOMC Rate Decision","importance":"high","category":"central_bank"},
    {"date":"2026-09-16","time":"20:00","name":"FOMC Rate Decision","importance":"high","category":"central_bank"},
    {"date":"2026-11-04","time":"20:00","name":"FOMC Rate Decision","importance":"high","category":"central_bank"},
    {"date":"2026-12-16","time":"20:00","name":"FOMC Rate Decision","importance":"high","category":"central_bank"},
    # CPI (US Bureau of Labor Statistics)
    {"date":"2026-01-14","time":"14:30","name":"CPI YoY — Dec 2025","importance":"high","category":"inflation"},
    {"date":"2026-02-11","time":"14:30","name":"CPI YoY — Jan 2026","importance":"high","category":"inflation"},
    {"date":"2026-03-11","time":"14:30","name":"CPI YoY — Feb 2026","importance":"high","category":"inflation"},
    {"date":"2026-04-10","time":"14:30","name":"CPI YoY — Mar 2026","importance":"high","category":"inflation"},
    {"date":"2026-05-12","time":"14:30","name":"CPI YoY — Apr 2026","importance":"high","category":"inflation"},
    {"date":"2026-06-10","time":"14:30","name":"CPI YoY — May 2026","importance":"high","category":"inflation"},
    {"date":"2026-07-15","time":"14:30","name":"CPI YoY — Jun 2026","importance":"high","category":"inflation"},
    {"date":"2026-08-12","time":"14:30","name":"CPI YoY — Jul 2026","importance":"high","category":"inflation"},
    {"date":"2026-09-10","time":"14:30","name":"CPI YoY — Aug 2026","importance":"high","category":"inflation"},
    {"date":"2026-10-14","time":"14:30","name":"CPI YoY — Sep 2026","importance":"high","category":"inflation"},
    {"date":"2026-11-12","time":"14:30","name":"CPI YoY — Oct 2026","importance":"high","category":"inflation"},
    {"date":"2026-12-10","time":"14:30","name":"CPI YoY — Nov 2026","importance":"high","category":"inflation"},
    # Non-Farm Payrolls
    {"date":"2026-01-09","time":"14:30","name":"Non-Farm Payrolls — Dec 2025","importance":"high","category":"employment"},
    {"date":"2026-02-06","time":"14:30","name":"Non-Farm Payrolls — Jan 2026","importance":"high","category":"employment"},
    {"date":"2026-03-06","time":"14:30","name":"Non-Farm Payrolls — Feb 2026","importance":"high","category":"employment"},
    {"date":"2026-04-03","time":"14:30","name":"Non-Farm Payrolls — Mar 2026","importance":"high","category":"employment"},
    {"date":"2026-05-08","time":"14:30","name":"Non-Farm Payrolls — Apr 2026","importance":"high","category":"employment"},
    {"date":"2026-06-05","time":"14:30","name":"Non-Farm Payrolls — May 2026","importance":"high","category":"employment"},
    {"date":"2026-07-09","time":"14:30","name":"Non-Farm Payrolls — Jun 2026","importance":"high","category":"employment"},
    {"date":"2026-08-07","time":"14:30","name":"Non-Farm Payrolls — Jul 2026","importance":"high","category":"employment"},
    {"date":"2026-09-04","time":"14:30","name":"Non-Farm Payrolls — Aug 2026","importance":"high","category":"employment"},
    {"date":"2026-10-02","time":"14:30","name":"Non-Farm Payrolls — Sep 2026","importance":"high","category":"employment"},
    {"date":"2026-11-06","time":"14:30","name":"Non-Farm Payrolls — Oct 2026","importance":"high","category":"employment"},
    {"date":"2026-12-04","time":"14:30","name":"Non-Farm Payrolls — Nov 2026","importance":"high","category":"employment"},
    # Core PCE (Fed preferred inflation gauge)
    {"date":"2026-01-30","time":"14:30","name":"Core PCE Price Index — Dec 2025","importance":"high","category":"inflation"},
    {"date":"2026-02-27","time":"14:30","name":"Core PCE Price Index — Jan 2026","importance":"high","category":"inflation"},
    {"date":"2026-03-27","time":"14:30","name":"Core PCE Price Index — Feb 2026","importance":"high","category":"inflation"},
    {"date":"2026-04-30","time":"14:30","name":"Core PCE Price Index — Mar 2026","importance":"high","category":"inflation"},
    {"date":"2026-05-29","time":"14:30","name":"Core PCE Price Index — Apr 2026","importance":"high","category":"inflation"},
    {"date":"2026-06-26","time":"14:30","name":"Core PCE Price Index — May 2026","importance":"high","category":"inflation"},
    {"date":"2026-07-31","time":"14:30","name":"Core PCE Price Index — Jun 2026","importance":"high","category":"inflation"},
    {"date":"2026-08-28","time":"14:30","name":"Core PCE Price Index — Jul 2026","importance":"high","category":"inflation"},
    {"date":"2026-09-25","time":"14:30","name":"Core PCE Price Index — Aug 2026","importance":"high","category":"inflation"},
    {"date":"2026-10-30","time":"14:30","name":"Core PCE Price Index — Sep 2026","importance":"high","category":"inflation"},
    {"date":"2026-11-25","time":"14:30","name":"Core PCE Price Index — Oct 2026","importance":"high","category":"inflation"},
    {"date":"2026-12-18","time":"14:30","name":"Core PCE Price Index — Nov 2026","importance":"high","category":"inflation"},
    # GDP (BEA)
    {"date":"2026-01-29","time":"14:30","name":"GDP QoQ Q4 2025 (Advance)","importance":"high","category":"gdp"},
    {"date":"2026-02-26","time":"14:30","name":"GDP QoQ Q4 2025 (Second Est.)","importance":"medium","category":"gdp"},
    {"date":"2026-03-26","time":"14:30","name":"GDP QoQ Q4 2025 (Final)","importance":"medium","category":"gdp"},
    {"date":"2026-04-29","time":"14:30","name":"GDP QoQ Q1 2026 (Advance)","importance":"high","category":"gdp"},
    {"date":"2026-05-28","time":"14:30","name":"GDP QoQ Q1 2026 (Second Est.)","importance":"medium","category":"gdp"},
    {"date":"2026-06-25","time":"14:30","name":"GDP QoQ Q1 2026 (Final)","importance":"medium","category":"gdp"},
    {"date":"2026-07-30","time":"14:30","name":"GDP QoQ Q2 2026 (Advance)","importance":"high","category":"gdp"},
    {"date":"2026-08-27","time":"14:30","name":"GDP QoQ Q2 2026 (Second Est.)","importance":"medium","category":"gdp"},
    {"date":"2026-09-24","time":"14:30","name":"GDP QoQ Q2 2026 (Final)","importance":"medium","category":"gdp"},
    {"date":"2026-10-29","time":"14:30","name":"GDP QoQ Q3 2026 (Advance)","importance":"high","category":"gdp"},
    {"date":"2026-11-24","time":"14:30","name":"GDP QoQ Q3 2026 (Second Est.)","importance":"medium","category":"gdp"},
    {"date":"2026-12-17","time":"14:30","name":"GDP QoQ Q3 2026 (Final)","importance":"medium","category":"gdp"},
]

_cal_cache: dict    = {"earnings": [], "dividends": [], "fetched_at": None}
_cal_fetching: bool = False

# ─── In-memory cache ──────────────────────────────────────────────────────────
_cache: dict = {
    "stocks":     [],   # list of scored stock summaries
    "chart_data": {},   # full per-ticker data (dates, prices, ogm history…)
    "sectors":    {},   # sector ETF metrics
    "updated_at": None,
    "scan_date":  None,
    "scanning":   False,
    "scan_error": None,
}

# ─── Daily auto-scan scheduler ────────────────────────────────────────────────
SCAN_HOUR   = 22
SCAN_MINUTE = 30

_scheduler: dict = {
    "enabled":     True,
    "last_auto":   None,   # ISO string of last auto-run
    "next_run":    None,   # ISO string of next scheduled run
}

def _next_run_time() -> datetime:
    now = datetime.now()
    t   = now.replace(hour=SCAN_HOUR, minute=SCAN_MINUTE, second=0, microsecond=0)
    if now >= t:
        t = t.replace(day=t.day + 1)
    return t

def _scheduler_loop():
    """Background thread: fires _run_scan every day at SCAN_HOUR:SCAN_MINUTE."""
    # Pre-compute next run on startup
    _scheduler["next_run"] = _next_run_time().isoformat(timespec="seconds")
    print(f"[SCHEDULER] Daily auto-scan scheduled at {SCAN_HOUR:02d}:{SCAN_MINUTE:02d} — next: {_scheduler['next_run']}")
    while True:
        now  = datetime.now()
        next = _next_run_time()
        secs = (next - now).total_seconds()
        _scheduler["next_run"] = next.isoformat(timespec="seconds")
        # Sleep in 30-second chunks so we can handle date-change edge cases
        while (next - datetime.now()).total_seconds() > 0:
            time.sleep(min(30, max(1, (next - datetime.now()).total_seconds())))
        # Fire scan only if one is not already running
        if _scheduler["enabled"] and not _cache.get("scanning"):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            print(f"[SCHEDULER] Auto-scan triggered at {ts}")
            _scheduler["last_auto"] = datetime.now().isoformat(timespec="seconds")
            threading.Thread(target=_run_scan, args=(None,), daemon=True, name="auto-scan").start()
        # Wait a minute past the target so we don't double-fire
        time.sleep(90)


@app.on_event("startup")
def _load_cache():
    """Load previous scan results from disk and start the daily scheduler."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            _cache.update(saved)
            _cache["scanning"] = False
            # Re-apply revenue growth filter in case cache was built with old code
            before = len(_cache["stocks"])
            _cache["stocks"] = [
                s for s in _cache["stocks"]
                if (s.get("rev_growth") or 0) >= MIN_REV_GROWTH * 100
            ]
            removed = before - len(_cache["stocks"])
            print(f"[API] Cache loaded — {len(_cache['stocks'])} stocks (removed {removed} low-revgrowth)")
        except Exception as e:
            print(f"[API] Cache load failed: {e}")
    # Start daily scheduler thread
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="scheduler")
    t.start()


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def serve_dashboard():
    """Serve the dashboard HTML — works locally and via ngrok/cloud."""
    return FileResponse("dashboard.html", media_type="text/html")


@app.get("/health")
def health():
    return {
        "status":         "ok",
        "stocks_cached":  len(_cache["stocks"]),
        "updated_at":     _cache["updated_at"],
        "scanning":       _cache["scanning"],
        "scan_date":      _cache["scan_date"],
    }


@app.get("/api/results")
def get_results():
    """Returns all stocks from the latest scan, sorted by OGM score."""
    return {
        "stocks":     _cache["stocks"],
        "count":      len(_cache["stocks"]),
        "updated_at": _cache["updated_at"],
        "scan_date":  _cache["scan_date"],
    }


@app.get("/api/stock/{ticker}")
def get_stock(ticker: str):
    """Full chart + OGM detail for a single ticker (from scan cache)."""
    ticker = ticker.upper()
    data = _cache["chart_data"].get(ticker)
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"{ticker} not in cache. Run /api/scan first.",
        )
    return data


@app.get("/api/analyze/{ticker}")
def analyze_stock(ticker: str):
    """On-demand full OGM diagnostic for any ticker (like A5 script). No scan needed."""
    ticker = ticker.upper()
    try:
        t    = yf.Ticker(ticker)
        info = t.info

        mcap         = info.get("marketCap")
        rev_growth   = _safe(info.get("revenueGrowth"))
        gross_margin = _safe(info.get("grossMargins"))
        eps_growth   = _safe(info.get("earningsQuarterlyGrowth") or info.get("earningsGrowth"))
        peg          = _safe(info.get("pegRatio"))

        data = t.history(start="2014-01-01", interval="1wk", actions=False)
        if data is None or data.empty or len(data) < 52:
            raise HTTPException(404, f"Not enough price history for {ticker}")
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        close = data["Close"].dropna()

        is_mega        = bool(mcap and mcap >= MEGA_CAP)
        is_high_margin = (gross_margin * 100) >= 50.0 and not is_mega
        if is_mega:
            # Mega-Cap: primary MA je 50w, ampak score split 50/50 med 50w in 200w MA
            ma      = close.rolling(50).mean()
            ma200_  = close.rolling(200).mean()
            ma_lbl  = "50w+200w MA (Mega-Cap)"
        else:
            ma     = close.rolling(200).mean()
            ma_lbl = "200w MA (Moat)" if is_high_margin else "200w MA"

        dist_arr = ((close - ma) / ma * 100).values
        rsi_s    = _rsi_series(close)
        rsi_arr  = rsi_s.values

        W_MA, W_RSI = 40.0, 15.0
        tocke_ma = np.zeros_like(dist_arr)
        pos, neg = dist_arr >= 0, dist_arr < 0

        if is_mega:
            # 50w MA komponenta (polovica uteži)
            W_half = W_MA / 2.0
            t50 = np.zeros_like(dist_arr)
            t50[pos] = np.interp(dist_arr[pos], [0,2,8,15],    [W_half*(32/35), W_half, W_half*(15/35), 0])
            t50[neg] = np.interp(dist_arr[neg], [-40,-15,-2,0], [W_half, W_half, W_half*(34/35), W_half*(32/35)])
            # 200w MA komponenta (druga polovica uteži)
            dist200_ = ((close - ma200_) / ma200_ * 100).fillna(0).values
            p2, n2 = dist200_ >= 0, dist200_ < 0
            t200 = np.zeros_like(dist200_)
            t200[p2] = np.interp(dist200_[p2], [0,5,20,40],    [W_half*(32/35), W_half, W_half*(15/35), 0])
            t200[n2] = np.interp(dist200_[n2], [-50,-20,-5,0],  [W_half, W_half, W_half*(34/35), W_half*(32/35)])
            tocke_ma = t50 + t200
        elif is_high_margin:
            tocke_ma[pos] = np.interp(dist_arr[pos], [0,2,10,25,50],    [W_MA*(33/35), W_MA, W_MA*(22/35), W_MA*(8/35), 0])
            tocke_ma[neg] = np.interp(dist_arr[neg], [-35,-20,-15,-5,0], [0, 35, 40, 38, W_MA*(33/35)])
        else:
            tocke_ma[pos] = np.interp(dist_arr[pos], [0,2,10,25,50],  [W_MA*(33/35), W_MA, W_MA*(22/35), W_MA*(8/35), 0])
            tocke_ma[neg] = np.interp(dist_arr[neg], [-20,-10,-5,0],   [0, W_MA*(12/35), W_MA*(25/35), W_MA*(33/35)])

        tocke_rsi    = np.interp(rsi_arr, [30,45,60,70,80], [W_RSI, W_RSI*0.8, W_RSI*0.5, W_RSI*0.2, 0])
        eps_pct      = eps_growth * 100
        peg_val      = peg if peg > 0 else 2.0
        gm_pct       = gross_margin * 100
        t_eps        = float(np.interp(eps_pct,  [0.0, 8.0, 16.5, 22.0, 30.0], [0.0, 5.0, 14.0, 20.0, 20.0]))
        t_peg        = float(np.interp(peg_val,  [0.4, 0.8,  1.2,  1.6,  2.0], [15.0, 13.0, 10.0,  5.0,  0.0]))
        t_mar        = float(np.interp(gm_pct,   [25,  35,   45,   55,   65],  [0.0,  2.0,  5.0,   8.0, 10.0]))
        base         = min(45.0, t_eps + t_peg + t_mar)
        ogm_arr      = np.clip(tocke_ma + tocke_rsi + base, 0, 100)
        ogm_now      = float(ogm_arr[-1])
        price_now    = float(close.iloc[-1])
        dist_now     = float(dist_arr[-1])
        dist200_now  = float(((close - ma200_) / ma200_ * 100).iloc[-1]) if is_mega else None

        # Signal history (OGM >= 80, min 26w apart)
        signals, last_sig = [], -999
        dates_str = [d.strftime("%Y-%m-%d") for d in close.index]
        for i in range(len(ogm_arr)):
            if ogm_arr[i] >= 80.0 and (i - last_sig) > 26 and i + 52 < len(close):
                p0       = float(close.iloc[i])
                max_12m  = float(close.iloc[i:i+52].max())
                min_12m  = float(close.iloc[i:i+52].min())
                signals.append({
                    "date":         dates_str[i],
                    "price":        round(p0, 2),
                    "ogm":          round(float(ogm_arr[i]), 1),
                    "max_price_12m":round(max_12m, 2),
                    "min_price_12m":round(min_12m, 2),
                    "max_return":   round((max_12m - p0) / p0 * 100, 1),
                    "max_loss":     round((min_12m - p0) / p0 * 100, 1),
                })
                last_sig = i

        filter_issues = []
        if not mcap or mcap < MIN_MARKET_CAP:
            filter_issues.append(f"Market cap too small ({_fmt_mcap(mcap)} < $20B)")
        if rev_growth < MIN_REV_GROWTH:
            filter_issues.append(f"Revenue growth too low ({rev_growth*100:.1f}% < 10%)")
        if ogm_now < 65.0:
            filter_issues.append(f"OGM score too low ({ogm_now:.1f} < 65)")

        # ── Extended chart data (full history) ───────────────────────────
        N = len(close)   # full history for all tabs
        ma50  = close.rolling(50).mean()
        ma50_vals  = [round(v, 2) if not np.isnan(v) else None for v in ma50.values]
        ma_vals    = [round(v, 2) if not np.isnan(v) else None for v in ma.values]
        ma200_vals = ([round(v, 2) if not np.isnan(v) else None for v in ma200_.values]
                      if is_mega else None)

        # Volume (green = up day, red = down day)
        raw_vol  = data["Volume"].reindex(close.index).fillna(0) if "Volume" in data.columns else pd.Series(0, index=close.index)
        close_shift = close.shift(1)
        vol_buy  = [int(v) if float(close.iloc[i]) >= float(close_shift.iloc[i]) else 0 for i, v in enumerate(raw_vol)]
        vol_sell = [int(v) if float(close.iloc[i]) <  float(close_shift.iloc[i]) else 0 for i, v in enumerate(raw_vol)]

        # 1M / YTD returns
        donos_1m  = (price_now / float(close.iloc[-5])  - 1) * 100 if len(close) >= 5  else 0.0
        donos_ytd_val = 0.0
        ytd_idx = close.index[close.index.year == datetime.now().year]
        if len(ytd_idx) > 0:
            donos_ytd_val = (price_now / float(close.loc[ytd_idx[0]]) - 1) * 100

        # Annual returns
        annual_returns = {}
        for yr in sorted(set(close.index.year)):
            yr_d = close[close.index.year == yr]
            if len(yr_d) >= 4:
                annual_returns[str(yr)] = round((float(yr_d.iloc[-1]) / float(yr_d.iloc[0]) - 1) * 100, 1)

        # Monthly seasonality — average per month AND full year×month matrix
        monthly_avg:    dict = {}
        monthly_matrix: dict = {}
        _month_rets: dict[int, list] = {m: [] for m in range(1, 13)}

        for yr in sorted(set(close.index.year)):
            monthly_matrix[str(yr)] = {}
            for mon in range(1, 13):
                m_data = close[(close.index.year == yr) & (close.index.month == mon)]
                pm     = (mon - 1) if mon > 1 else 12
                py     = yr if mon > 1 else yr - 1
                p_data = close[(close.index.year == py) & (close.index.month == pm)]
                if len(m_data) >= 1 and len(p_data) >= 1:
                    ret = (float(m_data.iloc[-1]) / float(p_data.iloc[-1]) - 1) * 100
                    monthly_matrix[str(yr)][str(mon)] = round(ret, 1)
                    _month_rets[mon].append(ret)

        for mon in range(1, 13):
            if _month_rets[mon]:
                monthly_avg[str(mon)] = round(sum(_month_rets[mon]) / len(_month_rets[mon]), 1)

        # Fundamentals
        def _pct(v): return round(_safe(v) * 100, 1)
        fundamentals = {
            "pe_trailing":  round(_safe(info.get("trailingPE")), 2),
            "pe_forward":   round(_safe(info.get("forwardPE")), 2),
            "pb":           round(_safe(info.get("priceToBook")), 2),
            "ps":           round(_safe(info.get("priceToSalesTrailing12Months")), 2),
            "ev_ebitda":    round(_safe(info.get("enterpriseToEbitda")), 2),
            "debt_equity":  round(_safe(info.get("debtToEquity")), 2),
            "roe":          _pct(info.get("returnOnEquity")),
            "roa":          _pct(info.get("returnOnAssets")),
            "op_margin":    _pct(info.get("operatingMargins")),
            "net_margin":   _pct(info.get("profitMargins")),
            "gross_margin": _pct(info.get("grossMargins")),
            "div_yield":    round(_safe(info.get("dividendYield")) * 100, 2),
            "div_rate":     round(_safe(info.get("dividendRate")), 2),
            "beta":         round(_safe(info.get("beta")), 2),
            "eps":          round(_safe(info.get("trailingEps")), 2),
            "eps_fwd":      round(_safe(info.get("forwardEps")), 2),
            "revenue":      info.get("totalRevenue"),
            "net_income":   info.get("netIncomeToCommon"),
            "fcf":          info.get("freeCashflow"),
            "employees":    info.get("fullTimeEmployees"),
            "description":  (info.get("longBusinessSummary") or "")[:600],
            "website":      info.get("website", ""),
            "industry":     info.get("industry", ""),
            "country":      info.get("country", ""),
        }

        return {
            "ticker":         ticker,
            "ime":            info.get("shortName") or ticker,
            "sektor":         info.get("sector", "N/A"),
            "mcap":           _fmt_mcap(mcap),
            "cena":           round(price_now, 2),
            "target_price":   round(_safe(info.get("targetMeanPrice")), 2),
            "ogm":            round(ogm_now, 1),
            "dist_ma":        round(dist_now, 1),
            "dist_ma200":     round(dist200_now, 1) if dist200_now is not None else None,
            "ma_type":        ma_lbl,
            "rev_growth":     round(rev_growth * 100, 1),
            "donos_1m":       round(donos_1m, 1),
            "donos_ytd":      round(donos_ytd_val, 1),
            "rsi":            round(float(rsi_arr[-1]), 1),
            "passes_filters": len(filter_issues) == 0,
            "filter_issues":  filter_issues,
            "components": {
                "eps_pct":    round(eps_pct, 1),   "eps_score":    round(t_eps, 1),
                "peg_val":    round(peg_val, 2),   "peg_score":    round(t_peg, 1),
                "margin_pct": round(gm_pct, 1),    "margin_score": round(t_mar, 1),
                "rsi":        round(float(rsi_arr[-1]), 1), "rsi_score": round(float(tocke_rsi[-1]), 1),
                "ma_dist":    round(dist_now, 1),  "ma_score":     round(float(tocke_ma[-1]), 1),
                "ma_dist200": round(dist200_now, 1) if dist200_now is not None else None,
                "fund_total": round(base, 1),       "total":        round(ogm_now, 1),
                "ma_type":    ma_lbl,
            },
            "fundamentals":   fundamentals,
            "signals":        signals,
            "annual_returns":  annual_returns,
            "monthly_avg":     monthly_avg,
            "monthly_matrix":  monthly_matrix,
            "chart": {
                "dates":    dates_str,
                "prices":   [round(float(v), 2) if not np.isnan(v) else None for v in close.values],
                "ogm":      [round(float(v), 1) if not np.isnan(v) else None for v in ogm_arr],
                "ma":       ma_vals,
                "ma50":     ma50_vals,
                "ma200":    ma200_vals,
                "vol_buy":  vol_buy,
                "vol_sell": vol_sell,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/portfolio/chart")
def portfolio_chart():
    """Portfolio performance curve vs S&P 500 & NASDAQ 100 plus allocation breakdown."""
    if not os.path.exists(PORTFOLIO_FILE):
        raise HTTPException(404, "No portfolio found")
    with open(PORTFOLIO_FILE, encoding="utf-8") as f:
        p = json.load(f)

    positions     = p.get("positions", {})
    closed        = p.get("closed_positions", [])
    starting_cash = float(p.get("starting_cash", 50000))

    # Build sorted transaction log
    txns: list[dict] = []
    for tkr, lots in positions.items():
        for lot in lots:
            txns.append({"date": lot["open_date"], "type": "buy",  "ticker": tkr,
                         "shares": lot["shares"],  "cash_delta": -lot["invested"]})
    for c in closed:
        txns.append({"date": c["buy_date"],  "type": "buy",  "ticker": c["ticker"],
                     "shares": c["shares"],  "cash_delta": -c["invested"]})
        txns.append({"date": c["sell_date"], "type": "sell", "ticker": c["ticker"],
                     "shares": c["shares"],  "cash_delta":  c["proceeds"]})
    txns.sort(key=lambda x: x["date"])

    if not txns:
        raise HTTPException(404, "No transactions found")

    start_date = txns[0]["date"]
    tkr_set    = list(set([t["ticker"] for t in txns] + ["SPY", "QQQ"]))

    hist: dict = {}
    for tkr in tkr_set:
        try:
            h = yf.Ticker(tkr).history(start=start_date, interval="1wk", auto_adjust=True)
            if h.empty: continue
            if isinstance(h.columns, pd.MultiIndex):
                h.columns = h.columns.get_level_values(0)
            s = h["Close"].dropna()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            hist[tkr] = s
        except Exception:
            pass

    if "SPY" not in hist:
        raise HTTPException(500, "Cannot download SPY benchmark data")

    idx       = hist["SPY"].index
    dates_str = [d.strftime("%Y-%m-%d") for d in idx]

    # Replay transactions to build weekly portfolio value
    open_sh: dict[str, float] = {}
    cash    = starting_cash
    txn_i   = 0
    port_vals: list[float] = []

    for dt, ds in zip(idx, dates_str):
        while txn_i < len(txns) and txns[txn_i]["date"] <= ds:
            t = txns[txn_i]
            open_sh[t["ticker"]] = open_sh.get(t["ticker"], 0.0) + (
                t["shares"] if t["type"] == "buy" else -t["shares"])
            cash += t["cash_delta"]
            txn_i += 1
        val = cash
        for tkr, sh in open_sh.items():
            if sh <= 0 or tkr not in hist: continue
            s    = hist[tkr]
            mask = s.index <= dt
            if mask.any():
                val += sh * float(s[mask].iloc[-1])
        port_vals.append(round(val, 2))

    # Benchmarks normalised to starting_cash
    spy_s    = float(hist["SPY"].iloc[0])
    spy_vals = [round(starting_cash * float(v) / spy_s, 2)
                for v in hist["SPY"].reindex(idx, method="ffill").values]
    qqq_vals: list[float] = []
    if "QQQ" in hist:
        qqq_r = hist["QQQ"].reindex(idx, method="ffill")
        qqq_s = float(qqq_r.iloc[0])
        qqq_vals = [round(starting_cash * float(v) / qqq_s, 2) for v in qqq_r.values]

    # Allocation (current market value per position)
    alloc: dict[str, float] = {}
    for tkr, lots in positions.items():
        sh = sum(l["shares"] for l in lots)
        if sh > 0 and tkr in hist:
            alloc[tkr] = round(sh * float(hist[tkr].iloc[-1]), 2)
    if float(p.get("cash", 0)) > 0:
        alloc["Gotovina"] = round(float(p["cash"]), 2)

    return {
        "dates":         dates_str,
        "portfolio":     port_vals,
        "spy":           spy_vals,
        "qqq":           qqq_vals,
        "starting_cash": starting_cash,
        "allocation":    alloc,
    }


@app.get("/api/sectors")
def get_sectors():
    """Sector ETF performance comparison."""
    if not _cache["sectors"]:
        _cache["sectors"] = _fetch_sectors()
    return {"sectors": _cache["sectors"], "updated_at": _cache.get("updated_at")}


@app.get("/api/sectors/{sector_name}/stocks")
def get_sector_stocks(sector_name: str):
    """Top stocks for a given sector with performance data."""
    if sector_name not in _sector_stocks_cache:
        _sector_stocks_cache[sector_name] = _fetch_sector_stocks(sector_name)
    return {"sector": sector_name, "stocks": _sector_stocks_cache[sector_name]}


# ─── Calendar helpers & fetch ─────────────────────────────────────────────────

def _safe_float_cal(v) -> float | None:
    try:
        return round(float(v), 2) if v is not None else None
    except Exception:
        return None


def _fmt_ts(d) -> str | None:
    if d is None:
        return None
    try:
        s = d.strftime("%Y-%m-%d")
    except Exception:
        s = str(d)
        if len(s) < 10:
            return None
        s = s[:10]
    # yfinance sometimes returns weekend dates due to timezone shifts — snap to nearest weekday
    try:
        dt = date.fromisoformat(s)
        wd = dt.weekday()  # 5=Sat, 6=Sun
        if wd == 5:        # Saturday → Friday
            dt -= timedelta(days=1)
        elif wd == 6:      # Sunday → Monday
            dt += timedelta(days=1)
        return dt.isoformat()
    except Exception:
        return s


def _fetch_calendar_bg():
    global _cal_fetching
    if _cal_fetching:
        return
    _cal_fetching = True
    print("[CALENDAR] Fetching earnings & dividends calendar…")
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        stock_lookup = {s["ticker"]: s for s in (_cache.get("stocks") or [])}

        def fetch_one(tkr):
            try:
                t    = yf.Ticker(tkr)
                cal  = t.calendar or {}
                fi   = t.fast_info
                mcap = (getattr(fi, "market_cap", None) or
                        stock_lookup.get(tkr, {}).get("market_cap", 0) or 0)
                return tkr, cal, _TICKER_NAMES.get(tkr, tkr), int(mcap)
            except Exception:
                return tkr, {}, _TICKER_NAMES.get(tkr, tkr), 0

        earnings_list: list[dict] = []
        divs_list:     list[dict] = []

        with ThreadPoolExecutor(max_workers=15) as ex:
            futures = {ex.submit(fetch_one, t): t for t in _CALENDAR_TICKERS}
            for f in as_completed(futures):
                tkr, cal, name, mcap = f.result()
                if not cal:
                    continue

                # Earnings
                dates = cal.get("Earnings Date") or []
                if isinstance(dates, (list, tuple)) and dates:
                    d0 = dates[0]
                    date_str = _fmt_ts(d0)
                    if date_str:
                        earnings_list.append({
                            "ticker":     tkr,
                            "name":       name,
                            "market_cap": mcap,
                            "date":       date_str,
                            "eps_est":    _safe_float_cal(cal.get("Earnings Average")),
                            "eps_low":    _safe_float_cal(cal.get("Earnings Low")),
                            "eps_high":   _safe_float_cal(cal.get("Earnings High")),
                            "rev_est":    _safe_float_cal(cal.get("Revenue Average")),
                        })

                # Ex-dividend
                ex_div = _fmt_ts(cal.get("Ex-Dividend Date"))
                if ex_div:
                    divs_list.append({
                        "ticker":     tkr,
                        "name":       name,
                        "market_cap": mcap,
                        "ex_date":    ex_div,
                        "pay_date":   _fmt_ts(cal.get("Dividend Date")),
                    })

        _cal_cache["earnings"]   = sorted(earnings_list, key=lambda x: x["date"])
        _cal_cache["dividends"]  = sorted(divs_list,     key=lambda x: x["ex_date"])
        _cal_cache["fetched_at"] = datetime.now().isoformat()
        print(f"[CALENDAR] Done: {len(earnings_list)} earnings, {len(divs_list)} dividends")
    except Exception as e:
        print(f"[CALENDAR] Error: {e}")
    finally:
        _cal_fetching = False


@app.get("/api/calendar")
async def get_calendar(background_tasks: BackgroundTasks, week_start: str | None = None):
    """Earnings, dividends and economic calendar for a given Mon–Sun week."""
    from datetime import date as dt_date
    today = dt_date.today()
    if week_start:
        try:
            ws = datetime.strptime(week_start, "%Y-%m-%d").date()
        except ValueError:
            ws = today - timedelta(days=today.weekday())
    else:
        ws = today - timedelta(days=today.weekday())

    we = ws + timedelta(days=6)

    # Trigger refresh if data is stale (>4 h) or missing
    stale = True
    if _cal_cache.get("fetched_at"):
        try:
            if (datetime.now() - datetime.fromisoformat(_cal_cache["fetched_at"])).total_seconds() < 14400:
                stale = False
        except Exception:
            pass

    if stale and not _cal_fetching:
        background_tasks.add_task(_fetch_calendar_bg)

    def in_week(ds: str) -> bool:
        try:
            d = datetime.strptime(ds, "%Y-%m-%d").date()
            return ws <= d <= we
        except Exception:
            return False

    earnings  = [e for e in (_cal_cache.get("earnings")  or []) if in_week(e["date"])]
    dividends = [d for d in (_cal_cache.get("dividends") or []) if in_week(d["ex_date"])]
    economic  = sorted(
        [e for e in _ECONOMIC_EVENTS if in_week(e["date"])],
        key=lambda x: (x["date"], x["time"]),
    )

    return {
        "week_start": str(ws),
        "week_end":   str(we),
        "earnings":   sorted(earnings,  key=lambda x: x["date"]),
        "dividends":  sorted(dividends, key=lambda x: x["ex_date"]),
        "economic":   economic,
        "loading":    _cal_fetching,
        "fetched_at": _cal_cache.get("fetched_at"),
    }


@app.post("/api/calendar/refresh")
async def refresh_calendar(background_tasks: BackgroundTasks):
    """Force re-fetch of earnings/dividends calendar data."""
    if _cal_fetching:
        raise HTTPException(409, "Fetch že teče")
    _cal_cache["fetched_at"] = None
    background_tasks.add_task(_fetch_calendar_bg)
    return {"status": "started", "tickers": len(_CALENDAR_TICKERS)}


@app.get("/api/scan/status")
def scan_status():
    return {
        "scanning":    _cache["scanning"],
        "updated_at":  _cache["updated_at"],
        "scan_date":   _cache["scan_date"],
        "stocks":      len(_cache["stocks"]),
        "error":       _cache["scan_error"],
        "scan_done":   _cache.get("scan_done", 0),
        "scan_total":  _cache.get("scan_total", 0),
    }


@app.get("/api/scan/schedule")
def get_schedule():
    """Return auto-scan schedule info."""
    return {
        "enabled":   _scheduler["enabled"],
        "time":      f"{SCAN_HOUR:02d}:{SCAN_MINUTE:02d}",
        "next_run":  _scheduler["next_run"],
        "last_auto": _scheduler["last_auto"],
    }


@app.post("/api/scan/schedule/toggle")
def toggle_schedule():
    """Enable or disable the daily auto-scan."""
    _scheduler["enabled"] = not _scheduler["enabled"]
    state = "enabled" if _scheduler["enabled"] else "disabled"
    print(f"[SCHEDULER] Auto-scan {state}")
    return {"enabled": _scheduler["enabled"], "message": f"Auto-scan {state}"}


@app.post("/api/scan")
def trigger_scan(
    background_tasks: BackgroundTasks,
    date: Optional[str] = None,
):
    """
    Start a background scan. Optional ?date=YYYY-MM-DD for historical mode.
    Returns immediately; poll /api/scan/status to track progress.
    """
    if _cache["scanning"]:
        return {"message": "Scan already running", "scanning": True}
    background_tasks.add_task(_run_scan, date)
    return {"message": "Scan started", "scan_date": date or "today"}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _safe(v, default=0.0):
    try:
        return float(v) if v is not None and not pd.isna(v) else default
    except Exception:
        return default


def _fmt_mcap(mcap):
    if not mcap or pd.isna(mcap):
        return "N/A"
    if mcap >= 1e12:
        return f"${mcap/1e12:.2f}T"
    if mcap >= 1e9:
        return f"${mcap/1e9:.2f}B"
    return f"${mcap/1e6:.2f}M"


def _slice_to_date(df, scan_date):
    """Slice a DataFrame/Series index to <= scan_date, handling timezone."""
    cutoff = pd.Timestamp(scan_date)
    if df.index.tz is not None:
        cutoff = cutoff.tz_localize(df.index.tz)
    return df[df.index <= cutoff]


def _rsi_series(prices: pd.Series, periods: int = 14) -> pd.Series:
    delta = prices.diff()
    gain  = delta.where(delta > 0, 0).rolling(periods).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(periods).mean()
    rs    = gain / loss
    return 100 - (100 / (1 + rs))


def _fetch_sectors(scan_date=None) -> dict:
    etfs = list(SECTOR_ETF_MAP.values())
    try:
        if scan_date:
            end_dt = (scan_date + timedelta(days=8)).strftime("%Y-%m-%d")
            raw = yf.download(etfs, start="2020-01-01", end=end_dt, interval="1wk", progress=False)
        else:
            raw = yf.download(etfs, period="13mo", interval="1wk", progress=False)
        data = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
        if scan_date:
            data = _slice_to_date(data, scan_date)
    except Exception as e:
        print(f"[WARN] Sector fetch failed: {e}")
        return {}

    leto   = scan_date.year if scan_date else datetime.now().year
    result = {}
    for sector, etf in SECTOR_ETF_MAP.items():
        try:
            p = data[etf].dropna()
            if len(p) < 10:
                continue
            ytd = p[p.index.year == leto]
            rsi_val = _rsi_series(p)
            result[sector] = {
                "etf":       etf,
                "cena":      round(float(p.iloc[-1]), 2),
                "donos_1m":  round(float((p.iloc[-1]/p.iloc[-5]-1)*100),  1) if len(p) >= 5  else 0.0,
                "donos_3m":  round(float((p.iloc[-1]/p.iloc[-14]-1)*100), 1) if len(p) >= 14 else 0.0,
                "donos_ytd": round(float((p.iloc[-1]/ytd.iloc[0]-1)*100), 1) if len(ytd) > 0 else 0.0,
                "donos_1y":  round(float((p.iloc[-1]/p.iloc[-53]-1)*100), 1) if len(p) >= 53 else 0.0,
                "rsi":       round(float(rsi_val.iloc[-1]) if not pd.isna(rsi_val.iloc[-1]) else 50.0, 1),
            }
        except Exception:
            continue
    return result


def _fetch_sector_stocks(sector: str) -> list[dict]:
    tickers = SECTOR_STOCKS.get(sector, [])
    if not tickers:
        return []
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Fetch price history and market caps in parallel
        raw  = yf.download(tickers, period="13mo", interval="1wk", progress=False)
        data = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
        if isinstance(data, pd.Series):
            data = data.to_frame(name=tickers[0])

        def get_mcap(tkr):
            try:
                fi = yf.Ticker(tkr).fast_info
                return tkr, int(getattr(fi, "market_cap", 0) or 0)
            except Exception:
                return tkr, 0

        mcap_map: dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=10) as ex:
            for tkr, mc in ex.map(lambda t: get_mcap(t), tickers):
                mcap_map[tkr] = mc

        leto = datetime.now().year
        result = []
        for tkr in tickers:
            try:
                p = data[tkr].dropna() if tkr in data.columns else pd.Series([], dtype=float)
                if len(p) < 5:
                    continue
                ytd = p[p.index.year == leto]
                result.append({
                    "ticker":     tkr,
                    "name":       _TICKER_NAMES.get(tkr, tkr),
                    "cena":       round(float(p.iloc[-1]), 2),
                    "market_cap": mcap_map.get(tkr, 0),
                    "donos_1m":   round(float((p.iloc[-1]/p.iloc[-5] -1)*100), 1) if len(p) >= 5  else 0.0,
                    "donos_3m":   round(float((p.iloc[-1]/p.iloc[-14]-1)*100), 1) if len(p) >= 14 else 0.0,
                    "donos_ytd":  round(float((p.iloc[-1]/ytd.iloc[0]-1)*100), 1) if len(ytd) > 0 else 0.0,
                    "donos_1y":   round(float((p.iloc[-1]/p.iloc[-53]-1)*100), 1) if len(p) >= 53 else 0.0,
                })
            except Exception:
                continue
        return sorted(result, key=lambda x: x["market_cap"], reverse=True)
    except Exception as e:
        print(f"[WARN] Sector stocks fetch failed for {sector}: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# CORE SCAN
# ═══════════════════════════════════════════════════════════════════════════════

def _run_scan(scan_date_str: str | None = None):
    _cache["scanning"]   = True
    _cache["scan_error"] = None

    scan_date = None
    if scan_date_str:
        try:
            scan_date = datetime.strptime(scan_date_str, "%Y-%m-%d").date()
        except ValueError:
            _cache["scanning"]   = False
            _cache["scan_error"] = f"Invalid date: {scan_date_str}. Use YYYY-MM-DD."
            return

    print(f"\n[SCAN] Starting {'historical ' + str(scan_date) if scan_date else 'live'} scan...")

    if not os.path.exists(CSV_FILE):
        _cache["scanning"]   = False
        _cache["scan_error"] = f"CSV not found: {CSV_FILE}"
        return

    tickers      = pd.read_csv(CSV_FILE)["Ticker"].dropna().astype(str).str.strip().tolist()
    leto         = scan_date.year if scan_date else datetime.now().year
    stocks       = []
    chart_data   = {}
    _cache["scan_total"] = len(tickers)
    _cache["scan_done"]  = 0

    for i, ticker in enumerate(tickers, 1):
        _cache["scan_done"] = i
        if i % 20 == 0:
            print(f"  [{i}/{len(tickers)}]")
        try:
            t    = yf.Ticker(ticker)
            info = t.info

            mcap = info.get("marketCap")
            if not mcap or pd.isna(mcap) or mcap < MIN_MARKET_CAP:
                continue

            rev_growth   = _safe(info.get("revenueGrowth"))
            gross_margin = _safe(info.get("grossMargins"))
            eps_growth   = _safe(info.get("earningsQuarterlyGrowth") or info.get("earningsGrowth"))
            peg          = _safe(info.get("pegRatio"))

            # skip weak revenue growth for live scans only
            if not scan_date and rev_growth < MIN_REV_GROWTH:
                continue

            # ── Price history ─────────────────────────────────────────────────
            dl_end = (scan_date + timedelta(days=8)).strftime("%Y-%m-%d") if scan_date else None
            data   = t.history(start="2010-01-01", end=dl_end, interval="1wk", actions=False)
            if data is None or data.empty or len(data) < 52:
                continue
            if scan_date:
                data = _slice_to_date(data, scan_date)
            if len(data) < 52:
                continue
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            close = data["Close"].dropna()
            if len(close) < 205:
                continue

            # ── Moving averages ───────────────────────────────────────────────
            is_mega        = mcap >= MEGA_CAP
            is_high_margin = (gross_margin * 100) >= 50.0 and not is_mega
            if is_mega:
                ma      = close.rolling(50).mean()
                ma200_  = close.rolling(200).mean()
                ma_lbl  = "50w+200w MA (Mega-Cap)"
            else:
                ma     = close.rolling(200).mean()
                ma_lbl = "200w MA (Moat)" if is_high_margin else "200w MA"

            dist_arr = ((close - ma) / ma * 100).values
            rsi_s    = _rsi_series(close)
            rsi_arr  = rsi_s.values

            # ── OGM scoring ───────────────────────────────────────────────────
            W_MA, W_RSI = 40.0, 15.0
            tocke_ma = np.zeros_like(dist_arr)
            pos, neg = dist_arr >= 0, dist_arr < 0

            if is_mega:
                W_half = W_MA / 2.0
                t50 = np.zeros_like(dist_arr)
                t50[pos] = np.interp(dist_arr[pos], [0,2,8,15],    [W_half*(32/35), W_half, W_half*(15/35), 0])
                t50[neg] = np.interp(dist_arr[neg], [-40,-15,-2,0], [W_half, W_half, W_half*(34/35), W_half*(32/35)])
                dist200_ = ((close - ma200_) / ma200_ * 100).fillna(0).values
                p2, n2 = dist200_ >= 0, dist200_ < 0
                t200 = np.zeros_like(dist200_)
                t200[p2] = np.interp(dist200_[p2], [0,5,20,40],   [W_half*(32/35), W_half, W_half*(15/35), 0])
                t200[n2] = np.interp(dist200_[n2], [-50,-20,-5,0], [W_half, W_half, W_half*(34/35), W_half*(32/35)])
                tocke_ma = t50 + t200
            elif is_high_margin:
                tocke_ma[pos] = np.interp(dist_arr[pos], [0,2,10,25,50],    [W_MA*(33/35), W_MA, W_MA*(22/35), W_MA*(8/35), 0])
                tocke_ma[neg] = np.interp(dist_arr[neg], [-35,-20,-15,-5,0], [0, 35, 40, 38, W_MA*(33/35)])
            else:
                tocke_ma[pos] = np.interp(dist_arr[pos], [0,2,10,25,50],  [W_MA*(33/35), W_MA, W_MA*(22/35), W_MA*(8/35), 0])
                tocke_ma[neg] = np.interp(dist_arr[neg], [-20,-10,-5,0],   [0, W_MA*(12/35), W_MA*(25/35), W_MA*(33/35)])

            tocke_rsi    = np.interp(rsi_arr, [30,45,60,70,80], [W_RSI, W_RSI*0.8, W_RSI*0.5, W_RSI*0.2, 0])

            eps_pct      = eps_growth * 100
            peg_val      = peg if peg > 0 else 2.0
            gm_pct       = gross_margin * 100
            tocke_eps    = float(np.interp(eps_pct,  [0.0, 8.0, 16.5, 22.0, 30.0], [0.0, 5.0, 14.0, 20.0, 20.0]))
            tocke_peg    = float(np.interp(peg_val,  [0.4, 0.8,  1.2,  1.6,  2.0], [15.0, 13.0, 10.0,  5.0,  0.0]))
            tocke_margin = float(np.interp(gm_pct,   [25,  35,   45,   55,   65],  [0.0,  2.0,   5.0,   8.0, 10.0]))
            base         = min(45.0, tocke_eps + tocke_peg + tocke_margin)

            ogm_arr = np.clip(tocke_ma + tocke_rsi + base, 0, 100)
            ogm_now = float(ogm_arr[-1])
            if ogm_now < 65.0:
                continue
            if not scan_date and rev_growth < MIN_REV_GROWTH:
                continue

            # ── Current metrics ───────────────────────────────────────────────
            price_now    = float(close.iloc[-1])
            dist_now     = float(dist_arr[-1])
            dist200_now  = float(dist200_[-1]) if is_mega else None
            price_1m     = float(close.iloc[-5]) if len(close) >= 5 else price_now
            donos_1m     = (price_now - price_1m) / price_1m * 100

            ytd_idx    = close.index[close.index.year == leto]
            ytd_start  = float(close.loc[ytd_idx[0]]) if len(ytd_idx) > 0 else float(close.iloc[-22])
            donos_ytd  = (price_now - ytd_start) / ytd_start * 100

            ma_short = close.rolling(4).mean()   # 4-week (~1 month), matches A18
            falling  = float(ma_short.iloc[-1]) < float(ma.iloc[-1])
            if ogm_now >= 80:                     status = "STRONG BUY"
            elif falling:                         status = "WARNING (FALLING PHASE)"
            elif dist_now < 0:                    status = "WARNING (POD MA)"
            elif rev_growth >= SUPER_GROWTH:      status = "SUPER-GROWTH TARGET"
            else:                                 status = "BUY"

            # ── Assemble output ───────────────────────────────────────────────
            summary = {
                "ticker":       ticker,
                "ime":          info.get("shortName") or ticker,
                "sektor":       info.get("sector", "N/A"),
                "ogm":          round(ogm_now, 1),
                "status":       status,
                "cena":         round(price_now, 2),
                "target_price": round(_safe(info.get("targetMeanPrice")), 2),
                "mcap":         _fmt_mcap(mcap),
                "rev_growth":   round(rev_growth * 100, 1),
                "dist_ma":      round(dist_now, 1),
                "dist_ma200":   round(dist200_now, 1) if dist200_now is not None else None,
                "ma_type":      ma_lbl,
                "donos_1m":     round(donos_1m, 2),
                "donos_ytd":    round(donos_ytd, 2),
            }
            stocks.append(summary)

            datumi = [d.strftime("%Y-%m-%d") for d in close.index]
            ma50_l = [0 if pd.isna(v) else round(float(v),2) for v in close.rolling(50).mean()]
            ma200_l= [0 if pd.isna(v) else round(float(v),2) for v in close.rolling(200).mean()]

            chart_data[ticker] = {
                **summary,
                "dates":       datumi,
                "prices":      [round(float(v), 2) if not np.isnan(v) else None for v in close.values],
                "ogm_history": [round(float(v), 1) if not np.isnan(v) else None for v in ogm_arr],
                "ma50":        ma50_l,
                "ma200":       ma200_l,
                "components": {
                    "eps_score":    round(tocke_eps, 1),
                    "peg_score":    round(tocke_peg, 1),
                    "margin_score": round(tocke_margin, 1),
                    "rsi_score":    round(float(tocke_rsi[-1]), 1),
                    "ma_score":     round(float(tocke_ma[-1]), 1),
                    "total":        round(ogm_now, 1),
                    "ma_type":      ma_lbl,
                },
            }

            time.sleep(0.04)

        except Exception:
            continue

    stocks.sort(key=lambda x: x["ogm"], reverse=True)
    sectors = _fetch_sectors(scan_date)

    _cache.update({
        "stocks":     stocks,
        "chart_data": chart_data,
        "sectors":    sectors,
        "updated_at": datetime.now().isoformat(),
        "scan_date":  str(scan_date) if scan_date else None,
        "scanning":   False,
    })

    # Persist to disk
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in _cache.items() if k not in ("scanning",)}, f)
        print(f"[SCAN] Done — {len(stocks)} stocks cached.")
    except Exception as e:
        print(f"[WARN] Cache save failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO  (/api/portfolio/*)
# ═══════════════════════════════════════════════════════════════════════════════

PORTFOLIO_FILE = "ogm_virtual_portfolio.json"


class BuyRequest(BaseModel):
    ticker: str
    amount: float
    date: Optional[str] = None   # YYYY-MM-DD, None = today


class SellRequest(BaseModel):
    ticker: str
    shares: Optional[float] = None   # None = sell all


@app.get("/api/portfolio")
def get_portfolio():
    """Live portfolio summary with P&L per position."""
    if not os.path.exists(PORTFOLIO_FILE):
        return {"cash": 50000.0, "positions": {}, "total_value": 50000.0, "total_pnl": 0.0}

    with open(PORTFOLIO_FILE, encoding="utf-8") as f:
        p = json.load(f)

    positions = {}
    total_invested = 0.0
    total_value    = float(p.get("cash", 0))

    for ticker, lots in p.get("positions", {}).items():
        try:
            price, _ = _live_price(ticker)
            if not price:
                continue
            shares    = sum(l["shares"]   for l in lots)
            cost      = sum(l["invested"] for l in lots)
            cur_val   = shares * price
            pnl       = cur_val - cost
            positions[ticker] = {
                "ticker":        ticker,
                "name":          lots[0].get("company", ticker),
                "sector":        lots[0].get("sector", "N/A"),
                "total_shares":  round(shares, 6),
                "avg_cost":      round(cost / shares, 4) if shares else 0,
                "current_price": round(price, 2),
                "total_invested":round(cost, 2),
                "current_value": round(cur_val, 2),
                "pnl":           round(pnl, 2),
                "pnl_pct":       round(pnl / cost * 100, 2) if cost else 0,
                "lots":          lots,
            }
            total_invested += cost
            total_value    += cur_val
        except Exception:
            continue

    starting = float(p.get("starting_cash", 50000))
    total_pnl = total_value - starting
    return {
        "cash":           round(p.get("cash", 0), 2),
        "starting_cash":  starting,
        "total_invested": round(total_invested, 2),
        "total_value":    round(total_value, 2),
        "total_pnl":      round(total_pnl, 2),
        "total_pnl_pct":  round(total_pnl / starting * 100, 2) if starting else 0,
        "positions":      positions,
        "closed_positions": p.get("closed_positions", []),
        "created":        p.get("created"),
    }


@app.post("/api/portfolio/buy")
def portfolio_buy(req: BuyRequest):
    """Add a buy position (today or historical date)."""
    if not os.path.exists(PORTFOLIO_FILE):
        p = {"cash": 50000.0, "starting_cash": 50000.0,
             "created": datetime.now().date().isoformat(),
             "positions": {}, "closed_positions": []}
    else:
        with open(PORTFOLIO_FILE, encoding="utf-8") as f:
            p = json.load(f)

    ticker   = req.ticker.upper()
    today    = datetime.now().date().isoformat()
    buy_date = req.date or today

    if req.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    if req.amount > p["cash"]:
        raise HTTPException(400, f"Insufficient cash — available ${p['cash']:,.2f}")

    if buy_date < today:
        price, actual = _hist_price(ticker, buy_date)
        buy_date = actual or buy_date
    else:
        price, _ = _live_price(ticker)

    if not price or price <= 0:
        raise HTTPException(404, f"Could not get price for {ticker}")

    try:
        info    = yf.Ticker(ticker).info
        company = info.get("shortName") or ticker
        sector  = info.get("sector", "N/A")
    except Exception:
        company, sector = ticker, "N/A"

    lot = {"shares": round(req.amount / price, 6), "cost_basis": round(price, 4),
           "invested": round(req.amount, 2), "open_date": buy_date,
           "company": company, "sector": sector}
    p["positions"].setdefault(ticker, []).append(lot)
    p["cash"] = round(p["cash"] - req.amount, 2)

    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2)

    return {"message": f"Bought {lot['shares']:.4f} shares of {ticker} @ ${price:.2f}",
            "lot": lot, "remaining_cash": p["cash"]}


@app.post("/api/portfolio/sell")
def portfolio_sell(req: SellRequest):
    """Sell shares from an open position."""
    if not os.path.exists(PORTFOLIO_FILE):
        raise HTTPException(404, "No portfolio found")
    with open(PORTFOLIO_FILE, encoding="utf-8") as f:
        p = json.load(f)

    ticker = req.ticker.upper()
    if ticker not in p.get("positions", {}):
        raise HTTPException(404, f"{ticker} not in portfolio")

    price, _ = _live_price(ticker)
    if not price:
        raise HTTPException(404, f"Could not get live price for {ticker}")

    lots            = p["positions"][ticker]
    total_shares    = sum(l["shares"] for l in lots)
    shares_to_sell  = req.shares if req.shares else total_shares
    if shares_to_sell > total_shares + 1e-8:
        raise HTTPException(400, f"Only {total_shares:.4f} shares available")

    today      = datetime.now().date().isoformat()
    remaining  = shares_to_sell
    new_lots   = []
    closed_log = []
    cost_sold  = 0.0

    for lot in lots:
        if remaining <= 0:
            new_lots.append(lot)
            continue
        if lot["shares"] <= remaining + 1e-8:
            cost_sold += lot["invested"]
            closed_log.append({"ticker": ticker, "buy_date": lot["open_date"],
                                "sell_date": today, "shares": round(lot["shares"], 6),
                                "buy_price": lot["cost_basis"], "sell_price": round(price, 4),
                                "invested": lot["invested"],
                                "proceeds": round(lot["shares"] * price, 2)})
            remaining -= lot["shares"]
        else:
            frac = remaining / lot["shares"]
            cost_sold += lot["invested"] * frac
            closed_log.append({"ticker": ticker, "buy_date": lot["open_date"],
                                "sell_date": today, "shares": round(remaining, 6),
                                "buy_price": lot["cost_basis"], "sell_price": round(price, 4),
                                "invested": round(lot["invested"] * frac, 2),
                                "proceeds": round(remaining * price, 2)})
            nl = dict(lot)
            nl["shares"]   = round(lot["shares"]   - remaining, 6)
            nl["invested"] = round(lot["invested"] * (1 - frac), 2)
            new_lots.append(nl)
            remaining = 0

    if new_lots:
        p["positions"][ticker] = new_lots
    else:
        del p["positions"][ticker]
    p["closed_positions"] = p.get("closed_positions", []) + closed_log
    proceeds  = round(shares_to_sell * price, 2)
    p["cash"] = round(p["cash"] + proceeds, 2)

    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2)

    pnl = round(proceeds - cost_sold, 2)
    return {"message": f"Sold {shares_to_sell:.4f} shares of {ticker} @ ${price:.2f}",
            "proceeds": proceeds, "pnl": pnl, "remaining_cash": p["cash"]}


def _live_price(ticker: str):
    try:
        info  = yf.Ticker(ticker).info
        price = (info.get("regularMarketPrice") or info.get("currentPrice")
                 or info.get("previousClose"))
        if not price:
            h = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
            price = float(h["Close"].iloc[-1]) if not h.empty else None
        return price, info
    except Exception:
        return None, {}


def _hist_price(ticker: str, date_str: str):
    try:
        end = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
        h   = yf.Ticker(ticker).history(start=date_str, end=end, auto_adjust=True)
        if not h.empty:
            return float(h["Close"].iloc[0]), h.index[0].strftime("%Y-%m-%d")
    except Exception:
        pass
    return None, None


# ═══════════════════════════════════════════════════════════════════════════════
# WATCHLIST  (/api/watchlist/*)
# ═══════════════════════════════════════════════════════════════════════════════

_wl_cache: dict = {"results": [], "updated_at": None, "scanning": False}


class WatchlistRequest(BaseModel):
    tickers: list[str]
    date: Optional[str] = None


@app.get("/api/watchlist/results")
def get_watchlist():
    return _wl_cache


@app.post("/api/watchlist/scan")
def scan_watchlist(req: WatchlistRequest, background_tasks: BackgroundTasks):
    """OGM analysis for a custom list of tickers."""
    if _wl_cache["scanning"]:
        return {"message": "Watchlist scan already running"}
    tickers = [t.strip().upper() for t in req.tickers if t.strip()]
    if not tickers:
        raise HTTPException(400, "No tickers provided")
    background_tasks.add_task(_run_watchlist, tickers, req.date)
    return {"message": f"Watchlist scan started for {len(tickers)} tickers", "tickers": tickers}


def _run_watchlist(tickers: list[str], scan_date_str: str | None = None):
    _wl_cache["scanning"] = True
    scan_date = None
    if scan_date_str:
        try:
            scan_date = datetime.strptime(scan_date_str, "%Y-%m-%d").date()
        except ValueError:
            _wl_cache["scanning"] = False
            return

    results = []
    for ticker in tickers:
        try:
            t    = yf.Ticker(ticker)
            info = t.info
            mcap         = info.get("marketCap")
            rev_growth   = _safe(info.get("revenueGrowth"))
            gross_margin = _safe(info.get("grossMargins"))
            eps_growth   = _safe(info.get("earningsQuarterlyGrowth") or info.get("earningsGrowth"))
            peg          = _safe(info.get("pegRatio"))

            dl_end = (scan_date + timedelta(days=8)).strftime("%Y-%m-%d") if scan_date else None
            data   = t.history(start="2014-01-01", end=dl_end, interval="1wk", actions=False)
            if data is None or data.empty or len(data) < 52:
                results.append({"ticker": ticker, "error": "Insufficient history"}); continue
            if scan_date:
                data = _slice_to_date(data, scan_date)
            if len(data) < 52:
                results.append({"ticker": ticker, "error": "Insufficient history for this date"}); continue
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            close = data["Close"].dropna()
            is_mega        = bool(mcap and mcap >= MEGA_CAP)
            is_high_margin = (gross_margin * 100) >= 50.0 and not is_mega
            if is_mega:
                ma     = close.rolling(50).mean()
                ma_lbl = "50w MA (Mega-Cap)"
            else:
                ma     = close.rolling(200).mean()
                ma_lbl = "200w MA (Moat)" if is_high_margin else "200w MA"

            dist_arr  = ((close - ma) / ma * 100).values
            rsi_arr   = _rsi_series(close).values
            W_MA, W_RSI = 40.0, 15.0
            tocke_ma  = np.zeros_like(dist_arr)
            pos, neg  = dist_arr >= 0, dist_arr < 0

            if is_mega:
                tocke_ma[pos] = np.interp(dist_arr[pos], [0,2,8,15],     [W_MA*(32/35),W_MA,W_MA*(15/35),0])
                tocke_ma[neg] = np.interp(dist_arr[neg], [-40,-15,-2,0],  [W_MA,W_MA,W_MA*(34/35),W_MA*(32/35)])
            elif is_high_margin:
                tocke_ma[pos] = np.interp(dist_arr[pos], [0,2,10,25,50],    [W_MA*(33/35),W_MA,W_MA*(22/35),W_MA*(8/35),0])
                tocke_ma[neg] = np.interp(dist_arr[neg], [-35,-20,-15,-5,0], [0,35,40,38,W_MA*(33/35)])
            else:
                tocke_ma[pos] = np.interp(dist_arr[pos], [0,2,10,25,50],  [W_MA*(33/35),W_MA,W_MA*(22/35),W_MA*(8/35),0])
                tocke_ma[neg] = np.interp(dist_arr[neg], [-20,-10,-5,0],   [0,W_MA*(12/35),W_MA*(25/35),W_MA*(33/35)])

            tocke_rsi    = np.interp(rsi_arr, [30,45,60,70,80], [W_RSI,W_RSI*.8,W_RSI*.5,W_RSI*.2,0])

            eps_pct      = eps_growth * 100
            peg_val      = peg if peg > 0 else 2.0
            gm_pct       = gross_margin * 100
            tocke_eps    = float(np.interp(eps_pct,  [0.0, 8.0, 16.5, 22.0, 30.0], [0.0, 5.0, 14.0, 20.0, 20.0]))
            tocke_peg    = float(np.interp(peg_val,  [0.4, 0.8,  1.2,  1.6,  2.0], [15.0, 13.0, 10.0, 5.0, 0.0]))
            tocke_margin = float(np.interp(gm_pct,   [25,  35,   45,   55,   65],  [0.0,  2.0,  5.0,  8.0, 10.0]))
            base         = min(45.0, tocke_eps + tocke_peg + tocke_margin)
            ogm_arr      = np.clip(tocke_ma + tocke_rsi + base, 0, 100)
            ogm_now      = float(ogm_arr[-1])
            dist_now     = float(dist_arr[-1])
            price_now    = float(close.iloc[-1])

            falling = float(close.rolling(4).mean().iloc[-1]) < float(ma.iloc[-1])
            if ogm_now >= 80:                 status = "STRONG BUY"
            elif falling:                     status = "WARNING (FALLING PHASE)"
            elif dist_now < 0:                status = "WARNING (POD MA)"
            elif rev_growth >= SUPER_GROWTH:  status = "SUPER-GROWTH TARGET"
            else:                             status = "BUY"

            results.append({
                "ticker":        ticker,
                "ime":           info.get("shortName") or ticker,
                "sektor":        info.get("sector", "N/A"),
                "ogm":           round(ogm_now, 1),
                "status":        status,
                "cena":          round(price_now, 2),
                "target_price":  round(_safe(info.get("targetMeanPrice")), 2),
                "mcap":          _fmt_mcap(mcap),
                "rev_growth":    round(rev_growth * 100, 1),
                "dist_ma":       round(dist_now, 1),
                "ma_type":       ma_lbl,
                "passes_filter": bool(mcap and mcap >= MIN_MARKET_CAP),
                "components": {
                    "eps_score":    round(tocke_eps, 1),
                    "peg_score":    round(tocke_peg, 1),
                    "margin_score": round(tocke_margin, 1),
                    "rsi_score":    round(float(tocke_rsi[-1]), 1),
                    "ma_score":     round(float(tocke_ma[-1]), 1),
                    "total":        round(ogm_now, 1),
                },
            })
        except Exception as e:
            results.append({"ticker": ticker, "error": str(e)})

    results.sort(key=lambda x: x.get("ogm", 0), reverse=True)
    _wl_cache.update({"results": results, "updated_at": datetime.now().isoformat(), "scanning": False})


# ═══════════════════════════════════════════════════════════════════════════════
# SELL RADAR  (/api/sell/*)
# ═══════════════════════════════════════════════════════════════════════════════

# Risk weights — 5 factors sum to exactly 100; eps_ma is a separate reduction (up to -35)
# Proportions kept from A2 genetic algorithm, scaled: 15.7+29.8+23.3+20.1+22.4=111.3 → ÷1.113
_SELL_W = {"rsi": 14.1, "d10": 26.8, "d50": 20.9, "strmina": 18.1, "pe": 20.1, "eps_ma": 35.0}
_SELL_T = {"armed": 84.6, "parabola": 30.4}
# EPS/MA50 ratio breakpoints:
#   ratio = MA50_growth_% / EPS_growth_%  (same units — both % change over 1 year)
#   ratio ≤ 1 → price growth ≤ earnings growth → fully justified → max reduction
#   ratio ≥ 6 → price grew 6× faster than earnings → no reduction
_EPS_MA_BREAKS = [1,    2,    4,    6   ]
_EPS_MA_REDS   = [35.0, 25.0, 10.0,  0.0]


def _eps_ma_reduction(ma50_growth_pct: float, eps_growth_raw: float) -> tuple[float, float]:
    """Return (ratio, risk_reduction_pts). Reduction is subtracted from sell score.
    ma50_growth_pct: % change of MA50 over past 52 weeks (weekly bars).
    eps_growth_raw:  YoY EPS growth as decimal fraction (e.g. 0.33 for 33%)."""
    if eps_growth_raw <= 0 or ma50_growth_pct <= 0:
        return (None, 0.0)
    eps_pct = eps_growth_raw * 100          # decimal → %
    ratio   = ma50_growth_pct / eps_pct     # both % → dimensionless
    red     = float(np.interp(ratio, _EPS_MA_BREAKS, _EPS_MA_REDS))
    return (round(ratio, 2), round(max(0.0, red), 1))
_sell_cache: dict = {"results": [], "updated_at": None, "scanning": False}


class SellScanRequest(BaseModel):
    tickers: Optional[list[str]] = None  # None → use portfolio open positions


@app.get("/api/sell/results")
def get_sell_results():
    return _sell_cache


@app.post("/api/sell/scan")
def scan_sell(req: SellScanRequest, background_tasks: BackgroundTasks):
    """Sell-risk analysis for custom tickers or portfolio positions."""
    if _sell_cache["scanning"]:
        return {"message": "Sell scan already running"}

    tickers = req.tickers
    if not tickers:
        if os.path.exists(PORTFOLIO_FILE):
            with open(PORTFOLIO_FILE, encoding="utf-8") as f:
                tickers = list(json.load(f).get("positions", {}).keys())
    if not tickers:
        raise HTTPException(400, "No tickers — provide a list or add positions to portfolio first")

    _sell_cache["scan_mode"] = "custom"
    background_tasks.add_task(_run_sell, [t.upper() for t in tickers], min_score=0)
    return {"message": f"Sell scan started for {len(tickers)} tickers"}


@app.post("/api/sell/scan/market")
def scan_sell_market(background_tasks: BackgroundTasks):
    """Scan all CSV tickers for sell risk — returns those with score >= 70."""
    if _sell_cache["scanning"]:
        return {"message": "Sell scan already running"}
    if not os.path.exists(CSV_FILE):
        raise HTTPException(404, f"CSV not found: {CSV_FILE}")
    tickers = pd.read_csv(CSV_FILE)["Ticker"].dropna().astype(str).str.strip().tolist()
    _sell_cache["scan_mode"] = "market"
    background_tasks.add_task(_run_sell, tickers, min_score=70)
    return {"message": f"Market sell scan started for {len(tickers)} tickers"}


@app.get("/api/sell/analyze/{ticker}")
def analyze_sell_stock(ticker: str):
    """Single-stock sell-risk deep dive: score breakdown + chart data."""
    ticker = ticker.upper()
    try:
        t    = yf.Ticker(ticker)
        info = t.info
        data = t.history(start="2019-01-01", interval="1wk", actions=False)
        if data is None or data.empty or len(data) < 52:
            raise HTTPException(404, f"Not enough price history for {ticker}")
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        close = pd.to_numeric(data["Close"].squeeze(), errors="coerce").dropna()
        ma10  = close.rolling(10).mean()
        ma50  = close.rolling(50).mean()
        ma200 = close.rolling(200).mean()
        ma100 = close.rolling(100).mean()
        rsi_s = _rsi_series(close)

        p0, p1, p2 = float(close.iloc[-1]), float(close.iloc[-2]), float(close.iloc[-3])
        rsi_now    = float(rsi_s.iloc[-1])
        d10_200    = (float(ma10.iloc[-1])  - float(ma200.iloc[-1])) / float(ma200.iloc[-1]) * 100
        d50_200    = (float(ma50.iloc[-1])  - float(ma200.iloc[-1])) / float(ma200.iloc[-1]) * 100
        strmina    = (float(ma10.iloc[-1])  - float(ma10.iloc[-11])) / float(ma10.iloc[-11]) * 100
        pe_stretch = (p0 - float(ma100.iloc[-1])) / float(ma100.iloc[-1]) * 100
        rast_3m    = (p0 - float(close.iloc[-13])) / float(close.iloc[-13]) * 100

        W = _SELL_W
        c_rsi  = float(np.interp(rsi_now,    [65,75,85],  [0, W["rsi"]/2,     W["rsi"]]))
        c_d10  = float(np.interp(d10_200,    [50,70,100], [0, W["d10"]/2,     W["d10"]]))
        c_d50  = float(np.interp(d50_200,    [30,40,60],  [0, W["d50"]/2,     W["d50"]]))
        c_str  = float(np.interp(strmina,    [10,12,20],  [0, W["strmina"]/2, W["strmina"]]))
        c_pe   = float(np.interp(pe_stretch, [30,40,60],  [0, W["pe"]/2,      W["pe"]]))
        raw_score = float(min(c_rsi + c_d10 + c_d50 + c_str + c_pe, 100.0))

        eps_growth_raw = _safe(info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth"))
        ma50_now   = float(ma50.iloc[-1])
        ma50_52w   = float(ma50.dropna().iloc[-53]) if len(ma50.dropna()) >= 53 else float(ma50.dropna().iloc[0])
        ma50_growth = (ma50_now - ma50_52w) / ma50_52w * 100 if ma50_52w > 0 else 0.0
        eps_ma_ratio, eps_ma_red = _eps_ma_reduction(ma50_growth, eps_growth_raw)
        score = max(0.0, raw_score - eps_ma_red)

        armed      = score >= _SELL_T["armed"]
        parabola   = rast_3m >= _SELL_T["parabola"]
        two_down   = p0 < p1 < p2
        ma10_break = p0 < float(ma10.iloc[-1]) and p1 >= float(ma10.iloc[-2])

        if score >= 99.0 and parabola:
            status, action = "BLOW-OFF TOP",         "TAKOJ PRODAJ"
        elif armed and parabola and two_down:
            status, action = "SELL — KLIMAKS PADEC", "PRODAJ 50%+"
        elif armed and parabola and ma10_break:
            status, action = "SELL — ZLOM 10w MA",   "PRODAJ VSE"
        elif armed and parabola:
            status, action = "PREGRETO",              "Stop-loss tik pod ceno"
        elif armed:
            status, action = "NATEGNJENO",            "Drži, trend stabilen"
        else:
            status, action = "VARNO",                 "Sedi na rokah"

        def _safe_list(s):
            return [round(float(v), 2) if not np.isnan(v) else None for v in s.values]

        dates = [d.strftime("%Y-%m-%d") for d in close.index]
        return {
            "ticker":      ticker,
            "ime":         info.get("shortName") or ticker,
            "sektor":      info.get("sector", "N/A"),
            "mcap":        _fmt_mcap(info.get("marketCap")),
            "cena":        round(p0, 2),
            "score":       round(score, 1),
            "raw_score":   round(raw_score, 1),
            "status":      status,
            "action":      action,
            "components": {
                "rsi":        {"val": round(rsi_now,    1), "score": round(c_rsi, 1), "max": W["rsi"],      "label": "RSI (14w)",           "reduce": False},
                "d10_200":    {"val": round(d10_200,    1), "score": round(c_d10, 1), "max": W["d10"],      "label": "MA10 vs MA200 (%)",   "reduce": False},
                "d50_200":    {"val": round(d50_200,    1), "score": round(c_d50, 1), "max": W["d50"],      "label": "MA50 vs MA200 (%)",   "reduce": False},
                "strmina":    {"val": round(strmina,    1), "score": round(c_str, 1), "max": W["strmina"],  "label": "MA10 Trend 10w (%)",  "reduce": False},
                "pe_stretch": {"val": round(pe_stretch, 1), "score": round(c_pe,  1), "max": W["pe"],       "label": "Price vs MA100 (%)",  "reduce": False},
                "eps_ma":     {
                    "val":          eps_ma_ratio,
                    "score":        round(eps_ma_red, 1),
                    "max":          W["eps_ma"],
                    "label":        "MA50 rast / EPS rast YoY (razmerje)",
                    "reduce":       True,
                    "ma50_growth":  round(ma50_growth, 1),
                    "eps_growth_pct": round(eps_growth_raw * 100, 1) if eps_growth_raw > 0 else None,
                },
            },
            "metrics": {
                "rsi":              round(rsi_now,    1),
                "rast_3m":          round(rast_3m,    1),
                "dist_10_200":      round(d10_200,    1),
                "dist_50_200":      round(d50_200,    1),
                "pe_stretch":       round(pe_stretch, 1),
                "strmina":          round(strmina,    1),
                "eps_ma_ratio":     eps_ma_ratio,
                "eps_ma_red":       round(eps_ma_red, 1),
                "ma50_growth":      round(ma50_growth, 1),
                "eps_growth_pct":   round(eps_growth_raw * 100, 1) if eps_growth_raw > 0 else None,
            },
            "chart": {
                "dates":  dates,
                "prices": _safe_list(close),
                "ma10":   _safe_list(ma10),
                "ma50":   _safe_list(ma50),
                "ma200":  _safe_list(ma200),
                "rsi":    [round(float(v), 1) if not np.isnan(v) else None for v in rsi_s.values],
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


def _run_sell(tickers: list[str], min_score: float = 0):
    _sell_cache["scanning"] = True
    _sell_cache["total"]    = len(tickers)
    _sell_cache["done"]     = 0
    results = []

    for ticker in tickers:
        try:
            t     = yf.Ticker(ticker)
            info  = t.info
            data  = t.history(period="5y", interval="1wk", actions=False)
            if len(data) < 52:
                continue
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            close = pd.to_numeric(data["Close"].squeeze(), errors="coerce").dropna()
            ma10  = close.rolling(10).mean()
            ma50  = close.rolling(50).mean()
            ma200 = close.rolling(200).mean()
            ma100 = close.rolling(100).mean()
            rsi   = _rsi_series(close)

            p0, p1, p2  = float(close.iloc[-1]), float(close.iloc[-2]), float(close.iloc[-3])
            rsi_now     = float(rsi.iloc[-1])
            d10_200     = (float(ma10.iloc[-1])  - float(ma200.iloc[-1])) / float(ma200.iloc[-1]) * 100
            d50_200     = (float(ma50.iloc[-1])  - float(ma200.iloc[-1])) / float(ma200.iloc[-1]) * 100
            strmina     = (float(ma10.iloc[-1])  - float(ma10.iloc[-11])) / float(ma10.iloc[-11]) * 100
            pe_stretch  = (p0 - float(ma100.iloc[-1])) / float(ma100.iloc[-1]) * 100
            rast_3m     = (p0 - float(close.iloc[-13])) / float(close.iloc[-13]) * 100

            W = _SELL_W
            raw_score = float(min(
                np.interp(rsi_now,    [65,75,85],  [0, W["rsi"]/2,     W["rsi"]]) +
                np.interp(d10_200,    [50,70,100], [0, W["d10"]/2,     W["d10"]]) +
                np.interp(d50_200,    [30,40,60],  [0, W["d50"]/2,     W["d50"]]) +
                np.interp(strmina,    [10,12,20],  [0, W["strmina"]/2, W["strmina"]]) +
                np.interp(pe_stretch, [30,40,60],  [0, W["pe"]/2,      W["pe"]]),
                100.0))

            eps_growth_raw = _safe(info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth"))
            ma50_now   = float(ma50.iloc[-1])
            ma50_52w   = float(ma50.dropna().iloc[-53]) if len(ma50.dropna()) >= 53 else float(ma50.dropna().iloc[0])
            ma50_growth = (ma50_now - ma50_52w) / ma50_52w * 100 if ma50_52w > 0 else 0.0
            eps_ma_ratio, eps_ma_red = _eps_ma_reduction(ma50_growth, eps_growth_raw)
            score = max(0.0, raw_score - eps_ma_red)

            armed     = score >= _SELL_T["armed"]
            parabola  = rast_3m >= _SELL_T["parabola"]
            two_down  = p0 < p1 < p2
            ma10_break= p0 < float(ma10.iloc[-1]) and p1 >= float(ma10.iloc[-2])

            if score >= 99.0 and parabola:
                status, action = "BLOW-OFF TOP",         "TAKOJ PRODAJ"
            elif armed and parabola and two_down:
                status, action = "SELL — KLIMAKS PADEC", "PRODAJ 50%+"
            elif armed and parabola and ma10_break:
                status, action = "SELL — ZLOM 10w MA",   "PRODAJ VSE"
            elif armed and parabola:
                status, action = "PREGRETO",              "Stop-loss tik pod ceno"
            elif armed:
                status, action = "NATEGNJENO",            "Drži, trend stabilen"
            else:
                status, action = "VARNO",                 "Vzdržuj pozicijo"

            if score >= min_score:
                results.append({
                    "ticker":        ticker,
                    "ime":           info.get("shortName") or ticker,
                    "cena":          round(p0, 2),
                    "score":         round(score, 1),
                    "raw_score":     round(raw_score, 1),
                    "eps_ma_ratio":  eps_ma_ratio,
                    "eps_ma_red":    round(eps_ma_red, 1),
                    "status":        status,
                    "action":        action,
                    "rsi":           round(rsi_now, 1),
                    "rast_3m":       round(rast_3m, 1),
                    "dist_10_200":   round(d10_200, 1),
                    "dist_50_200":   round(d50_200, 1),
                    "pe_stretch":    round(pe_stretch, 1),
                })
        except Exception:
            pass
        finally:
            _sell_cache["done"] = _sell_cache.get("done", 0) + 1

    results.sort(key=lambda x: x["score"], reverse=True)
    _sell_cache.update({"results": results, "updated_at": datetime.now().isoformat(), "scanning": False, "done": len(tickers), "total": len(tickers)})


# ═══════════════════════════════════════════════════════════════════════════════
# BOTTOM FINDER  (/api/bottom/*)
# Detects confirmed historical price bottoms and scores current conditions
# against those historical buy-point fingerprints.
# ═══════════════════════════════════════════════════════════════════════════════

NASDAQ100: list[str] = list(dict.fromkeys([
    # Big Tech
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA",
    # Semiconductors
    "AVGO","AMD","QCOM","TXN","INTC","MU","AMAT","LRCX","KLAC",
    "ADI","MCHP","ON","NXPI","MRVL","MPWR",
    # Software & Cloud
    "INTU","ADSK","SNPS","CDNS","ANSS","WDAY","TEAM","MDB","SNOW",
    # Cybersecurity
    "PANW","CRWD","FTNT","ZS","OKTA","DDOG","NET",
    # E-commerce & Internet
    "COST","BKNG","MELI","ABNB","PDD","JD","BIDU","NTES","TCOM",
    # Streaming & Media
    "NFLX","EA","TTWO","RBLX","TTD",
    # Biotech & Healthcare
    "AMGN","GILD","REGN","VRTX","BIIB","MRNA","IDXX","DXCM","ISRG","ILMN","ALGN",
    # Fintech
    "PYPL","COIN",
    # Industrial & Services
    "ADP","PAYX","CTAS","FAST","ODFL","CPRT","ORLY","PCAR","CSX","VRSK",
    # Consumer
    "ROST","DLTR","SBUX","KDP","MNST","PEP","MDLZ","LULU",
    # Growth / Other
    "PLTR","APP","SHOP","TMUS","ARM","ASML","AZN","CTSH","GEHC",
]))


def _detect_bottoms(
    close: pd.Series,
    rsi_s: pd.Series,
    ma50:  pd.Series,
    ma200: pd.Series,
    vol:   pd.Series,
) -> list[dict]:
    """
    Detects major market bottoms — 2-4× per decade for quality growth stocks.

    Primary signal: price at or below the 200-week SMA (the defining feature
    of real bottoms like MSFT/META/AMZN in 2022, 2020 COVID, 2018 Q4).

    Requirements (ALL must be met):
      1. Price is within 10% of MA200 from below  (dist_200 <= +10%)
      2. Price dropped >= 20% from the 2-year high (real correction, not noise)
      3. RSI < 45 (stock is oversold)
      4. Local minimum within ±8 week window
      5. Price recovers >= 20% within 52 weeks (confirmed — not just a dead-cat)
    """
    prices = close.values
    rsi_v  = rsi_s.values
    ma200v = ma200.values
    n      = len(prices)
    found  = []

    for i in range(104, n - 52):
        p     = float(prices[i])
        r     = float(rsi_v[i])
        m200  = float(ma200v[i]) if not np.isnan(ma200v[i]) else p

        # 1. PRIMARY SIGNAL: price at or near/below MA200 (within +10% from below)
        dist_200 = (p - m200) / m200 * 100
        if dist_200 > 10.0:        # more than 10% above MA200 = not a bottom zone
            continue

        # 2. RSI must be oversold
        if np.isnan(r) or r > 45:
            continue

        # 3. Local minimum: no bar within ±8 weeks is lower
        lo, hi = max(0, i - 8), min(n, i + 9)
        if float(prices[lo:hi].min()) < p:
            continue

        # 4. Significant correction from 2-year peak (filters out sideways noise)
        peak     = float(prices[max(0, i - 104):i].max())
        drop_pct = (p - peak) / peak * 100
        if drop_pct > -20.0:
            continue

        # 5. Confirmed: price recovers >= 20% within next 52 weeks
        future_hi = float(prices[i:min(n, i + 52)].max())
        recovery  = (future_hi - p) / p * 100
        if recovery < 20.0:
            continue

        m50_v = float(ma50.values[i]) if not np.isnan(ma50.values[i]) else p

        avg_vol = float(vol.iloc[max(0, i - 20):i].mean())
        vol_r   = round(float(vol.values[i]) / avg_vol, 2) if avg_vol > 0 else 1.0

        found.append({
            "idx":          i,
            "date":         close.index[i].strftime("%Y-%m-%d"),
            "price":        round(p, 2),
            "rsi":          round(r, 1),
            "drop_pct":     round(drop_pct, 1),
            "recovery_pct": round(recovery, 1),
            "dist_50":      round((p - m50_v) / m50_v  * 100, 1),
            "dist_200":     round(dist_200, 1),
            "vol_ratio":    vol_r,
        })

    # Deduplicate: bottoms within 26 weeks = same bear market, keep the lowest
    deduped: list[dict] = []
    for b in found:
        if deduped and b["idx"] - deduped[-1]["idx"] < 26:
            if b["price"] < deduped[-1]["price"]:
                deduped[-1] = b
        else:
            deduped.append(b)

    return deduped


def _bottom_score(current: dict, hist: list[dict]) -> dict:
    """
    Score current conditions against historical bottom fingerprint.
    If a trained ML model exists: use global mus/weights/scales.
    Otherwise: use per-stock averages + fixed weights (fallback).
    """
    if not hist and _BOTTOM_MODEL is None:
        return {"score": 0.0, "n_bottoms": 0, "hist_avg": None, "components": {}, "model_used": False}

    if _BOTTOM_MODEL is not None:
        ha = _BOTTOM_MODEL["mus"]
        ws = _BOTTOM_MODEL["weights"]
        sc = _BOTTOM_MODEL["scales"]
        n_ref = _BOTTOM_MODEL.get("n_pos", len(hist))
        model_used = True
    else:
        def _avg(key: str) -> float:
            return float(np.mean([b[key] for b in hist]))
        def _std(key: str) -> float:
            return max(float(np.std([b[key] for b in hist])), 3.0)
        ha = {k: round(_avg(k), 1) for k in _BOTTOM_KEYS}
        ws = {"rsi": 20.0, "drop_pct": 25.0, "dist_50": 25.0, "dist_200": 25.0, "vol_ratio": 5.0}
        sc = {"rsi": 10.0, "drop_pct": 8.0,  "dist_50": 8.0,  "dist_200": 8.0,  "vol_ratio": 1.5}
        n_ref = len(hist)
        model_used = False

    def sim(key: str) -> float:
        diff = abs(float(current.get(key) or 0) - float(ha[key]))
        return float(np.exp(-0.5 * (diff / max(float(sc[key]), 0.5)) ** 2) * float(ws[key]))

    c_rsi  = sim("rsi")
    c_drop = sim("drop_pct")
    c_d50  = sim("dist_50")
    c_d200 = sim("dist_200")
    c_vol  = sim("vol_ratio")
    score  = round(min(100.0, c_rsi + c_drop + c_d50 + c_d200 + c_vol), 1)

    return {
        "score":      score,
        "n_bottoms":  n_ref,
        "hist_avg":   ha,
        "model_used": model_used,
        "components": {
            "rsi":     {"current": current.get("rsi"),      "hist": ha["rsi"],      "score": round(c_rsi,1),  "max": round(ws["rsi"],1),      "label": "RSI (14w)"},
            "drop":    {"current": current.get("drop_pct"), "hist": ha["drop_pct"], "score": round(c_drop,1), "max": round(ws["drop_pct"],1),  "label": "Padec od 52w High (%)"},
            "dist_50": {"current": current.get("dist_50"),  "hist": ha["dist_50"],  "score": round(c_d50,1),  "max": round(ws["dist_50"],1),   "label": "Dist. od MA50 (%)"},
            "dist_200":{"current": current.get("dist_200"), "hist": ha["dist_200"], "score": round(c_d200,1), "max": round(ws["dist_200"],1),  "label": "Dist. od MA200 (%)"},
            "vol":     {"current": current.get("vol_ratio"),"hist": ha["vol_ratio"],"score": round(c_vol,1),  "max": round(ws["vol_ratio"],1), "label": "Volume spike (ratio)"},
        },
    }


def _bottom_analyze_ticker(ticker: str) -> dict:
    t    = yf.Ticker(ticker)
    info = t.info
    data = t.history(period="10y", interval="1wk", actions=False)
    if len(data) < 156:
        raise ValueError("Premalo podatkov (< 3 leta tedenskih podatkov)")

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    close = pd.to_numeric(data["Close"].squeeze(),  errors="coerce").dropna()
    vol   = pd.to_numeric(data["Volume"].squeeze(), errors="coerce").fillna(0)
    vol   = vol.reindex(close.index).fillna(0)

    ma50  = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    rsi_s = _rsi_series(close)

    bottoms = _detect_bottoms(close, rsi_s, ma50, ma200, vol)

    # Retroactive OGM Bottom score for each historical bottom:
    # score each bottom against all OTHER bottoms as reference
    for j, b in enumerate(bottoms):
        others = [x for k, x in enumerate(bottoms) if k != j]
        if others:
            b_metrics = {"rsi": b["rsi"], "drop_pct": b["drop_pct"],
                         "dist_50": b["dist_50"], "dist_200": b["dist_200"],
                         "vol_ratio": b["vol_ratio"]}
            b["ogm_bottom"] = _bottom_score(b_metrics, others)["score"]
        else:
            b["ogm_bottom"] = None

    p0        = float(close.iloc[-1])
    high_52w  = float(close.iloc[-52:].max()) if len(close) >= 52 else float(close.max())
    m50_now   = float(ma50.iloc[-1])  if not pd.isna(ma50.iloc[-1])  else p0
    m200_now  = float(ma200.iloc[-1]) if not pd.isna(ma200.iloc[-1]) else p0
    avg_vol_n = float(vol.iloc[-20:].mean()) or 1.0

    current = {
        "rsi":       round(float(rsi_s.iloc[-1]), 1),
        "drop_pct":  round((p0 - high_52w) / high_52w * 100, 1),
        "dist_50":   round((p0 - m50_now)  / m50_now  * 100, 1),
        "dist_200":  round((p0 - m200_now) / m200_now * 100, 1),
        "vol_ratio": round(float(vol.iloc[-1]) / avg_vol_n, 2),
    }

    analysis = _bottom_score(current, bottoms)

    def _sl(s: pd.Series) -> list:
        return [round(float(v), 2) if not np.isnan(v) else None for v in s.values]

    rev_growth = _safe(info.get("revenueGrowth") or 0)
    eps_growth = _safe(info.get("earningsGrowth") or 0)

    return {
        "ticker":      ticker,
        "ime":         info.get("shortName") or ticker,
        "sektor":      info.get("sector", "N/A"),
        "mcap":        _fmt_mcap(info.get("marketCap")),
        "cena":        round(p0, 2),
        "high_52w":    round(high_52w, 2),
        "rev_growth":  round(rev_growth * 100, 1),
        "eps_growth":  round(eps_growth * 100, 1),
        "gross_margin":round(_safe(info.get("grossMargins") or 0) * 100, 1),
        "score":       analysis["score"],
        "n_bottoms":   analysis["n_bottoms"],
        "hist_avg":    analysis["hist_avg"],
        "model_used":  analysis.get("model_used", False),
        "current":     current,
        "components":  analysis["components"],
        "bottoms":     [{"date":b["date"],"price":b["price"],"rsi":b["rsi"],
                         "drop_pct":b["drop_pct"],"recovery_pct":b["recovery_pct"],
                         "dist_50":b["dist_50"],"dist_200":b["dist_200"],
                         "vol_ratio":b["vol_ratio"],
                         "ogm_bottom":b.get("ogm_bottom")} for b in bottoms],
        "chart": {
            "dates":         [d.strftime("%Y-%m-%d") for d in close.index],
            "prices":        _sl(close),
            "ma50":          _sl(ma50),
            "ma200":         _sl(ma200),
            "rsi":           [round(float(v),1) if not np.isnan(v) else None for v in rsi_s.values],
            "bottom_dates":  [b["date"]  for b in bottoms],
            "bottom_prices": [b["price"] for b in bottoms],
        },
    }


# ─── OGM Bottom ML model ──────────────────────────────────────────────────────
_BOTTOM_MODEL_FILE = Path(__file__).parent / "ogm_bottom_model.json"
_BOTTOM_MODEL: dict | None = None

def _load_bottom_model():
    global _BOTTOM_MODEL
    if _BOTTOM_MODEL_FILE.exists():
        try:
            with open(_BOTTOM_MODEL_FILE) as f:
                _BOTTOM_MODEL = json.load(f)
        except Exception:
            _BOTTOM_MODEL = None

_load_bottom_model()

# Stocks used as training corpus — quality growth names with clear historical cycles
_TRAIN_TICKERS = [
    "MSFT","AAPL","META","AMZN","NVDA","GOOGL","TSLA",
    "MELI","COST","NFLX","PANW","CRWD","ADBE","CRM","INTU",
    "V","MA","SHOP","DDOG","NET","PLTR","AVGO","AMD",
    "MU","LRCX","KLAC","AMAT","TXN","SNPS","CDNS",
]

_BOTTOM_KEYS = ["rsi", "drop_pct", "dist_50", "dist_200", "vol_ratio"]
_bottom_train_status: dict = {"running": False, "log": [], "result": None}


def _collect_training_data() -> tuple[np.ndarray, np.ndarray, list]:
    """
    For each training ticker: detect confirmed bottoms (positive) and
    sample non-bottom periods every 6 weeks (negative).
    Returns (pos_matrix, neg_matrix, ticker_stats).
    """
    pos, neg, stats = [], [], []
    for ticker in _TRAIN_TICKERS:
        try:
            t    = yf.Ticker(ticker)
            data = t.history(period="15y", interval="1wk", actions=False)
            if len(data) < 200:
                continue
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            close = pd.to_numeric(data["Close"].squeeze(),  errors="coerce").dropna()
            vol   = pd.to_numeric(data["Volume"].squeeze(), errors="coerce").fillna(0)
            vol   = vol.reindex(close.index).fillna(0)
            ma50  = close.rolling(50).mean()
            ma200 = close.rolling(200).mean()
            rsi_s = _rsi_series(close)

            bottoms = _detect_bottoms(close, rsi_s, ma50, ma200, vol)
            if not bottoms:
                stats.append({"ticker": ticker, "n_bottoms": 0})
                continue

            bot_idx = {b["idx"] for b in bottoms}
            for b in bottoms:
                pos.append([b[k] for k in _BOTTOM_KEYS])

            prices = close.values
            n = len(prices)
            for i in range(104, n - 52, 6):
                if any(abs(i - bi) < 16 for bi in bot_idx):
                    continue
                p = float(prices[i])
                r = float(rsi_s.values[i])
                if np.isnan(r): continue
                m50v  = float(ma50.values[i])  if not np.isnan(ma50.values[i])  else p
                m200v = float(ma200.values[i]) if not np.isnan(ma200.values[i]) else p
                h2y   = float(prices[max(0, i-104):i].max())
                drop  = (p - h2y) / h2y * 100
                avg_v = float(vol.iloc[max(0, i-20):i].mean()) or 1.0
                neg.append([
                    round(r, 1),
                    round(drop, 1),
                    round((p - m50v)  / m50v  * 100, 1),
                    round((p - m200v) / m200v * 100, 1),
                    round(float(vol.values[i]) / avg_v, 2),
                ])
            stats.append({"ticker": ticker, "n_bottoms": len(bottoms)})
        except Exception:
            pass

    return np.array(pos, dtype=float), np.array(neg, dtype=float), stats


def _run_train_model():
    """
    Optimize weights [w1..w5] and Gaussian scales [s1..s5] to separate
    confirmed bottoms (target=100) from non-bottom periods (target=0).

    Loss = MSE of bottom scores from 100
         + consistency penalty (std of bottom scores should be low)
         + penalty for high non-bottom scores
    """
    from scipy.optimize import minimize

    global _BOTTOM_MODEL
    _bottom_train_status.update({"running": True, "log": [], "result": None})

    def log(msg: str):
        _bottom_train_status["log"].append(msg)

    try:
        log("Zbiranje podatkov za trening…")
        pos, neg, ticker_stats = _collect_training_data()
        n_pos, n_neg = len(pos), len(neg)
        log(f"Pozitivnih vzorcev (dna): {n_pos} | Negativnih: {n_neg}")

        if n_pos < 10:
            _bottom_train_status["result"] = {"error": f"Premalo dna ({n_pos}). Potrebno ≥ 10."}
            return

        # Global fingerprint — mean metrics at confirmed bottoms
        mu = pos.mean(axis=0)
        log(f"Globalno povprečje dna: RSI={mu[0]:.1f}, drop={mu[1]:.1f}%, dist50={mu[2]:.1f}%, dist200={mu[3]:.1f}%, vol={mu[4]:.2f}x")

        def score_batch(X: np.ndarray, w: np.ndarray, s: np.ndarray) -> np.ndarray:
            diffs = np.abs(X - mu[None, :]) / np.maximum(s[None, :], 0.5)
            return (np.exp(-0.5 * diffs**2) * w[None, :]).sum(axis=1)

        def objective(params: np.ndarray) -> float:
            w_raw = np.abs(params[:5]) + 0.1
            s_raw = np.abs(params[5:]) + 0.5
            w = w_raw / w_raw.sum() * 100        # normalize to sum=100

            b = score_batch(pos, w, s_raw)
            n = score_batch(neg, w, s_raw)

            loss = (
                (100.0 - b.mean())**2 * 2.0      # push bottom mean → 100
                + b.std()**2 * 8.0               # minimize spread across bottoms
                + n.mean()**2 * 1.5              # suppress non-bottom scores
            )
            return float(loss)

        # Starting point: current weights + std-based scales
        pos_std = pos.std(axis=0).clip(min=2.0)
        x0 = np.array([14.1, 26.8, 20.9, 25.0, 13.2,   # weights
                        *pos_std.tolist()])               # scales

        log("Optimizacija z L-BFGS-B (do 3000 iteracij)…")
        result = minimize(
            objective, x0,
            method="L-BFGS-B",
            bounds=[(0.5, 70)] * 5 + [(1.0, 60)] * 5,
            options={"maxiter": 3000, "ftol": 1e-12, "gtol": 1e-8},
        )

        w_opt = np.abs(result.x[:5])
        s_opt = np.abs(result.x[5:]) + 0.5
        w_norm = (w_opt / w_opt.sum() * 100).round(1)
        s_opt  = s_opt.round(2)

        b_final = score_batch(pos, w_norm, s_opt)
        n_final = score_batch(neg, w_norm, s_opt)

        log(f"Optimizacija končana. Povprečni score pri dnih: {b_final.mean():.1f} ± {b_final.std():.1f}")
        log(f"Povprečni score izven dna: {n_final.mean():.1f}")
        log(f"Uteži: {dict(zip(_BOTTOM_KEYS, w_norm.tolist()))}")
        log(f"Scale: {dict(zip(_BOTTOM_KEYS, s_opt.tolist()))}")

        model = {
            "weights": dict(zip(_BOTTOM_KEYS, w_norm.tolist())),
            "scales":  dict(zip(_BOTTOM_KEYS, s_opt.tolist())),
            "mus":     dict(zip(_BOTTOM_KEYS, mu.round(2).tolist())),
            "trained_at":           datetime.now().isoformat(),
            "n_pos":                int(n_pos),
            "n_neg":                int(n_neg),
            "mean_bottom_score":    round(float(b_final.mean()), 1),
            "std_bottom_score":     round(float(b_final.std()),  1),
            "mean_non_bottom_score":round(float(n_final.mean()), 1),
            "separation":           round(float(b_final.mean() - n_final.mean()), 1),
            "ticker_stats":         ticker_stats,
        }

        with open(_BOTTOM_MODEL_FILE, "w") as f:
            json.dump(model, f, indent=2)
        _BOTTOM_MODEL = model
        _bottom_train_status["result"] = model
        log("Model shranjen → ogm_bottom_model.json")

    except Exception as e:
        _bottom_train_status["result"] = {"error": str(e)}
        log(f"Napaka: {e}")
    finally:
        _bottom_train_status["running"] = False


@app.post("/api/bottom/train")
async def api_bottom_train(background_tasks: BackgroundTasks):
    if _bottom_train_status["running"]:
        raise HTTPException(409, "Trening že teče")
    background_tasks.add_task(_run_train_model)
    return {"status": "started", "tickers": len(_TRAIN_TICKERS)}


@app.get("/api/bottom/train")
async def api_bottom_train_status():
    return {**_bottom_train_status, "model": _BOTTOM_MODEL}


_bottom_cache: dict = {"results": [], "updated_at": None, "scanning": False, "total": 0, "done": 0}


def _run_bottom_scan(tickers: list[str], min_score: float = 0):
    _bottom_cache.update({"scanning": True, "total": len(tickers), "done": 0, "results": []})
    results = []
    for ticker in tickers:
        try:
            d = _bottom_analyze_ticker(ticker)
            if d["score"] >= min_score:
                results.append({
                    "ticker":     d["ticker"],
                    "ime":        d["ime"],
                    "sektor":     d["sektor"],
                    "mcap":       d["mcap"],
                    "cena":       d["cena"],
                    "score":      d["score"],
                    "n_bottoms":  d["n_bottoms"],
                    "rsi":        d["current"]["rsi"],
                    "drop_pct":   d["current"]["drop_pct"],
                    "dist_200":   d["current"]["dist_200"],
                    "rev_growth": d["rev_growth"],
                    "eps_growth": d["eps_growth"],
                })
        except Exception:
            pass
        finally:
            _bottom_cache["done"] += 1
    results.sort(key=lambda x: x["score"], reverse=True)
    _bottom_cache.update({"results": results, "updated_at": datetime.now().isoformat(),
                          "scanning": False, "done": len(tickers), "total": len(tickers)})


@app.get("/api/bottom/analyze/{ticker}")
async def api_bottom_analyze(ticker: str):
    try:
        return _bottom_analyze_ticker(ticker.upper())
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/bottom/scan")
async def api_bottom_scan_start(background_tasks: BackgroundTasks, min_score: float = 0):
    if _bottom_cache["scanning"]:
        raise HTTPException(409, "Scan ze tece")
    background_tasks.add_task(_run_bottom_scan, NASDAQ100, min_score)
    return {"status": "started", "total": len(NASDAQ100)}


@app.get("/api/bottom/scan")
async def api_bottom_scan_status():
    return _bottom_cache


# ─── Posts / Feed endpoints ───────────────────────────────────────────────────
@app.get("/api/posts")
async def api_get_posts():
    return {"posts": _load_posts()}

@app.post("/api/posts")
async def api_create_post(body: PostIn):
    if body.password != ADMIN_PASSWORD:
        raise HTTPException(401, "Napačno geslo")
    import uuid
    posts = _load_posts()
    post = {
        "id":       str(uuid.uuid4()),
        "title":    body.title,
        "content":  body.content,
        "category": body.category,
        "author":   body.author,
        "date":     datetime.now().strftime("%Y-%m-%d"),
    }
    posts.insert(0, post)
    _save_posts(posts)
    return post

@app.delete("/api/posts/{post_id}")
async def api_delete_post(post_id: str, body: DeleteIn):
    if body.password != ADMIN_PASSWORD:
        raise HTTPException(401, "Napačno geslo")
    posts = _load_posts()
    posts = [p for p in posts if p["id"] != post_id]
    _save_posts(posts)
    return {"ok": True}
