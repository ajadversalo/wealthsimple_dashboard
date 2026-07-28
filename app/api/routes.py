import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import yfinance as yf

from app.schemas.positions import PortfolioResponse, CurrencyValue
from app.services.reconciler import reconcile_positions, calculate_sector_summaries
from app.services.snaptrade import fetch_all_user_positions

router = APIRouter()
logger = logging.getLogger(__name__)

def get_usd_cad_rate() -> float:
    try:
        ticker = yf.Ticker("USDCAD=X")
        rate = ticker.fast_info.get("lastPrice")
        return round(float(rate), 4) if rate else 1.38
    except Exception as e:
        logger.warning(f"Failed to fetch USDCAD rate, using fallback 1.38: {e}")
        return 1.38  # Fallback exchange rate if yfinance call fails

@router.get("/positions", response_model=PortfolioResponse)
async def get_portfolio_positions():
    try:
        # 1. Fetch raw data from SnapTrade
        raw_equities, raw_options = await fetch_all_user_positions()
        
        # 2. Reconcile positions and calculate sector summaries
        positions = reconcile_positions(raw_equities, raw_options)
        sectors = calculate_sector_summaries(positions)
        
        # 3. Calculate base USD balances
        usd_committed = sum(s.capital_committed for s in sectors)
        usd_cash = 2500.00  # Hardcoded cash balance (or pull dynamically from SnapTrade balance endpoint)
        
        # 4. Apply FX rate
        fx_rate = get_usd_cad_rate()
        
        return PortfolioResponse(
            account_id="ALL_ACCOUNTS",
            updated_at=datetime.now(timezone.utc).isoformat(),
            fx_rate_usd_cad=fx_rate,
            total_capital=CurrencyValue(
                usd=round(usd_committed, 2),
                cad=round(usd_committed * fx_rate, 2)
            ),
            remaining_capital=CurrencyValue(
                usd=round(usd_cash, 2),
                cad=round(usd_cash * fx_rate, 2)
            ),
            positions=positions,
            sectors=sectors
        )
    except Exception as e:
        logger.error(f"Error fetching portfolio positions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch portfolio positions: {str(e)}")