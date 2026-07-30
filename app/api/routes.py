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
        return 1.38

@router.get("/positions", response_model=PortfolioResponse)
async def get_portfolio_positions():
    try:
        # 1. Fetch raw positions, options, and balances from SnapTrade
        raw_equities, raw_options, raw_balances = await fetch_all_user_positions()
        
        # 2. Reconcile positions and calculate sector collateral
        positions = reconcile_positions(raw_equities, raw_options)
        sectors = calculate_sector_summaries(positions)
        
        # 3. Capital and Cash Calculations
        usd_committed = sum(s.capital_committed for s in sectors)
        usd_cash = 0.0
        net_portfolio_usd = 0.0

        # Parse SnapTrade balance object
        for bal in raw_balances:
            if isinstance(bal, dict):
                # Extract actual settled cash
                cash_val = bal.get("cash") or bal.get("amount") or 0.0
                if isinstance(cash_val, (int, float)):
                    usd_cash += float(cash_val)
                elif isinstance(cash_val, dict):
                    usd_cash += float(cash_val.get("amount", 0.0))

                # Extract total account net value if SnapTrade provides it
                tot_val = bal.get("total") or bal.get("net_liquidation_value")
                if isinstance(tot_val, (int, float)):
                    net_portfolio_usd += float(tot_val)
                elif isinstance(tot_val, dict):
                    net_portfolio_usd += float(tot_val.get("amount", 0.0))

        # If SnapTrade doesn't return total equity directly in balances, 
        # Total Portfolio Equity = Deployed Option Collateral + Actual Settled Cash
        if net_portfolio_usd == 0.0:
            net_portfolio_usd = usd_committed + usd_cash

        # 4. Apply FX rate
        fx_rate = get_usd_cad_rate()
        
        return PortfolioResponse(
            account_id="ALL_ACCOUNTS",
            updated_at=datetime.now(timezone.utc).isoformat(),
            fx_rate_usd_cad=fx_rate,
            total_capital=CurrencyValue(
                usd=round(net_portfolio_usd, 2),
                cad=round(net_portfolio_usd * fx_rate, 2)
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