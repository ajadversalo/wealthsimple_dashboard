from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_cash_secured_put_screener_returns_ranked_candidates():
    candidates = [
        {
            "rank": 1,
            "symbol": "BAC",
            "score": 82.4,
            "earnings_date": "2026-08-27",
            "earnings_days": 27,
        }
    ]

    with patch("app.api.routes.screen_cash_secured_puts", return_value=candidates):
        response = TestClient(app).get("/api/v1/screener/cash-secured-puts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_count"] == 1
    assert payload["candidates"] == candidates
    assert "updated_at" in payload
