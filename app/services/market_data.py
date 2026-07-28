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
                
                # Fast info lookup avoids full ticker metadata download
                fast_info = getattr(ticker_obj, "fast_info", {})
                price = (
                    fast_info.get("lastPrice") 
                    or fast_info.get("regularMarketPreviousClose")
                    or ticker_obj.info.get("regularMarketPrice")
                )
                
                if price and float(price) > 0:
                    prices[t] = float(price)
            except Exception as e:
                logger.warning(f"Could not extract price for {t} via yfinance: {e}")
                
    except Exception as e:
        logger.error(f"Failed batch yfinance fetch for {clean_tickers}: {e}")

    return prices