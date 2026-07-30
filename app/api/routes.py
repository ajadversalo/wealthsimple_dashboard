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
        
        fx_rate = get_usd_cad_rate()

        # 3. Capital and Cash Calculations
        usd_committed = sum(s.capital_committed for s in sectors)
        usd_cash_balance = 0.0

        # Parse exact SnapTrade cash structure
        for bal in raw_balances:
            if isinstance(bal, dict):
                currency_code = bal.get("currency", {}).get("code", "USD")
                cash_amount = float(bal.get("cash", 0.0))

                if currency_code == "USD":
                    usd_cash_balance += cash_amount
                elif currency_code == "CAD":
                    usd_cash_balance += (cash_amount / fx_rate)

        # Calculate total market value of long stock holdings (e.g. PFE)
        long_equity_usd = sum(
            pos.market_value 
            for pos in positions 
            if getattr(pos, "shares_owned", 0) > 0
        )

        # Net Portfolio Equity = Total Cash + Long Stock Value
        net_portfolio_usd = usd_cash_balance + long_equity_usd

        # Available cash remaining after options collateral reservation
        available_cash_usd = max(0.0, usd_cash_balance - usd_committed)

        return PortfolioResponse(
            account_id="ALL_ACCOUNTS",
            updated_at=datetime.now(timezone.utc).isoformat(),
            fx_rate_usd_cad=fx_rate,
            total_capital=CurrencyValue(
                usd=round(net_portfolio_usd, 2),
                cad=round(net_portfolio_usd * fx_rate, 2)
            ),
            remaining_capital=CurrencyValue(
                usd=round(available_cash_usd, 2),
                cad=round(available_cash_usd * fx_rate, 2)
            ),
            positions=positions,
            sectors=sectors
        )
    except Exception as e:
        logger.error(f"Error fetching portfolio positions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch portfolio positions: {str(e)}")