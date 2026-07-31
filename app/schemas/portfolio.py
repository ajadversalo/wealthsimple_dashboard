from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class StrategyType(str, Enum):
    CASH_SECURED_PUT = "CASH_SECURED_PUT"
    COVERED_CALL = "COVERED_CALL"
    LONG_STOCK = "LONG_STOCK"
    LONG_EQUITY = "LONG_EQUITY"


class UnderlyingLeg(BaseModel):
    shares: float
    avg_purchase_price: float = 0.0


class OptionLeg(BaseModel):
    contract_symbol: str
    option_type: str
    strike_price: float
    expiration_date: str
    quantity: float
    avg_price: Optional[float] = None
    moneyness: Optional[str] = None


class PositionItem(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    symbol: str
    broker: str
    asset_class: str
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


class BrokerSummary(BaseModel):
    broker: str
    net_value: CurrencyValue
    option_liabilities: CurrencyValue
    remaining_capital: CurrencyValue
    deployed_capital: CurrencyValue
    total_capital: CurrencyValue


class PortfolioResponse(BaseModel):
    account_id: str
    updated_at: str
    fx_rate_usd_cad: float = 1.0
    total_capital: CurrencyValue
    remaining_capital: CurrencyValue
    broker_totals: Dict[str, BrokerSummary] = Field(default_factory=dict)
    positions: List[PositionItem]
    sectors: Optional[List[SectorSummary]] = Field(default_factory=list)
