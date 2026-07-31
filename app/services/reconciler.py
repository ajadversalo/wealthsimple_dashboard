from typing import Any, Dict, List, Optional
from app.schemas.portfolio import (
    BrokerSummary,
    CurrencyValue,
    PortfolioResponse,
    PositionItem,
    SectorSummary,
    StrategyType,
    UnderlyingLeg,
    OptionLeg,
)
from app.constants import SECTOR_MAP
from app.services.market_data import fetch_underlying_prices

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def resolve_broker(raw_item: dict, account_map: Optional[Dict[str, str]] = None) -> str:
    """Identify institution from SnapTrade payload using account mapping and exchange metadata."""
    if not isinstance(raw_item, dict):
        return "OTHER"

    # 1. Direct lookup via account_id mapping
    acc_id = raw_item.get("account_id")
    if not acc_id and isinstance(raw_item.get("account"), dict):
        acc_id = raw_item["account"].get("id")

    if account_map and acc_id in account_map:
        return account_map[acc_id]

    # 2. Check exchange metadata (e.g., Kraken crypto)
    sym_obj = raw_item.get("symbol", {})
    if isinstance(sym_obj, dict):
        base_sym = sym_obj.get("symbol") if isinstance(sym_obj.get("symbol"), dict) else {}
        exchange_obj = base_sym.get("exchange") or {}
        exchange_name = str(exchange_obj.get("name") or exchange_obj.get("code") or "").upper()

        if "KRAKEN" in exchange_name or "KRAK" in exchange_name:
            return "KRAKEN"

    # 3. Check inline account metadata
    account_info = raw_item.get("account")
    institution = ""
    if isinstance(account_info, dict):
        brokerage = account_info.get("brokerage") or {}
        institution = (
            brokerage.get("name")
            or account_info.get("institution_name")
            or account_info.get("brokerage_name")
            or ""
        )

    institution = str(institution).upper()

    if "WEALTHSIMPLE" in institution:
        return "WEALTHSIMPLE"
    if "KRAKEN" in institution:
        return "KRAKEN"
    if any(k in institution for k in ["INTERACTIVE", "IBKR"]):
        return "IBKR"

    # 4. Default fallback
    return "WEALTHSIMPLE"


def resolve_asset_class(raw_item: dict, broker: str) -> str:
    """Categorize asset type based on security details or broker."""
    if broker == "KRAKEN":
        return "CRYPTO"

    sym_obj = raw_item.get("symbol", {}).get("symbol", {})
    if isinstance(sym_obj, dict):
        sec_type = sym_obj.get("type", {}).get("code", "").lower()
        if sec_type == "crypto":
            return "CRYPTO"
        if "option" in sec_type:
            return "OPTIONS"

    if raw_item.get("option_leg") is not None:
        return "OPTIONS"

    return "EQUITY"


KRAKEN_MAP = {"XXRP": "XRP", "XXBT": "BTC", "XETH": "ETH", "ZUSD": "USD"}


def extract_ticker_symbol(val: Any) -> str:
    """Recursively extracts a string ticker symbol from raw string/dict structures."""
    if not val:
        return ""

    symbol = ""
    if isinstance(val, str):
        symbol = val.strip()
    elif isinstance(val, dict):
        sym = val.get("symbol") or val.get("raw_symbol") or val.get("ticker")
        if isinstance(sym, str):
            symbol = sym.strip()
        elif isinstance(sym, dict):
            return extract_ticker_symbol(sym)
    elif hasattr(val, "symbol"):
        return extract_ticker_symbol(getattr(val, "symbol"))

    return KRAKEN_MAP.get(symbol.upper(), symbol.upper())


def extract_industry(data: dict, ticker: str) -> str:
    sym_obj = data.get("symbol") if isinstance(data.get("symbol"), dict) else {}
    if not sym_obj and isinstance(data.get("option_symbol"), dict):
        sym_obj = data["option_symbol"].get("underlying_symbol") or {}

    industry = sym_obj.get("industry") or sym_obj.get("sector")

    sec_type = sym_obj.get("type", {}).get("code", "").lower()
    is_crypto = sec_type == "crypto" or ticker.upper() in {"XRP", "SOL", "BTC", "ETH"}

    if is_crypto:
        return "Crypto"

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


# ==========================================
# BROKER TOTALS CALCULATOR
# ==========================================

# app/services/reconciler.py

def calculate_broker_totals(positions, fx_rate: float, raw_accounts: list, raw_balances: list = None) -> dict:
    broker_cash = {}
    broker_long_equity = {}
    broker_option_liabilities = {}
    broker_collateral = {}

    # 1. Map account_id -> normalized broker name
    account_to_broker = {}
    for acc in (raw_accounts or []):
        acc_id = acc.get("id")
        brokerage_info = acc.get("brokerage", {})
        b_name = (
            brokerage_info.get("name")
            or acc.get("institution_name")
            or acc.get("brokerage_name")
            or ""
        ).upper()

        if acc_id:
            if "WEALTHSIMPLE" in b_name:
                account_to_broker[acc_id] = "WEALTHSIMPLE"
            elif "KRAKEN" in b_name:
                account_to_broker[acc_id] = "KRAKEN"
            elif "INTERACTIVE" in b_name or "IBKR" in b_name:
                account_to_broker[acc_id] = "IBKR"
            else:
                account_to_broker[acc_id] = b_name or "OTHER"

    # 2. Extract Cash (Remaining Capital) per broker from raw_balances
    if raw_balances:
        for bal in raw_balances:
            if isinstance(bal, dict):
                acc_info = bal.get("account", {})
                acc_id = bal.get("account_id")
                if not acc_id:
                    acc_id = acc_info.get("id") if isinstance(acc_info, dict) else acc_info
                
                broker_name = account_to_broker.get(acc_id, "OTHER")

                currency_code = bal.get("currency", {}).get("code", "USD")
                cash_amount = float(bal.get("cash", 0.0))

                cash_usd = cash_amount if currency_code == "USD" else (cash_amount / fx_rate if fx_rate else cash_amount)
                broker_cash[broker_name] = broker_cash.get(broker_name, 0.0) + cash_usd

    # 3. Calculate Position Long Equity, Option Liabilities, and CSP Collateral
    for pos in positions:
        broker = getattr(pos, "broker", None) if not isinstance(pos, dict) else pos.get("broker", "OTHER")
        underlying = getattr(pos, "underlying", None) if not isinstance(pos, dict) else pos.get("underlying")
        option_leg = getattr(pos, "option_leg", None) if not isinstance(pos, dict) else pos.get("option_leg")
        current_price = getattr(pos, "current_price", 0.0) if not isinstance(pos, dict) else pos.get("current_price", 0.0)

        # Long Stock / Crypto
        if underlying:
            shares = getattr(underlying, "shares", 0.0) if not isinstance(underlying, dict) else underlying.get("shares", 0.0)
            if shares and current_price:
                val = float(shares) * float(current_price)
                broker_long_equity[broker] = broker_long_equity.get(broker, 0.0) + val

        # Option legs (Liabilities + CSP Collateral)
        if option_leg:
            qty = getattr(option_leg, "quantity", 0.0) if not isinstance(option_leg, dict) else option_leg.get("quantity", 0.0)
            avg_price = getattr(option_leg, "avg_price", 0.0) if not isinstance(option_leg, dict) else option_leg.get("avg_price", 0.0)
            strike = getattr(option_leg, "strike_price", 0.0) if not isinstance(option_leg, dict) else option_leg.get("strike_price", 0.0)
            opt_type = getattr(option_leg, "option_type", "") if not isinstance(option_leg, dict) else option_leg.get("option_type", "")

            qty_val = float(qty or 0.0)
            opt_price = float(avg_price or 0.0)
            strike_val = float(strike or 0.0)

            if qty_val < 0:
                # Option liability = current cost to buy back
                liab = abs(qty_val) * opt_price * 100.0
                broker_option_liabilities[broker] = broker_option_liabilities.get(broker, 0.0) + liab

                # Cash Secured Put collateral reservation
                if opt_type == "PUT":
                    collateral = strike_val * 100.0 * abs(qty_val)
                    broker_collateral[broker] = broker_collateral.get(broker, 0.0) + collateral

    # 4. Synthesize per-broker figures
    all_brokers = set(broker_cash.keys()).union(set(broker_long_equity.keys())).union(set(broker_collateral.keys()))
    result = {}

    for b in all_brokers:
        cash = round(broker_cash.get(b, 0.0), 2)
        long_eq = round(broker_long_equity.get(b, 0.0), 2)
        option_liab = round(broker_option_liabilities.get(b, 0.0), 2)
        collateral = round(broker_collateral.get(b, 0.0), 2)

        # Net Liquidating Value (Matches Wealthsimple App)
        net_usd = round(cash + long_eq - option_liab, 2)
        
        # Capital Deployed in Assets/Collateral
        deployed_usd = round(long_eq + collateral, 2)
        
        # Total Purchasing/Collateral Power
        total_capital_usd = round(cash + deployed_usd, 2)

        result[b] = {
            "broker": b,
            "net_value": {
                "usd": net_usd,
                "cad": round(net_usd * fx_rate, 2),
            },
            "option_liabilities": {
                "usd": option_liab,
                "cad": round(option_liab * fx_rate, 2),
            },
            "remaining_capital": {
                "usd": cash,
                "cad": round(cash * fx_rate, 2),
            },
            "deployed_capital": {
                "usd": deployed_usd,
                "cad": round(deployed_usd * fx_rate, 2),
            },
            "total_capital": {
                "usd": total_capital_usd,
                "cad": round(total_capital_usd * fx_rate, 2),
            },
        }

    return result


# ==========================================
# MAIN RECONCILER & SUMMARY BUILDERS
# ==========================================

def reconcile_positions(
    raw_equities: List[Dict[str, Any]],
    raw_options: List[Dict[str, Any]],
    live_prices: Optional[Dict[str, float]] = None,
    account_map: Optional[Dict[str, str]] = None,
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

    target_tickers = set(equity_pool.keys())

    for opt in raw_options:
        top = opt.get("symbol") if isinstance(opt.get("symbol"), dict) else {}
        opt_sym = (
            top.get("option_symbol")
            if isinstance(top.get("option_symbol"), dict)
            else opt.get("option_symbol") or {}
        )
        underlying = opt_sym.get("underlying_symbol") if isinstance(opt_sym, dict) else None
        sym = extract_ticker_symbol(underlying) or extract_ticker_symbol(top)
        if sym:
            target_tickers.add(sym)

    # 2. Fetch live stock quotes if not provided
    if live_prices is None:
        live_prices = fetch_underlying_prices(list(target_tickers))

    # 3. Process Options
    for opt in raw_options:
        broker = resolve_broker(opt, account_map)
        asset_class = resolve_asset_class(opt, broker)

        top = opt.get("symbol") if isinstance(opt.get("symbol"), dict) else {}
        opt_sym = (
            top.get("option_symbol")
            if isinstance(top.get("option_symbol"), dict)
            else opt.get("option_symbol") or {}
        )
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
            moneyness=calculate_moneyness(
                "CALL" if is_call else "PUT", strike, stock_price
            ),
        )

        # Covered Call
        if is_call and is_short and available_shares >= required_shares:
            eq_match = equity_meta.get(symbol, {})
            avg_p = float(
                eq_match.get("average_buy_price") or eq_match.get("avg_price") or 0.0
            )

            positions.append(
                PositionItem(
                    symbol=symbol,
                    broker=broker,
                    asset_class=asset_class,
                    strategy=StrategyType.COVERED_CALL,
                    industry=industry,
                    current_price=stock_price,
                    underlying=UnderlyingLeg(
                        shares=required_shares, avg_purchase_price=avg_p
                    ),
                    option_leg=option_leg_data,
                )
            )
            equity_pool[symbol] -= required_shares

        # Cash-Secured Put
        elif not is_call and is_short:
            positions.append(
                PositionItem(
                    symbol=symbol,
                    broker=broker,
                    asset_class=asset_class,
                    strategy=StrategyType.CASH_SECURED_PUT,
                    industry=industry,
                    current_price=stock_price,
                    underlying=None,
                    option_leg=option_leg_data,
                )
            )

    # 4. Catch Unmatched Long Shares
    for symbol, remaining_shares in equity_pool.items():
        if remaining_shares > 0:
            eq_match = equity_meta.get(symbol, {})
            broker = resolve_broker(eq_match, account_map)
            asset_class = resolve_asset_class(eq_match, broker)

            avg_p = float(
                eq_match.get("average_buy_price") or eq_match.get("avg_price") or 0.0
            )

            is_crypto = asset_class == "CRYPTO" or symbol in {"XRP", "SOL", "BTC", "ETH"}

            if is_crypto:
                stock_price = float(eq_match.get("price") or 0.0)
            else:
                stock_price = live_prices.get(symbol, 0.0) or float(
                    eq_match.get("price") or 0.0
                )

            positions.append(
                PositionItem(
                    symbol=symbol,
                    broker=broker,
                    asset_class=asset_class,
                    strategy=StrategyType.LONG_EQUITY,
                    industry=extract_industry(eq_match, symbol),
                    current_price=stock_price,
                    underlying=UnderlyingLeg(
                        shares=remaining_shares, avg_purchase_price=avg_p
                    ),
                    option_leg=None,
                )
            )

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


def calculate_sector_summaries(positions: List[PositionItem]) -> List[SectorSummary]:
    """Groups positions by sector and computes total committed capital and weight."""
    sector_capitals: Dict[str, float] = {}
    sector_tickers: Dict[str, set] = {}
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

    sectors: List[SectorSummary] = []

    if total_portfolio_capital > 0:
        for ind, cap in sector_capitals.items():
            pct = round((cap / total_portfolio_capital) * 100, 2)
            sectors.append(
                SectorSummary(
                    industry=ind,
                    capital_committed=round(cap, 2),
                    portfolio_pct=pct,
                    tickers=sorted(list(sector_tickers[ind])),
                )
            )

    sectors.sort(key=lambda s: s.portfolio_pct, reverse=True)
    return sectors


def build_portfolio_response(
    account_id: str,
    updated_at: str,
    fx_rate: float,
    positions: List[PositionItem],
    raw_accounts: Optional[List[Dict[str, Any]]] = None,
) -> PortfolioResponse:
    """Assembles the final PortfolioResponse model including broker_totals and sector metrics."""
    broker_totals = calculate_broker_totals(positions, fx_rate, raw_accounts)
    sectors = calculate_sector_summaries(positions)

    # Compute aggregate global metrics across all brokers
    total_usd = round(sum(b.total_capital.usd for b in broker_totals.values()), 2)
    remaining_usd = round(
        sum(b.remaining_capital.usd for b in broker_totals.values()), 2
    )

    return PortfolioResponse(
        account_id=account_id,
        updated_at=updated_at,
        fx_rate_usd_cad=fx_rate,
        total_capital=CurrencyValue(
            usd=total_usd,
            cad=round(total_usd * fx_rate, 2),
        ),
        remaining_capital=CurrencyValue(
            usd=remaining_usd,
            cad=round(remaining_usd * fx_rate, 2),
        ),
        broker_totals=broker_totals,
        positions=positions,
        sectors=sectors,
    )
