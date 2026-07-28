# app/schemas/positions.py

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class StrategyType(str, Enum):
    CASH_SECURED_PUT = "CASH_SECURED_PUT"
    COVERED_CALL = "COVERED_CALL"
    LONG_STOCK = "LONG_STOCK"


class UnderlyingLeg(BaseModel):
    shares: float
    avg_purchase_price: float = 0.0


class OptionLeg(BaseModel):
    contract_symbol: str
    option_type: str  # "CALL" or "PUT"
    strike_price: float
    expiration_date: str
    quantity: float
    avg_price: Optional[float] = None
    moneyness: Optional[str] = None  # "ITM" or "OTM"


class PositionItem(BaseModel):
    symbol: str
    strategy: StrategyType
    industry: str
    current_price: Optional[float] = None
    portfolio_pct: float = 0.0
    underlying: Optional[UnderlyingLeg] = None
    option_leg: Optional[OptionLeg] = None


class SectorSummary(BaseModel):
    industry: str
    capital_committed: float
    portfolio_pct: float
    tickers: List[str]


class CurrencyValue(BaseModel):
    usd: float = 0.0
    cad: float = 0.0

class PortfolioResponse(BaseModel):
    account_id: str
    updated_at: str
    fx_rate_usd_cad: float = 1.0        # Included so frontends know the applied rate
    total_capital: CurrencyValue        # Committed capital
    remaining_capital: CurrencyValue    # Cash/liquidity balance
    positions: List[PositionItem]
    sectors: Optional[List[SectorSummary]] = Field(default_factory=list)