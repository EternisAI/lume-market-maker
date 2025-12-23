"""Main client for Lume Market Maker."""
from typing import AsyncIterator, Optional

from lume_market_maker.constants import (
    CTF_EXCHANGE_ADDRESS,
    DEFAULT_API_URL,
    DEFAULT_CHAIN_ID,
    DEFAULT_FEE_RATE_BPS,
    NEGRISK_EXCHANGE_ADDRESS,
    SIGNATURE_TYPE_POLY_GNOSIS_SAFE,
)
from lume_market_maker.graphql import GraphQLClient, GraphQLError
from lume_market_maker.order_builder import OrderBuilder
from lume_market_maker.subscriptions import (
    OrderUpdate,
    PositionUpdate,
    SubscriptionManager,
)
from lume_market_maker.websocket import GraphQLWebSocketClient
from lume_market_maker.types import (
    Event,
    Market,
    Order,
    OrderArgs,
    OrderBook,
    OrderBookLevel,
    OrderSide,
    OrderType,
    Outcome,
    SignedOrder,
)


class LumeClient:
    """Client for interacting with Lume prediction markets."""

    def __init__(
        self,
        private_key: str,
        api_url: str = DEFAULT_API_URL,
        chain_id: int = DEFAULT_CHAIN_ID,
        fee_rate_bps: int = DEFAULT_FEE_RATE_BPS,
        proxy_wallet: Optional[str] = None,
        signature_type: int = SIGNATURE_TYPE_POLY_GNOSIS_SAFE,
    ):
        """
        Initialize Lume client.

        Args:
            private_key: Private key for signing orders (hex string with or without 0x prefix)
            api_url: GraphQL API endpoint URL (default: dev server)
            chain_id: Chain ID for the network (default: Base Sepolia)
            fee_rate_bps: Fee rate in basis points
            proxy_wallet: Optional proxy wallet address (if None, will be fetched from API)
            signature_type: Signature type (0=EOA, 1=POLY_PROXY, 2=POLY_GNOSIS_SAFE)
        """
        self.api_url = api_url
        self.chain_id = chain_id
        self.fee_rate_bps = fee_rate_bps
        self.signature_type = signature_type

        # Initialize GraphQL client
        self.graphql = GraphQLClient(api_url)

        # Initialize order builder
        self.order_builder = OrderBuilder(
            private_key=private_key,
            chain_id=chain_id,
            fee_rate_bps=fee_rate_bps,
            signature_type=signature_type,
        )

        # Store EOA address
        self.eoa_address = self.order_builder.eoa_address

        # Get or set proxy wallet
        self._proxy_wallet = proxy_wallet
        if self._proxy_wallet is None:
            self._proxy_wallet = self._fetch_proxy_wallet()

        # WebSocket URL derived from API URL
        self.ws_url = self._derive_ws_url(api_url)

        # Lazy-initialized WebSocket client and subscription manager
        self._ws_client: Optional[GraphQLWebSocketClient] = None
        self._subscription_manager: Optional[SubscriptionManager] = None

    def _derive_ws_url(self, api_url: str) -> str:
        """Derive WebSocket URL from HTTP API URL."""
        ws_url = api_url.replace("https://", "wss://").replace("http://", "ws://")
        # Ensure path ends with /query for subscriptions
        if not ws_url.endswith("/query"):
            if ws_url.endswith("/"):
                ws_url = ws_url + "query"
            else:
                ws_url = ws_url + "/query"
        return ws_url

    @property
    def proxy_wallet(self) -> str:
        """Get proxy wallet address."""
        return self._proxy_wallet

    def _fetch_proxy_wallet(self) -> str:
        """
        Fetch proxy wallet address from API.

        Returns:
            Proxy wallet address

        Raises:
            GraphQLError: If the query fails
        """
        query = """
        query($address: String!) {
            user(address: $address) {
                proxyWalletAddress
            }
        }
        """
        variables = {"address": self.eoa_address}

        try:
            data = self.graphql.query(query, variables)
            proxy = data["user"]["proxyWalletAddress"]
            return proxy
        except (KeyError, TypeError) as e:
            raise GraphQLError(
                f"Failed to parse proxy wallet from response: {e}"
            ) from e

    def get_market(self, market_id: str) -> Market:
        """
        Get market information.

        Args:
            market_id: Market UUID

        Returns:
            Market data

        Raises:
            GraphQLError: If the query fails
        """
        query = """
        query($id: ID!) {
            market(id: $id) {
                id
                outcomes {
                    id
                    label
                    tokenId
                }
                event {
                    isNegRisk
                }
            }
        }
        """
        variables = {"id": market_id}

        try:
            data = self.graphql.query(query, variables)
            market_data = data["market"]

            outcomes = [
                Outcome(
                    id=o["id"],
                    label=o["label"],
                    token_id=o["tokenId"],
                )
                for o in market_data["outcomes"]
                if o.get("id")
            ]

            # Extract isNegRisk from event
            is_neg_risk = None
            if (
                market_data.get("event")
                and market_data["event"].get("isNegRisk") is not None
            ):
                is_neg_risk = market_data["event"]["isNegRisk"]

            return Market(
                id=market_data["id"],
                outcomes=outcomes,
                is_neg_risk=is_neg_risk,
            )
        except (KeyError, TypeError) as e:
            raise GraphQLError(f"Failed to parse market data from response: {e}") from e

    def place_order(
        self,
        market_id: str,
        signed_order: SignedOrder,
        order_args: OrderArgs,
        outcome: Outcome,
        order_type: OrderType = OrderType.LIMIT,
    ) -> dict:
        """
        Place an order on the exchange.

        Args:
            market_id: Market UUID
            signed_order: Signed order data
            order_args: Order arguments (for metadata)
            outcome: Resolved outcome object
            order_type: Order type (LIMIT)

        Returns:
            Order response data

        Raises:
            GraphQLError: If the mutation fails
        """
        mutation = """
        mutation($input: PlaceOrderInput!) {
            placeOrder(input: $input) {
                id
            }
        }
        """

        shares_amount = (
            signed_order.taker_amount
            if order_args.side == OrderSide.BUY
            else signed_order.maker_amount
        )

        variables = {
            "input": {
                "marketId": market_id,
                "outcomeId": outcome.id,
                "side": order_args.side.value,
                "orderType": order_type.value,
                "shares": shares_amount,
                "eoaWallet": self.eoa_address,
                "orderData": signed_order.to_dict(),
            }
        }

        try:
            data = self.graphql.mutate(mutation, variables)
            return data["placeOrder"]
        except (KeyError, TypeError) as e:
            raise GraphQLError(f"Failed to parse order response: {e}") from e

    def _resolve_outcome(
        self, market_id: str, outcome_label: str, market: Optional[Market] = None
    ) -> Outcome:
        """
        Resolve outcome label to outcome object.

        Args:
            market_id: Market UUID
            outcome_label: Outcome label (e.g., "YES", "NO")
            market: Optional market object (if already fetched)

        Returns:
            Outcome object

        Raises:
            ValueError: If outcome not found
        """
        if market is None:
            market = self.get_market(market_id)
        outcome_label_upper = outcome_label.upper()

        for outcome in market.outcomes:
            if outcome.label.upper() == outcome_label_upper:
                return outcome

        # If not found, raise error with available outcomes
        available = ", ".join([o.label for o in market.outcomes])
        raise ValueError(
            f"Outcome '{outcome_label}' not found. Available outcomes: {available}"
        )

    def create_and_place_order(
        self,
        order_args: OrderArgs,
        order_type: OrderType = OrderType.LIMIT,
        nonce: int = 0,
    ) -> dict:
        """
        Create, sign, and place an order in one step.

        Args:
            order_args: Order arguments (market_id, side, outcome label, price, size, expiration)
            order_type: Order type (LIMIT)
            nonce: Order nonce

        Returns:
            Order response data

        Raises:
            GraphQLError: If the operation fails
            ValueError: If outcome not found
        """
        # Get market information including isNegRisk and outcomes
        market = self.get_market(order_args.market_id)

        # Resolve outcome from label (pass market to avoid duplicate fetch)
        outcome = self._resolve_outcome(
            order_args.market_id, order_args.outcome, market
        )

        # Determine exchange address based on isNegRisk (default to CTF)
        exchange_address = (
            NEGRISK_EXCHANGE_ADDRESS if market.is_neg_risk else CTF_EXCHANGE_ADDRESS
        )

        # Build and sign order
        signed_order = self.order_builder.build_and_sign_order(
            proxy_wallet=self.proxy_wallet,
            order_args=order_args,
            outcome_id=outcome.id,
            token_id=outcome.token_id,
            exchange_address=exchange_address,
            nonce=nonce,
        )

        return self.place_order(
            order_args.market_id, signed_order, order_args, outcome, order_type
        )

    def get_order(self, order_id: str) -> Order:
        """
        Get order by ID.

        Args:
            order_id: Order UUID

        Returns:
            Order data

        Raises:
            GraphQLError: If the query fails
        """
        query = """
        query($id: ID!) {
            order(id: $id) {
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
                feeAmount
                eoaWallet
                createdAt
                updatedAt
                expiresAt
            }
        }
        """
        variables = {"id": order_id}

        try:
            data = self.graphql.query(query, variables)
            order_data = data["order"]

            return Order(
                id=order_data["id"],
                market_id=order_data["marketId"],
                outcome_id=order_data["outcomeId"],
                user_id=order_data["userId"],
                side=order_data["side"],
                type=order_data["type"],
                status=order_data["status"],
                time_in_force=order_data["timeInForce"],
                price=order_data["price"],
                shares=order_data["shares"],
                filled_shares=order_data["filledShares"],
                collateral_locked=order_data["collateralLocked"],
                fee_amount=order_data["feeAmount"],
                eoa_wallet=order_data["eoaWallet"],
                created_at=order_data["createdAt"],
                updated_at=order_data["updatedAt"],
                expires_at=order_data["expiresAt"],
            )
        except (KeyError, TypeError) as e:
            raise GraphQLError(f"Failed to parse order data from response: {e}") from e

    def list_user_orders_for_market(
        self,
        address: str,
        market_id: str,
        status: str = "OPEN",
        first: int = 100,
    ) -> list[Order]:
        """
        List a user's orders for a given market.

        This is primarily intended for bots to detect whether they already have
        open orders on a market.

        Args:
            address: EOA address (checks `user(address: ...)`)
            market_id: Market UUID
            status: Order status filter (e.g. OPEN, PARTIALLY_FILLED, FILLED)
            first: Page size

        Returns:
            List of Order objects (may be empty)

        Raises:
            GraphQLError: If the query fails or response can't be parsed
        """
        query = """
        query($address: String!, $marketId: ID!, $status: OrderStatus, $first: Int) {
            user(address: $address) {
                orders(marketId: $marketId, status: $status, first: $first) {
                    orders {
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
                }
            }
        }
        """
        variables = {
            "address": address,
            "marketId": market_id,
            "status": status,
            "first": first,
        }

        try:
            data = self.graphql.query(query, variables)
            orders_data = (
                data.get("user", {})
                .get("orders", {})
                .get("orders", [])
                or []
            )

            orders: list[Order] = []
            for order_data in orders_data:
                if not order_data or not order_data.get("id"):
                    continue
                orders.append(
                    Order(
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
                        fee_amount=order_data.get("feeAmount", ""),
                        eoa_wallet=order_data.get("eoaWallet", ""),
                        created_at=order_data.get("createdAt", ""),
                        updated_at=order_data.get("updatedAt", ""),
                        expires_at=order_data.get("expiresAt", ""),
                    )
                )

            return orders
        except (AttributeError, KeyError, TypeError) as e:
            raise GraphQLError(f"Failed to parse user orders from response: {e}") from e

    def get_orderbook(self, market_id: str, outcome: str) -> OrderBook:
        """
        Get order book for a market outcome.

        Args:
            market_id: Market UUID
            outcome: Outcome label (e.g., "YES", "NO")

        Returns:
            Order book data

        Raises:
            GraphQLError: If the query fails
            ValueError: If outcome not found
        """
        # Resolve outcome from label
        resolved_outcome = self._resolve_outcome(market_id, outcome)

        query = """
        query($marketId: ID!, $outcomeId: ID!) {
            orderBook(marketId: $marketId, outcomeId: $outcomeId) {
                outcome {
                    id
                    label
                    tokenId
                }
                bids {
                    price
                    shares
                }
                asks {
                    price
                    shares
                }
            }
        }
        """
        variables = {"marketId": market_id, "outcomeId": resolved_outcome.id}

        try:
            data = self.graphql.query(query, variables)
            orderbook_data = data["orderBook"]

            outcome_data = Outcome(
                id=orderbook_data["outcome"]["id"],
                label=orderbook_data["outcome"]["label"],
                token_id=orderbook_data["outcome"]["tokenId"],
            )

            bids = [
                OrderBookLevel(price=b["price"], shares=b["shares"])
                for b in orderbook_data["bids"]
            ]

            asks = [
                OrderBookLevel(price=a["price"], shares=a["shares"])
                for a in orderbook_data["asks"]
            ]

            return OrderBook(outcome=outcome_data, bids=bids, asks=asks)
        except (KeyError, TypeError) as e:
            raise GraphQLError(
                f"Failed to parse orderbook data from response: {e}"
            ) from e

    def cancel_order(self, order_id: str) -> dict:
        """
        Cancel an order.

        Args:
            order_id: Order UUID

        Returns:
            Cancellation response data

        Raises:
            GraphQLError: If the mutation fails
        """
        mutation = """
        mutation($input: CancelOrderInput!) {
            cancelOrder(input: $input) {
                id
                status
            }
        }
        """
        variables = {
            "input": {
                "orderId": order_id,
            }
        }

        try:
            data = self.graphql.mutate(mutation, variables)
            return data["cancelOrder"]
        except (KeyError, TypeError) as e:
            raise GraphQLError(f"Failed to parse cancel order response: {e}") from e

    def get_all_events(
        self,
        first: Optional[int] = None,
        after: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[list[str]] = None,
        status: Optional[str] = None,
    ) -> list[Event]:
        """
        Get all events from the API.

        Args:
            first: Maximum number of events to return (None for all)
            after: Pagination cursor (event ID to start after)
            category: Filter by category
            tags: Filter by tags
            status: Filter by status (ACTIVE, RESOLVED, CANCELLED)

        Returns:
            List of Event objects

        Raises:
            GraphQLError: If the query fails
        """
        query = """
        query($first: Int, $after: ID, $category: String, $tags: [String!], $status: EventStatus) {
            events(first: $first, after: $after, category: $category, tags: $tags, status: $status) {
                events {
                    id
                    slug
                    title
                    resolutionCriteria
                    startDate
                    endDate
                    createdAt
                    imageUrl
                    status
                    volume
                    liquidity
                    openInterest
                    category
                    tags
                    isNegRisk
                    markets {
                        id
                        slug
                        question
                        outcomes {
                            id
                            label
                            tokenId
                        }
                    }
                }
            }
        }
        """
        variables = {
            "first": first,
            "after": after,
            "category": category,
            "tags": tags,
            "status": status,
        }

        try:
            data = self.graphql.query(query, variables)
            events_data = data.get("events", {}).get("events", [])

            events = []
            for e in events_data:
                markets = []
                for m in e.get("markets", []):
                    outcomes = [
                        Outcome(
                            id=o["id"],
                            label=o["label"],
                            token_id=o["tokenId"],
                        )
                        for o in m.get("outcomes", [])
                        if o.get("id")
                    ]
                    markets.append(
                        Market(
                            id=m["id"],
                            outcomes=outcomes,
                            slug=m.get("slug"),
                            question=m.get("question"),
                        )
                    )

                events.append(
                    Event(
                        id=e["id"],
                        slug=e["slug"],
                        title=e["title"],
                        status=e["status"],
                        category=e["category"],
                        tags=e.get("tags", []),
                        markets=markets,
                        resolution_criteria=e.get("resolutionCriteria"),
                        start_date=e.get("startDate"),
                        end_date=e.get("endDate"),
                        created_at=e.get("createdAt"),
                        image_url=e.get("imageUrl"),
                        volume=e.get("volume"),
                        liquidity=e.get("liquidity"),
                        open_interest=e.get("openInterest"),
                        is_neg_risk=e.get("isNegRisk"),
                    )
                )

            return events
        except (KeyError, TypeError) as e:
            raise GraphQLError(f"Failed to parse events data from response: {e}") from e

    def get_all_markets(
        self,
        event_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[Market]:
        """
        Get all markets from the API.

        Args:
            event_id: Filter by event ID (None for all markets)
            status: Filter by status (ACTIVE, RESOLVED, CANCELLED)

        Returns:
            List of Market objects

        Raises:
            GraphQLError: If the query fails
        """
        query = """
        query($eventId: ID, $status: MarketStatus) {
            markets(eventId: $eventId, status: $status) {
                id
                slug
                question
                outcomes {
                    id
                    label
                    tokenId
                }
            }
        }
        """
        variables = {
            "eventId": event_id,
            "status": status,
        }

        try:
            data = self.graphql.query(query, variables)
            markets_data = data.get("markets", [])

            markets = []
            for m in markets_data:
                outcomes = [
                    Outcome(
                        id=o["id"],
                        label=o["label"],
                        token_id=o["tokenId"],
                    )
                    for o in m.get("outcomes", [])
                    if o.get("id")
                ]

                markets.append(
                    Market(
                        id=m["id"],
                        outcomes=outcomes,
                        slug=m.get("slug"),
                        question=m.get("question"),
                    )
                )

            return markets
        except (KeyError, TypeError) as e:
            raise GraphQLError(
                f"Failed to parse markets data from response: {e}"
            ) from e

    # ==================== Subscription Methods ====================

    async def connect_websocket(self) -> None:
        """
        Connect to WebSocket for real-time subscriptions.

        This establishes a WebSocket connection using wallet-based authentication.
        Must be called before using subscription methods.

        Raises:
            WebSocketError: If connection fails
        """
        if self._ws_client is None:
            self._ws_client = GraphQLWebSocketClient(
                ws_url=self.ws_url,
                account=self.order_builder.account,
                chain_id=self.chain_id,
                graphql_client=self.graphql,
            )

        if not self._ws_client.connected:
            await self._ws_client.connect()
            self._subscription_manager = SubscriptionManager(self._ws_client)

    async def close_websocket(self) -> None:
        """
        Close WebSocket connection.

        Call this when done with subscriptions to clean up resources.
        """
        if self._ws_client is not None:
            await self._ws_client.close()
            self._ws_client = None
            self._subscription_manager = None

    @property
    def subscriptions(self) -> SubscriptionManager:
        """
        Get subscription manager for direct subscription access.

        Returns:
            SubscriptionManager instance

        Raises:
            RuntimeError: If WebSocket not connected
        """
        if self._subscription_manager is None:
            raise RuntimeError(
                "WebSocket not connected. Call connect_websocket() first."
            )
        return self._subscription_manager

    async def subscribe_to_order_updates(self) -> AsyncIterator[OrderUpdate]:
        """
        Subscribe to authenticated user's order updates.

        Automatically connects to WebSocket if not already connected.

        Yields:
            OrderUpdate objects for each order change

        Example:
            async for update in client.subscribe_to_order_updates():
                print(f"[{update.type}] Order {update.order.id}: {update.order.status}")
        """
        await self.connect_websocket()
        async for update in self.subscriptions.my_order_updates():
            yield update

    async def subscribe_to_position_updates(self) -> AsyncIterator[PositionUpdate]:
        """
        Subscribe to authenticated user's position updates.

        Automatically connects to WebSocket if not already connected.

        Yields:
            PositionUpdate objects for each position change

        Example:
            async for update in client.subscribe_to_position_updates():
                print(f"[{update.type}] Position {update.position.id}: {update.position.shares} shares")
        """
        await self.connect_websocket()
        async for update in self.subscriptions.my_position_updates():
            yield update
