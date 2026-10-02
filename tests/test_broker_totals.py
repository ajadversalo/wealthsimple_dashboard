from app.services.reconciler import calculate_broker_totals

OPTIONS_ID = "9c7fd8bd-598c-431f-af42-fe1c12b0b768"
SWING_ID = "92fe0874-cbca-4612-a2cf-3f0d4a3926df"
FX = 1.4256


def test_options_net_value_uses_account_nav_not_cash_wallets():
    raw_accounts = [
        {
            "id": OPTIONS_ID,
            "name": "Wealthsimple Trade PERSONAL",
            "balance": {"total": {"amount": 26547.12, "currency": "CAD"}},
        },
        {
            "id": SWING_ID,
            "name": "Wealthsimple Trade PERSONAL",
            "balance": {"total": {"amount": 1013.40, "currency": "CAD"}},
        },
    ]
    raw_balances = [
        {"account_id": OPTIONS_ID, "currency": {"code": "USD"}, "cash": 19764.02},
        {"account_id": OPTIONS_ID, "currency": {"code": "CAD"}, "cash": 59.32},
        {"account_id": SWING_ID, "currency": {"code": "USD"}, "cash": 711.86},
    ]
    account_map = {
        OPTIONS_ID: "WEALTHSIMPLE OPTIONS",
        SWING_ID: "WEALTHSIMPLE SWING",
    }

    totals = calculate_broker_totals(
        positions=[],
        fx_rate=FX,
        raw_accounts=raw_accounts,
        raw_balances=raw_balances,
        account_map=account_map,
        group_by_account=True,
    )

    assert totals["WEALTHSIMPLE OPTIONS"]["net_value"]["usd"] == round(26547.12 / FX, 2)
    assert totals["WEALTHSIMPLE SWING"]["net_value"]["usd"] == round(1013.40 / FX, 2)
    assert totals["WEALTHSIMPLE OPTIONS"]["net_value"]["usd"] != round(
        19764.02 + (59.32 / FX), 2
    )
