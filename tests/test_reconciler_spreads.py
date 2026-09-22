from app.schemas.portfolio import StrategyType
from app.services.reconciler import reconcile_positions


def option_holding(
    *, account_id: str, ticker: str, strike: float, expiration: str,
    units: float, average_purchase_price: float, price: float,
):
    return {
        "account_id": account_id,
        "units": units,
        "average_purchase_price": average_purchase_price,
        "price": price,
        "symbol": {
            "option_symbol": {
                "ticker": f"{ticker}-{expiration}-{strike}",
                "option_type": "PUT",
                "strike_price": strike,
                "expiration_date": expiration,
                "underlying_symbol": {"symbol": ticker},
            }
        },
    }


def test_reconcile_pairs_put_credit_spread_legs():
    positions = reconcile_positions(
        raw_equities=[],
        raw_options=[
            option_holding(
                account_id="account-1", ticker="AAPL", strike=100,
                expiration="2026-12-18", units=-1,
                average_purchase_price=200, price=300,
            ),
            option_holding(
                account_id="account-1", ticker="AAPL", strike=95,
                expiration="2026-12-18", units=1,
                average_purchase_price=80, price=100,
            ),
        ],
        live_prices={"AAPL": 105},
        account_map={"account-1": "WEALTHSIMPLE OPTIONS"},
    )

    assert len(positions) == 1
    position = positions[0]
    option = position.option_leg

    assert position.strategy == StrategyType.PUT_CREDIT_SPREAD
    assert option is not None
    assert option.short_strike_price == 100
    assert option.long_strike_price == 95
    assert option.net_credit == 1.2
    assert option.current_debit == 2.0
    assert option.break_even_price == 98.8
    assert option.max_profit == 120.0
    assert option.max_loss == 380.0
    assert option.current_pnl == -80.0
    assert option.moneyness == "OTM"

