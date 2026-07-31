"""Cash-secured-put screening logic adapted from options_screener/v2.py."""

from datetime import datetime
import logging
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

WATCHLIST = [
    "TMUS", "T", "VZ", "WEC", "AEE", "DUK", "SO", "EXC", "JPM", "BAC",
    "WFC", "PNC", "USB", "GS", "MS", "AXP", "SCHW", "COF", "RY", "TD",
    "BNS", "CM", "SOFI", "XLF", "ABBV", "JNJ", "MRK", "GILD", "PFE", "BMY",
    "XLV", "KO", "PEP", "PG", "COST", "WMT", "KR", "GIS", "HSY", "KHC", "CPB",
    "XLP", "HD", "LOW", "BBY", "TGT", "AAPL", "MSFT", "GOOGL", "AMZN", "ORCL",
    "CSCO", "IBM", "QCOM", "NFLX", "AMD", "SHOP", "CAT", "GE", "HON", "UPS", "FDX",
    "XLI", "XOM", "CVX", "COP", "EOG", "FANG", "ENB", "SU", "CNQ", "O", "VICI",
    "SPG", "NNN", "WPC", "SPY", "QQQ",
]

MIN_DTE, MAX_DTE = 14, 21
MIN_OTM, MAX_PRICE = 5.0, 100.0
MIN_OPEN_INTEREST, MIN_AVG_VOLUME = 100, 1_000_000
EARNINGS_BLACKOUT_DAYS = 21
QUALITY_WEIGHT, OPTION_WEIGHT = 0.70, 0.30


def _number(value: Any, digits: int = 2) -> float | None:
    try:
        return None if pd.isna(value) else round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _indicators(history: pd.DataFrame) -> pd.DataFrame:
    frame = history.copy()
    close = frame["Close"]
    frame["SMA20"] = close.rolling(20).mean()
    frame["SMA50"] = close.rolling(50).mean()
    frame["SMA200"] = close.rolling(200).mean()
    frame["MACD"] = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    frame["MACD_SIGNAL"] = frame["MACD"].ewm(span=9).mean()
    delta = close.diff()
    rs = delta.clip(lower=0).rolling(14).mean() / (-delta.clip(upper=0)).rolling(14).mean()
    frame["RSI"] = 100 - (100 / (1 + rs))
    frame["ROC20"] = close.pct_change(20) * 100
    frame["AVG_VOL20"] = frame["Volume"].rolling(20).mean()
    return frame


def _earnings_details(ticker: yf.Ticker) -> tuple[str | None, int | None]:
    """Return the next earnings date and its distance from today, when available."""
    try:
        calendar = ticker.calendar
        if calendar is None or len(calendar) == 0:
            return None, None

        if isinstance(calendar, pd.DataFrame) and "Earnings Date" in calendar.index:
            value = calendar.loc["Earnings Date"].iloc[0]
        elif isinstance(calendar, dict):
            value = calendar.get("Earnings Date")
        else:
            value = calendar.index[0]

        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        date = pd.Timestamp(value)
        if pd.isna(date):
            return None, None
        return date.date().isoformat(), (date.date() - datetime.now().date()).days
    except Exception:
        return None, None


def _relative_strength(close: pd.Series, spy_close: pd.Series) -> tuple[float, float, float]:
    return tuple((close.iloc[-1] / close.iloc[-period] - spy_close.iloc[-1] / spy_close.iloc[-period]) * 100 for period in (21, 63, 126))


def _score_symbol(symbol: str, spy_close: pd.Series) -> list[dict[str, Any]]:
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="1y", auto_adjust=True)
        if len(history) < 220:
            return []
        history = _indicators(history)
        row, previous = history.iloc[-1], history.iloc[-2]
        price = float(row["Close"])
        if price > MAX_PRICE:
            return []
        earnings_date, earnings_days = _earnings_details(ticker)
        if earnings_days is not None and earnings_days <= EARNINGS_BLACKOUT_DAYS:
            return []

        trend, reasons = 0, []
        for points, condition, reason in (
            (5, price > row["SMA20"], "Above SMA20"), (5, price > row["SMA50"], "Above SMA50"),
            (10, price > row["SMA200"], "Above SMA200"), (5, row["SMA20"] > row["SMA50"], "SMA20>SMA50"),
            (5, row["SMA50"] > row["SMA200"], "SMA50>SMA200"), (5, row["SMA200"] > previous["SMA200"], "Rising SMA200"),
        ):
            if condition:
                trend += points; reasons.append(reason)
        momentum, momentum_reasons = 0, []
        for points, condition, reason in ((5, 50 <= row["RSI"] <= 70, f"RSI {row['RSI']:.1f}"), (5, row["MACD"] > row["MACD_SIGNAL"], "MACD Bullish"), (5, row["ROC20"] > 0, "Positive ROC20"), (5, row["ROC20"] > 5, "Strong Momentum")):
            if condition:
                momentum += points; momentum_reasons.append(reason)
        rs_values = _relative_strength(history["Close"], spy_close)
        strength = sum(5 for value in rs_values if value > 0)
        strength_reasons = [f"Beats SPY {period}" for value, period in zip(rs_values, ("1M", "3M", "6M")) if value > 0]
        info = ticker.info or {}
        fundamentals = sum((3 if info.get("revenueGrowth", 0) > 0 else 0, 3 if info.get("earningsGrowth", 0) > 0 else 0, 4 if info.get("trailingPE", 0) > 0 else 0))
        risk = sum((2 if info.get("marketCap", 0) >= 20_000_000_000 else 0, 2 if (info.get("beta") or 99) < 2 else 0, 2 if (info.get("debtToEquity") or 999) < 150 else 0, 2 if (info.get("freeCashflow") or 0) > 0 else 0, 2 if earnings_days is None or earnings_days > EARNINGS_BLACKOUT_DAYS else 0))
        quality = trend + momentum + strength + fundamentals + risk
        base_reasons = reasons + momentum_reasons + strength_reasons
        candidates = []
        for expiry in ticker.options:
            dte = (datetime.strptime(expiry, "%Y-%m-%d").date() - datetime.now().date()).days
            if not MIN_DTE <= dte <= MAX_DTE:
                continue
            for _, put in ticker.option_chain(expiry).puts.iterrows():
                strike, bid, ask, oi = float(put["strike"]), float(put.get("bid", 0)), float(put.get("ask", 0)), int(put.get("openInterest", 0))
                otm = (price - strike) / price * 100
                if strike >= price or otm < MIN_OTM or bid <= 0 or ask <= 0 or oi < MIN_OPEN_INTEREST:
                    continue
                premium, spread = (bid + ask) / 2, (ask - bid) / ask * 100
                liquidity = (4 if row["AVG_VOL20"] >= MIN_AVG_VOLUME else 0) + (4 if oi >= 500 else 0) + (2 if spread <= 5 else 0)
                yield_pct = premium / strike * 100
                option_score = _clamp(yield_pct * 12, 0, 35) + _clamp(otm * 3, 0, 25) + _clamp(oi / 50, 0, 20) + 20
                score = quality + liquidity
                final = score * QUALITY_WEIGHT + option_score * OPTION_WEIGHT
                candidates.append({"symbol": symbol, "price": _number(price), "expiry": expiry, "dte": dte, "strike": _number(strike), "premium": _number(premium), "yield_pct": _number(yield_pct), "otm_pct": _number(otm), "earnings_date": earnings_date, "earnings_days": earnings_days, "quality": _number(score), "option": _number(option_score), "score": _number(final), "trend": trend, "momentum": momentum, "strength": strength, "fundamentals": fundamentals, "risk": risk, "liquidity": liquidity, "reasons": "; ".join(base_reasons)})
        return candidates
    except Exception:
        logger.exception("CSP screening failed for %s", symbol)
        return []


def screen_cash_secured_puts() -> list[dict[str, Any]]:
    """Return the highest-scoring eligible CSP per watchlist symbol."""
    spy = yf.download("SPY", period="1y", progress=False, auto_adjust=True)["Close"]
    if isinstance(spy, pd.DataFrame):
        spy = spy.iloc[:, 0]
    candidates = [candidate for symbol in WATCHLIST for candidate in _score_symbol(symbol, spy.squeeze())]
    best_by_symbol: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if candidate["symbol"] not in best_by_symbol or candidate["score"] > best_by_symbol[candidate["symbol"]]["score"]:
            best_by_symbol[candidate["symbol"]] = candidate
    ranked = sorted(best_by_symbol.values(), key=lambda candidate: candidate["score"], reverse=True)
    for rank, candidate in enumerate(ranked, start=1):
        candidate["rank"] = rank
    return ranked
