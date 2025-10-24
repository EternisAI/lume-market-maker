"""Type definitions for Lume Market Maker."""

from dataclasses import dataclass
from enum import Enum


class OrderSide(str, Enum):
    """Order side enum."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order type enum."""

    LIMIT = "LIMIT"


@dataclass
class OrderArgs:
    """
    Arguments for creating an order.

    Args:
        market_id: Market UUID
        side: Order side (BUY or SELL)
        outcome: Outcome label (e.g., "YES", "NO", or any custom outcome label)
        price: Price per share in decimal format (0.01 to 0.99)
        size: Number of shares in decimal format (e.g., 10.5 shares)
        expiration: Optional unix timestamp for order expiration (default: None = 0)
    """

    market_id: str
    side: OrderSide
    outcome: str  # Outcome label like "YES", "NO", etc.
    price: float
    size: float
    expiration: int | None = None  # Optional unix timestamp (None = 0)

    def print_order(self) -> None:
        """Print formatted order details."""
        from datetime import datetime

        print(f"\nPlacing {self.side.value} order:")
        print(f"{'Market':<30s}: {self.market_id}")
        print(f"{'Outcome':<30s}: {self.outcome}")
        print(f"{'Price':<30s}: ${self.price}")
        print(f"{'Size':<30s}: {self.size} shares")
        print(f"{'Total':<30s}: ${self.price * self.size:.2f}")

        if self.expiration is not None:
            exp_date = datetime.fromtimestamp(self.expiration).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            print(f"{'Expiration':<30s}: {exp_date} ({self.expiration})")
        else:
            print(f"{'Expiration':<30s}: 0 (no expiration)")


@dataclass
class Outcome:
    """Market outcome data."""

    id: str
    label: str
    token_id: str


@dataclass
class Market:
    """Market data."""

    id: str
    outcomes: list[Outcome]
    slug: str | None = None
    question: str | None = None
    status: str | None = None
    volume: str | None = None
    liquidity: str | None = None
    open_interest: str | None = None


@dataclass
class Event:
    """Event data."""

    id: str
    slug: str
    title: str
    status: str
    category: str
    tags: list[str]
    markets: list[Market]
    resolution_criteria: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    created_at: str | None = None
    image_url: str | None = None
    volume: str | None = None
    liquidity: str | None = None
    open_interest: str | None = None


@dataclass
class SignedOrder:
    """Signed order data."""

    salt: str
    maker: str
    signer: str
    taker: str
    token_id: str
    maker_amount: str
    taker_amount: str
    expiration: str
    nonce: str
    fee_rate_bps: str
    side: int
    signature_type: int
    signature: str

    def to_dict(self) -> dict:
        """Convert to dictionary for GraphQL mutation."""
        return {
            "salt": self.salt,
            "maker": self.maker,
            "signer": self.signer,
            "taker": self.taker,
            "tokenId": self.token_id,
            "makerAmount": self.maker_amount,
            "takerAmount": self.taker_amount,
            "expiration": self.expiration,
            "nonce": self.nonce,
            "feeRateBps": self.fee_rate_bps,
            "side": self.side,  # Keep as int (uint8)
            "signatureType": self.signature_type,  # Keep as int
            "signature": self.signature,
        }


@dataclass
class Order:
    """Order data from API."""

    id: str
    market_id: str
    outcome_id: str
    user_id: str
    side: str
    type: str
    status: str
    time_in_force: str
    price: str
    shares: str
    filled_shares: str
    collateral_locked: str
    fee_amount: str
    eoa_wallet: str
    created_at: str
    updated_at: str
    expires_at: str


@dataclass
class OrderBookLevel:
    """Order book level (price and size)."""

    price: str
    shares: str


@dataclass
class OrderBook:
    """Order book data."""

    outcome: Outcome
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
