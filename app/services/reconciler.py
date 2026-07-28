# app/services/reconciler.py

from typing import List, Dict, Any, Optional
from app.schemas.positions import PositionItem, StrategyType, UnderlyingLeg, OptionLeg, SectorSummary
from app.services.market_data import fetch_underlying_prices

SECTOR_MAP = {
    "BAC": "Financials",
    "BMY": "Healthcare",
    "KHC": "Consumer Staples",
    "PFE": "Healthcare",
    "SOFI": "Financials",
}

def extract_ticker_symbol(val: Any) -> str:
    """Recursively extracts a string ticker symbol from raw string/dict structures."""
    if not val:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        sym = val.get("symbol") or val.get("raw_symbol") or val.get("ticker")
        if isinstance(sym, str):
            return sym.strip()
        if isinstance(sym, dict):
            return extract_ticker_symbol(sym)
    if hasattr(val, "symbol"):
        return extract_ticker_symbol(getattr(val, "symbol"))
    return ""

def extract_industry(data: dict, ticker: str) -> str:
    sym_obj = data.get("symbol") if isinstance(data.get("symbol"), dict) else {}
    if not sym_obj and isinstance(data.get("option_symbol"), dict):
        sym_obj = data["option_symbol"].get("underlying_symbol") or {}

    industry = sym_obj.get("industry") or sym_obj.get("sector")
    if not industry or industry in ["Common Stock", "Equity"]:
        industry = SECTOR_MAP.get(ticker.upper(), "Equity")
    return industry

def calculate_moneyness(option_type: str, strike: float, stock_price: float) -> str:
    """Returns ITM or OTM relative to underlying stock price."""
    if not stock_price or not strike:
        return "UNKNOWN"
    
    is_call = "CALL" in option_type.upper()
    if is_call:
        return "ITM" if stock_price > strike else "OTM"
    else:
        return "ITM" if stock_price < strike else "OTM"

def reconcile_positions(
    raw_equities: List[Dict[str, Any]], 
    raw_options: List[Dict[str, Any]],
    live_prices: Optional[Dict[str, float]] = None
) -> List[PositionItem]:
    
    positions: List[PositionItem] = []
    equity_pool: Dict[str, float] = {}
    equity_meta: Dict[str, dict] = {}

    # 1. Map Equities
    for eq in raw_equities:
        sym = extract_ticker_symbol(eq.get("symbol"))
        if sym:
            qty = float(eq.get("units") or eq.get("quantity") or 0)
            equity_pool[sym] = equity_pool.get(sym, 0.0) + qty
            equity_meta[sym] = eq

    # Collect distinct tickers needing market quotes
    target_tickers = set(equity_pool.keys())
    
    # Pre-parse option symbols to add to ticker set
    for opt in raw_options:
        top = opt.get("symbol") if isinstance(opt.get("symbol"), dict) else {}
        opt_sym = top.get("option_symbol") if isinstance(top.get("option_symbol"), dict) else opt.get("option_symbol") or {}
        underlying = opt_sym.get("underlying_symbol") if isinstance(opt_sym, dict) else None
        sym = extract_ticker_symbol(underlying) or extract_ticker_symbol(top)
        if sym:
            target_tickers.add(sym)

    # 2. Fetch live stock quotes if not explicitly provided
    if live_prices is None:
        live_prices = fetch_underlying_prices(list(target_tickers))

    # 3. Process Options
    for opt in raw_options:
        top = opt.get("symbol") if isinstance(opt.get("symbol"), dict) else {}
        opt_sym = top.get("option_symbol") if isinstance(top.get("option_symbol"), dict) else opt.get("option_symbol") or {}
        underlying = opt_sym.get("underlying_symbol") if isinstance(opt_sym, dict) else None
        symbol = extract_ticker_symbol(underlying) or extract_ticker_symbol(top)

        contract_sym = str(opt_sym.get("ticker") or symbol).strip()
        strike = float(opt_sym.get("strike_price") or 0.0)
        exp_date = str(opt_sym.get("expiration_date") or "")
        is_call = "CALL" in str(opt_sym.get("option_type") or "").upper()
        
        qty = float(opt.get("units") or opt.get("quantity") or 0.0)
        is_short = qty < 0
        required_shares = abs(qty) * 100
        available_shares = equity_pool.get(symbol, 0.0)
        opt_price = float(opt.get("price") or opt.get("avg_price") or 0.0)

        industry = extract_industry(opt, symbol)
        stock_price = live_prices.get(symbol, 0.0)

        option_leg_data = OptionLeg(
            contract_symbol=contract_sym,
            option_type="CALL" if is_call else "PUT",
            strike_price=strike,
            expiration_date=exp_date,
            quantity=qty,
            avg_price=opt_price if opt_price > 0 else None,
            moneyness=calculate_moneyness("CALL" if is_call else "PUT", strike, stock_price)
        )

        # Covered Call
        if is_call and is_short and available_shares >= required_shares:
            eq_match = equity_meta.get(symbol, {})
            avg_p = float(eq_match.get("average_buy_price") or eq_match.get("avg_price") or 0.0)
            
            positions.append(PositionItem(
                symbol=symbol,
                strategy=StrategyType.COVERED_CALL,
                industry=industry,
                current_price=stock_price,
                underlying=UnderlyingLeg(shares=required_shares, avg_purchase_price=avg_p),
                option_leg=option_leg_data
            ))
            equity_pool[symbol] -= required_shares

        # Cash-Secured Put
        elif not is_call and is_short:
            positions.append(PositionItem(
                symbol=symbol,
                strategy=StrategyType.CASH_SECURED_PUT,
                industry=industry,
                current_price=stock_price,
                underlying=None,
                option_leg=option_leg_data
            ))

    # 4. Catch Unmatched Long Shares (Standalone Equities)
    for symbol, remaining_shares in equity_pool.items():
        if remaining_shares > 0:
            eq_match = equity_meta.get(symbol, {})
            avg_p = float(eq_match.get("average_buy_price") or eq_match.get("avg_price") or 0.0)
            stock_price = live_prices.get(symbol, 0.0)
            
            positions.append(PositionItem(
                symbol=symbol,
                strategy=StrategyType.LONG_EQUITY if hasattr(StrategyType, "LONG_EQUITY") else "LONG_EQUITY",
                industry=extract_industry(eq_match, symbol),
                current_price=stock_price,
                underlying=UnderlyingLeg(shares=remaining_shares, avg_purchase_price=avg_p),
                option_leg=None
            ))

    # 5. Calculate Portfolio Percentages
    total_val = 0.0
    pos_vals = []

    for pos in positions:
        val = 0.0
        if pos.underlying and pos.underlying.shares:
            p = pos.current_price or pos.underlying.avg_purchase_price or 0.0
            val = pos.underlying.shares * p
        elif pos.strategy == StrategyType.CASH_SECURED_PUT and pos.option_leg:
            strike = pos.option_leg.strike_price or 0.0
            contracts = abs(pos.option_leg.quantity)
            val = strike * 100 * contracts

        pos_vals.append(val)
        total_val += val

    if total_val > 0:
        for idx, pos in enumerate(positions):
            pos.portfolio_pct = round((pos_vals[idx] / total_val) * 100, 2)

    return positions

def calculate_sector_summaries(positions: list[PositionItem]) -> list[SectorSummary]:
    """
    Groups positions by industry sector and calculates total capital 
    committed and overall portfolio weight percentage per sector.
    """
    sector_capitals: dict[str, float] = {}
    sector_tickers: dict[str, set[str]] = {}
    total_portfolio_capital = 0.0

    for pos in positions:
        cap = 0.0
        
        if pos.underlying and pos.underlying.shares:
            p = pos.current_price or pos.underlying.avg_purchase_price or 0.0
            cap = pos.underlying.shares * p
        elif pos.strategy == StrategyType.CASH_SECURED_PUT and pos.option_leg:
            strike = pos.option_leg.strike_price or 0.0
            contracts = abs(pos.option_leg.quantity)
            cap = strike * 100 * contracts

        industry = pos.industry or "Uncategorized"
        
        sector_capitals[industry] = sector_capitals.get(industry, 0.0) + cap
        total_portfolio_capital += cap
        
        if industry not in sector_tickers:
            sector_tickers[industry] = set()
        sector_tickers[industry].add(pos.symbol)

    sectors: list[SectorSummary] = []
    
    if total_portfolio_capital > 0:
        for ind, cap in sector_capitals.items():
            pct = round((cap / total_portfolio_capital) * 100, 2)
            sectors.append(
                SectorSummary(
                    industry=ind,
                    capital_committed=round(cap, 2),
                    portfolio_pct=pct,
                    tickers=sorted(list(sector_tickers[ind]))
                )
            )
            
    sectors.sort(key=lambda s: s.portfolio_pct, reverse=True)
    return sectors