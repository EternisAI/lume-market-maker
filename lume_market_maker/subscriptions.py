"""Subscription manager for real-time order and position updates."""

from dataclasses import dataclass
from typing import AsyncIterator, Optional

from lume_market_maker.websocket import GraphQLWebSocketClient


@dataclass
class OrderData:
    """Order data from subscription."""

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
    eoa_wallet: str
    created_at: str
    updated_at: str
    expires_at: Optional[str] = None


@dataclass
class OrderUpdate:
    """Real-time order update."""

    type: str  # INSERT, UPDATE, DELETE
    order: OrderData
    timestamp: str
    sequence: str


@dataclass
class OutcomeData:
    """Outcome data from subscription."""

    id: str
    label: str
    token_id: Optional[str] = None


@dataclass
class PositionData:
    """Position data from subscription."""

    id: str
    market_id: str
    user_id: str
    outcome: OutcomeData
    shares: str
    average_price: str
    pnl_realized: str
    pnl_unrealized: str
    percent_pnl: str
    initial_value: str
    current_value: str
    created_at: str
    updated_at: str


@dataclass
class PositionUpdate:
    """Real-time position update."""

    type: str  # INSERT, UPDATE, DELETE
    position: PositionData
    timestamp: str
    sequence: str


# GraphQL subscription queries
MY_ORDER_UPDATES_SUBSCRIPTION = """
subscription MyOrderUpdates {
    myOrderUpdates {
        type
        order {
            id
            marketId
            outcomeId
            userId
            side
            type
            status
            timeInForce
            price
            shares
            filledShares
            collateralLocked
            eoaWallet
            createdAt
            updatedAt
            expiresAt
        }
        timestamp
        sequence
    }
}
"""

MY_POSITION_UPDATES_SUBSCRIPTION = """
subscription MyPositionUpdates {
    myPositionUpdates {
        type
        position {
            id
            marketId
            userId
            outcome {
                id
                label
                tokenId
            }
            shares
            averagePrice
            pnlRealized
            pnlUnrealized
            percentPnl
            initialValue
            currentValue
            createdAt
            updatedAt
        }
        timestamp
        sequence
    }
}
"""


class SubscriptionManager:
    """
    Manager for GraphQL subscriptions with typed data models.

    Provides convenient methods for subscribing to order and position updates
    with proper type parsing.
    """

    def __init__(self, ws_client: GraphQLWebSocketClient):
        """
        Initialize subscription manager.

        Args:
            ws_client: Connected WebSocket client
        """
        self.ws_client = ws_client

    async def my_order_updates(self) -> AsyncIterator[OrderUpdate]:
        """
        Subscribe to authenticated user's order updates.

        Yields:
            OrderUpdate objects for each order change

        Raises:
            WebSocketError: If connection issues occur
            GraphQLError: If subscription errors
        """
        async for payload in self.ws_client.subscribe(MY_ORDER_UPDATES_SUBSCRIPTION):
            data = payload.get("data", {}).get("myOrderUpdates", {})
            if not data:
                continue

            order_data = data.get("order", {})
            order = OrderData(
                id=order_data.get("id", ""),
                market_id=order_data.get("marketId", ""),
                outcome_id=order_data.get("outcomeId", ""),
                user_id=order_data.get("userId", ""),
                side=order_data.get("side", ""),
                type=order_data.get("type", ""),
                status=order_data.get("status", ""),
                time_in_force=order_data.get("timeInForce", ""),
                price=order_data.get("price", ""),
                shares=order_data.get("shares", ""),
                filled_shares=order_data.get("filledShares", ""),
                collateral_locked=order_data.get("collateralLocked", ""),
                eoa_wallet=order_data.get("eoaWallet", ""),
                created_at=order_data.get("createdAt", ""),
                updated_at=order_data.get("updatedAt", ""),
                expires_at=order_data.get("expiresAt"),
            )

            yield OrderUpdate(
                type=data.get("type", ""),
                order=order,
                timestamp=data.get("timestamp", ""),
                sequence=data.get("sequence", ""),
            )

    async def my_position_updates(self) -> AsyncIterator[PositionUpdate]:
        """
        Subscribe to authenticated user's position updates.

        Yields:
            PositionUpdate objects for each position change

        Raises:
            WebSocketError: If connection issues occur
            GraphQLError: If subscription errors
        """
        async for payload in self.ws_client.subscribe(MY_POSITION_UPDATES_SUBSCRIPTION):
            data = payload.get("data", {}).get("myPositionUpdates", {})
            if not data:
                continue

            position_data = data.get("position", {})
            outcome_data = position_data.get("outcome", {})

            outcome = OutcomeData(
                id=outcome_data.get("id", ""),
                label=outcome_data.get("label", ""),
                token_id=outcome_data.get("tokenId"),
            )

            position = PositionData(
                id=position_data.get("id", ""),
                market_id=position_data.get("marketId", ""),
                user_id=position_data.get("userId", ""),
                outcome=outcome,
                shares=position_data.get("shares", ""),
                average_price=position_data.get("averagePrice", ""),
                pnl_realized=position_data.get("pnlRealized", ""),
                pnl_unrealized=position_data.get("pnlUnrealized", ""),
                percent_pnl=position_data.get("percentPnl", ""),
                initial_value=position_data.get("initialValue", ""),
                current_value=position_data.get("currentValue", ""),
                created_at=position_data.get("createdAt", ""),
                updated_at=position_data.get("updatedAt", ""),
            )

            yield PositionUpdate(
                type=data.get("type", ""),
                position=position,
                timestamp=data.get("timestamp", ""),
                sequence=data.get("sequence", ""),
            )
