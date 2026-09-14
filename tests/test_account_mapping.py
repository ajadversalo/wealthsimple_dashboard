from app.api.routes import build_account_map


def test_generic_wealthsimple_accounts_are_split_by_option_holdings():
    options_id = "9c7fd8bd-598c-431f-af42-fe1c12b0b768"
    swing_id = "92fe0874-cbca-4612-a2cf-3f0d4a3926df"

    account_map = build_account_map(
        [
            {"id": options_id, "brokerage": {"name": "Wealthsimple"}},
            {"id": swing_id, "brokerage": {"name": "Wealthsimple"}},
        ],
        [],
        [{"account_id": options_id}],
    )

    assert account_map[options_id] == "WEALTHSIMPLE OPTIONS"
    assert account_map[swing_id] == "WEALTHSIMPLE SWING"
