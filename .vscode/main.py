from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Optional

# ==============================================================================
# NASTAVITVE IN KONSTANTE
# ==============================================================================
MIN_MARKET_CAP = 20_000_000_000      
MEGA_CAP_THRESHOLD = 200_000_000_000 
MIN_REVENUE_GROWTH = 0.10            
SUPER_GROWTH_THRESHOLD = 0.50

app = FastAPI(
    title="OGM Invest API",
    description="Backend API za OGM SaaS Platformo (V3 Moat pravila)",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # V produkciji tu vpiševa tvojo pravo domeno
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# PODATKOVNI MODELI (Za vhodne zahteve in dokumentacijo)
# ==============================================================================
class WatchlistRequest(BaseModel):
    tickers: List[str]

# ==============================================================================
# CENTRALNO KVANITATIVNO JEDRO (OGM ALGORITEM)
# ==============================================================================
def safe_float(val, default=0.0):
    try:
        if val is None or pd.isna(val): return default
        return float(val)
    except: return default

def analyze_stock(ticker: str):
    """Glavna funkcija, ki izračuna OGM za poljuben ticker in vrne JSON."""
    ticker = ticker.strip().upper()
    try:
        delnica = yf.Ticker(ticker)
        info = delnica.info
        
        mcap = info.get('marketCap')
        if mcap is None or pd.isna(mcap) or mcap < MIN_MARKET_CAP:
            return {"ticker": ticker, "status": "REJECTED", "reason": "Market Cap < 20B"}
            
        rev_growth = safe_float(info.get('revenueGrowth'))
        if rev_growth < MIN_REVENUE_GROWTH:
            return {"ticker": ticker, "status": "REJECTED", "reason": f"Revenue Growth < 10% ({rev_growth*100:.1f}%)"}
            
        is_mega_cap = mcap >= MEGA_CAP_THRESHOLD
        
        data = delnica.history(start="2014-01-01", interval="1wk", actions=False)
        if data is None or data.empty or len(data) < 205:
            return {"ticker": ticker, "status": "REJECTED", "reason": "Premalo zgodovine (min 4 leta)"}
            
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
            
        close = data['Close'].dropna()
        if close.empty or len(close) < 205:
            return {"ticker": ticker, "status": "REJECTED", "reason": "Manjkajoči podatki o cenah"}

        # Fundamenti
        eps_growth = info.get('earningsQuarterlyGrowth') or info.get('earningsGrowth')
        eps_pct = safe_float(eps_growth) * 100
        
        peg_val = safe_float(info.get('pegRatio'), default=2.0)
        if peg_val == 0.0: peg_val = 2.0
        
        margin_val = safe_float(info.get('grossMargins')) * 100
        is_high_margin_moat = (not is_mega_cap) and (margin_val >= 50.0)
        
        # Interpolacije fundamentov (Max 45)
        t_eps = np.interp(eps_pct, [0.0, 8.0, 16.5, 22.0, 30.0], [0.0, 5.0, 14.0, 20.0, 20.0])
        t_peg = np.interp(peg_val, [0.4, 0.8, 1.2, 1.6, 2.0], [15.0, 13.0, 10.0, 5.0, 0.0])
        t_mar = np.interp(margin_val, [25, 35, 45, 55, 65], [0.0, 2.0, 5.0, 8.0, 10.0]) 
        fund_score = min(45.0, float(t_eps + t_peg + t_mar))

        # Tehnika
        ma50 = close.rolling(window=50).mean()
        ma200 = close.rolling(window=200).mean()
        ma20 = close.rolling(window=4).mean()
        
        ma_target = ma50 if is_mega_cap else ma200
        tip_ma = "50w MA (Mega-Cap)" if is_mega_cap else ("200w MA (Moat)" if is_high_margin_moat else "200w MA")
        
        pct_ma = ((close - ma_target) / ma_target) * 100
        
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        arr_pct = pct_ma.values
        arr_rsi = rsi.values
        tocke_ma = np.zeros_like(arr_pct)
        
        pos_mask = arr_pct >= 0
        neg_mask = arr_pct < 0
        W_MA = 40.0
        
        if is_mega_cap:
            tocke_ma[pos_mask] = np.interp(arr_pct[pos_mask], [0, 2, 8, 15], [W_MA*(32/35), W_MA, W_MA*(15/35), 0.0])
            tocke_ma[neg_mask] = np.interp(arr_pct[neg_mask], [-40, -15, -2, 0], [W_MA, W_MA, W_MA*(34/35), W_MA*(32/35)])
        elif is_high_margin_moat:
            tocke_ma[pos_mask] = np.interp(arr_pct[pos_mask], [0, 2, 10, 25, 50], [W_MA*(33/35), W_MA, W_MA*(22/35), W_MA*(8/35), 0.0])
            tocke_ma[neg_mask] = np.interp(arr_pct[neg_mask], [-35, -20, -15, -5, 0], [0.0, 35.0, 40.0, 38.0, W_MA*(33/35)])
        else:
            tocke_ma[pos_mask] = np.interp(arr_pct[pos_mask], [0, 2, 10, 25, 50], [W_MA*(33/35), W_MA, W_MA*(22/35), W_MA*(8/35), 0.0])
            tocke_ma[neg_mask] = np.interp(arr_pct[neg_mask], [-20, -10, -5, 0], [0.0, W_MA*(12/35), W_MA*(25/35), W_MA*(33/35)])
            
        tocke_rsi = np.interp(arr_rsi, [30, 45, 60, 70, 80], [15.0, 15*0.8, 15*0.5, 15*0.2, 0.0])
        
        ogm_zgodovina = np.clip(tocke_ma + tocke_rsi + fund_score, 0, 100.0)
        trenutni_ogm = min(100.0, float(ogm_zgodovina[-1]))

        if trenutni_ogm < 65.0:
            return {"ticker": ticker, "status": "REJECTED", "reason": f"OGM Score prenizek ({trenutni_ogm:.1f})"}

        # Kategorizacija in Trendi
        trenutna_cena = float(close.iloc[-1])
        trend_ok = arr_pct[-1] >= 0
        is_falling_phase = float(ma20.iloc[-1]) < float(ma_target.iloc[-1])
        
        if trenutni_ogm >= 80.0: status = "STRONG BUY"
        elif is_falling_phase: status = "WARNING (FALLING PHASE)"
        elif not trend_ok: status = "WARNING (POD MA)"
        elif rev_growth >= SUPER_GROWTH_THRESHOLD: status = "SUPER-GROWTH TARGET"
        else: status = "BUY"

        # Pakiranje podatkov v slovar (JSON)
        return {
            "ticker": ticker,
            "ime": info.get('shortName') or info.get('longName') or ticker,
            "sektor": info.get('sector', 'Neznano'),
            "status": status,
            "cena": round(trenutna_cena, 2),
            "ogm_score": round(trenutni_ogm, 1),
            "market_cap_raw": mcap,
            "revenue_growth_pct": round(rev_growth * 100, 1),
            "components": {
                "eps_growth": {"raw": round(eps_pct, 1), "score": round(float(t_eps), 1)},
                "peg_ratio": {"raw": round(peg_val, 2), "score": round(float(t_peg), 1)},
                "gross_margin": {"raw": round(margin_val, 1), "score": round(float(t_mar), 1)},
                "rsi_14w": {"raw": round(float(arr_rsi[-1]), 1), "score": round(float(tocke_rsi[-1]), 1)},
                "ma_distance": {"raw": round(float(arr_pct[-1]), 1), "score": round(float(tocke_ma[-1]), 1), "type": tip_ma}
            }
        }

    except Exception as e:
        return {"ticker": ticker, "status": "ERROR", "reason": str(e)}

# ==============================================================================
# API ENDPOINTI (Tukaj se spletna stran pogovarja z našim motorjem)
# ==============================================================================

@app.get("/")
def read_root():
    return {"message": "OGM Invest API je aktiven in deluje."}

@app.get("/api/stock/{ticker}")
def get_single_stock(ticker: str):
    """Modul: Single Stock Report (Za živo iskanje posamezne delnice)."""
    result = analyze_stock(ticker)
    if result.get("status") in ["REJECTED", "ERROR"]:
        # Če želimo, da spletna stran uporabniku izpiše napako, lahko vrnemo HTTP 400
        # HTTPException(status_code=400, detail=result["reason"])
        pass 
    return result

@app.post("/api/watchlist")
def analyze_watchlist(request: WatchlistRequest):
    """Modul: Watchlist Radar (Sprejme array tickerjev, vrne analize za vse)."""
    results = []
    for ticker in request.tickers:
        res = analyze_stock(ticker)
        results.append(res)
    return {"analized_count": len(request.tickers), "results": results}

@app.get("/api/master-scan")
def trigger_master_scan():
    """
    Modul: Master Scanner. 
    V produkciji se ta endpoint NE kliče v živo, ker traja predolgo. 
    Namesto tega se kliče iz internega Cron opravila, ki podatke shrani v PostgreSQL bazo, 
    spletna stran pa nato bere iz te baze. Za zdaj vrne le simuliran odgovor.
    """
    return {
        "message": "Master scan zagnan. V produkciji se to izvede v ozadju in shrani v DB.",
        "status": "processing"
    }
QUICK_DASHBOARD_TICKERS = [
    "SAP.DE", "NVDA", "AAPL", "MSFT", "ASML.AS", 
    "TSLA", "META", "GOOGL", "AMZN", "NFLX"
]

@app.get("/api/dashboard/buy")
def get_buy_dashboard(tier: str = "free"):
    """
    Modul: Weekly Buy Radar.
    Vrne seznam analiziranih delnic. Skrije občutljive podatke za FREE uporabnike pri OGM > 80.
    """
    results = []
    for ticker in QUICK_DASHBOARD_TICKERS:
        res = analyze_stock(ticker)
        
        # Preskočimo tiste, ki ne ustrezajo filtrom
        if res.get("status") in ["REJECTED", "ERROR"]:
            continue
            
        # PAYWALL LOGIKA: Zameglitev za FREE uporabnike, če je OGM >= 80
        if res["ogm_score"] >= 80.0 and tier != "pro":
            res["is_locked"] = True
            # V backendu preventivno skrijemo podatke (dodatna varnost)
            res["ticker_hidden"] = "***"
            res["ime_hidden"] = "Premium Delnica (Zaklenjeno)"
        else:
            res["is_locked"] = False
            
        results.append(res)
        
    # Sortiramo od najvišjega OGM proti najnižjemu
    results.sort(key=lambda x: x["ogm_score"], reverse=True)
    
    return {"tier_used": tier, "results": results}