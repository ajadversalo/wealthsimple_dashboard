import logging
import json
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import yfinance as yf
import asyncio

from app.schemas.portfolio import PortfolioResponse, CurrencyValue
from app.services.reconciler import (
    reconcile_positions,
    calculate_sector_summaries,
    calculate_broker_totals,
    normalize_account_label,
)
from app.services.snaptrade import fetch_all_user_positions
from app.services.csp_screener import screen_cash_secured_puts

router = APIRouter()
logger = logging.getLogger(__name__)


def build_account_map(raw_accounts, raw_equities, raw_options):
    """Build stable account labels, including a fallback for unnamed WS accounts."""
    account_map = {
        acc.get("id"): normalize_account_label(acc)
        for acc in raw_accounts
        if isinstance(acc, dict) and acc.get("id")
    }

    # Prefer explicit deployment configuration when available.
    swing_id = os.getenv("SNAPTRADE_SWING_ACCOUNT_ID")
    options_id = os.getenv("SNAPTRADE_OPTIONS_ACCOUNT_ID")
    if swing_id:
        account_map[swing_id] = "WEALTHSIMPLE SWING"
    if options_id:
        account_map[options_id] = "WEALTHSIMPLE OPTIONS"

    wealthsimple_ids = {
        acc_id for acc_id, label in account_map.items() if label.startswith("WEALTHSIMPLE")
    }
    option_account_ids = {
        item.get("account_id")
        for item in raw_options
        if isinstance(item, dict) and item.get("account_id") in wealthsimple_ids
    }

    # SnapTrade can return two Wealthsimple accounts with identical generic
    # metadata. If options exist in exactly one of them, the other is Swing.
    if len(wealthsimple_ids) == 2 and len(option_account_ids) == 1:
        option_account_id = next(iter(option_account_ids))
        account_map[option_account_id] = "WEALTHSIMPLE OPTIONS"
        swing_account_id = next(iter(wealthsimple_ids - {option_account_id}))
        account_map[swing_account_id] = "WEALTHSIMPLE SWING"

    logger.info("Resolved account labels: %s", account_map)
    return account_map


@router.get("/screener/cash-secured-puts")
async def get_cash_secured_put_candidates():
    """Run the CSP screener and return the top eligible put per symbol."""
    try:
        candidates = await asyncio.to_thread(screen_cash_secured_puts)
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "candidate_count": len(candidates),
            "candidates": candidates,
        }
    except Exception as exc:
        logger.error("CSP screener failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run CSP screener") from exc


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
        # 1. Fetch raw positions, options, balances, and accounts from SnapTrade
        raw_equities, raw_options, raw_balances, raw_accounts = await fetch_all_user_positions()

        account_map = build_account_map(raw_accounts, raw_equities, raw_options)

        # 2. Reconcile Positions & Sectors
        positions = reconcile_positions(raw_equities, raw_options, account_map=account_map)
        sectors = calculate_sector_summaries(positions)

        fx_rate = get_usd_cad_rate()

        # 3. Aggregate Actual Liquid Cash across all brokers
        usd_cash_balance = 0.0

        for bal in raw_balances:
            if isinstance(bal, dict):
                currency_code = bal.get("currency", {}).get("code", "USD")
                cash_amount = float(bal.get("cash", 0.0))

                if currency_code == "USD":
                    usd_cash_balance += cash_amount
                elif currency_code == "CAD":
                    usd_cash_balance += cash_amount / fx_rate

        # 4. Extract Stock Value & Option Buyback Liability
        long_equity_usd = 0.0
        short_options_liability_usd = 0.0

        for pos in positions:
            underlying = getattr(pos, "underlying", None) if not isinstance(pos, dict) else pos.get("underlying")
            option_leg = getattr(pos, "option_leg", None) if not isinstance(pos, dict) else pos.get("option_leg")
            current_price = getattr(pos, "current_price", 0.0) if not isinstance(pos, dict) else pos.get("current_price", 0.0)

            # Long shares/crypto real market value
            if underlying:
                shares = getattr(underlying, "shares", 0.0) if not isinstance(underlying, dict) else underlying.get("shares", 0.0)
                if shares and current_price:
                    long_equity_usd += float(shares) * float(current_price)

            # Short option current market cost to close
            if option_leg:
                qty = getattr(option_leg, "quantity", 0.0) if not isinstance(option_leg, dict) else option_leg.get("quantity", 0.0)
                opt_mkt_price = getattr(option_leg, "avg_price", 0.0) if not isinstance(option_leg, dict) else option_leg.get("avg_price", 0.0)

                qty_val = float(qty) if qty is not None else 0.0
                opt_p_val = float(opt_mkt_price) if opt_mkt_price is not None else 0.0

                if qty_val < 0:
                    short_options_liability_usd += abs(qty_val) * opt_p_val * 100.0

        # 5. True Net Portfolio Equity = Liquid Cash + Shares Value - Option Liability
        net_portfolio_usd = (usd_cash_balance + long_equity_usd) - short_options_liability_usd

        # 6. Calculate per-broker metrics
        broker_totals = calculate_broker_totals(
            positions=positions,
            fx_rate=fx_rate,
            raw_accounts=raw_accounts,
            raw_balances=raw_balances,
            account_map=account_map,
        )

        return PortfolioResponse(
            account_id="ALL_ACCOUNTS",
            updated_at=datetime.now(timezone.utc).isoformat(),
            fx_rate_usd_cad=fx_rate,
            total_capital=CurrencyValue(
                usd=round(net_portfolio_usd, 2),
                cad=round(net_portfolio_usd * fx_rate, 2),
            ),
            remaining_capital=CurrencyValue(
                usd=round(usd_cash_balance, 2),
                cad=round(usd_cash_balance * fx_rate, 2),
            ),
            broker_totals=broker_totals,  # <-- ADDED HERE
            account_totals=broker_totals,
            positions=positions,
            sectors=sectors,
        )
    except Exception as e:
        logger.error(f"Error fetching portfolio positions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch portfolio positions: {str(e)}")
