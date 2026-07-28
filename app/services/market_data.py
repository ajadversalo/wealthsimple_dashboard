# app/services/market_data.py

import logging
from typing import Dict, List
import yfinance as yf

logger = logging.getLogger(__name__)

def fetch_underlying_prices(tickers: List[str]) -> Dict[str, float]:
    """
    Batch fetches fast market/delayed stock prices for a list of tickers.
    Returns a dictionary mapping ticker symbol -> float price.
    """
    clean_tickers = list({t.strip().upper() for t in tickers if t and t.strip()})
    if not clean_tickers:
        return {}

    ticker_str = " ".join(clean_tickers)
    prices: Dict[str, float] = {}

    try:
        data = yf.Tickers(ticker_str)
        for t in clean_tickers:
            try:
                ticker_obj = data.tickers.get(t)
                if not ticker_obj:
                    continue
                
                # FastInfo is an object, so use getattr or direct attributes
                fast_info = getattr(ticker_obj, "fast_info", None)
                price = None

                if fast_info:
                    price = (
                        getattr(fast_info, "last_price", None)
                        or getattr(fast_info, "lastPrice", None)
                        or getattr(fast_info, "previous_close", None)
                        or getattr(fast_info, "regularMarketPreviousClose", None)
                    )

                # Fallback to .info dict only if fast_info fails completely
                if price is None and hasattr(ticker_obj, "info"):
                    info = ticker_obj.info or {}
                    price = info.get("regularMarketPrice") or info.get("currentPrice")
                
                if price and float(price) > 0:
                    prices[t] = float(price)
            except Exception as e:
                logger.warning(f"Could not extract price for {t} via yfinance: {e}")
                
    except Exception as e:
        logger.error(f"Failed batch yfinance fetch for {clean_tickers}: {e}")

    return prices