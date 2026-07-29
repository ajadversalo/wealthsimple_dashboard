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
        # 1. Unpack all 3 returned items from SnapTrade
        raw_equities, raw_options, raw_balances = await fetch_all_user_positions()
        
        # 2. Reconcile positions and sectors
        positions = reconcile_positions(raw_equities, raw_options)
        sectors = calculate_sector_summaries(positions)
        
        # 3. Capital and Cash Calculations
        usd_committed = sum(s.capital_committed for s in sectors)
        net_portfolio_usd = 0.0

        for bal in raw_balances:
            if isinstance(bal, dict):
                # Pull Net Liquidation Value directly from brokerage
                total_obj = bal.get("total_value") or bal.get("total")
                if isinstance(total_obj, dict):
                    net_portfolio_usd += float(total_obj.get("amount", 0.0))
                elif isinstance(total_obj, (int, float)):
                    net_portfolio_usd += float(total_obj)

        # Fallback if SnapTrade balance total is 0: Net Value = Collateral + True Settled Cash (~$1,800 USD)
        if net_portfolio_usd == 0.0:
            usd_cash = 1800.00
            net_portfolio_usd = usd_committed + usd_cash
        else:
            # Free cash is the remaining net portfolio equity not locked in collateral
            usd_cash = max(0.0, net_portfolio_usd - usd_committed)

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