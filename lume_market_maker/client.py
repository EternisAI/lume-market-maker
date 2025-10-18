"""Main client for Lume Market Maker."""

from decimal import Decimal
from typing import Optional

from lume_market_maker.constants import (
    DEFAULT_API_URL,
    DEFAULT_CHAIN_ID,
    DEFAULT_EXCHANGE_ADDRESS,
    DEFAULT_FEE_RATE_BPS,
)
from lume_market_maker.graphql import GraphQLClient, GraphQLError
from lume_market_maker.order_builder import OrderBuilder
from lume_market_maker.types import Market, Order, OrderArgs, OrderBook, OrderBookLevel, OrderType, Outcome, SignedOrder


class LumeClient:
    """Client for interacting with Lume prediction markets."""

    def __init__(
        self,
        private_key: str,
        api_url: str = DEFAULT_API_URL,
        chain_id: int = DEFAULT_CHAIN_ID,
        exchange_address: str = DEFAULT_EXCHANGE_ADDRESS,
        fee_rate_bps: int = DEFAULT_FEE_RATE_BPS,
        proxy_wallet: Optional[str] = None,
    ):
        """
        Initialize Lume client.

        Args:
            private_key: Private key for signing orders (hex string with or without 0x prefix)
            api_url: GraphQL API endpoint URL (default: dev server)
            chain_id: Chain ID for the network (default: Base Sepolia)
            exchange_address: Exchange contract address
            fee_rate_bps: Fee rate in basis points
            proxy_wallet: Optional proxy wallet address (if None, will be fetched from API)
        """
        self.api_url = api_url
        self.chain_id = chain_id
        self.exchange_address = exchange_address
        self.fee_rate_bps = fee_rate_bps

        # Initialize GraphQL client
        self.graphql = GraphQLClient(api_url)

        # Initialize order builder
        self.order_builder = OrderBuilder(
            private_key=private_key,
            chain_id=chain_id,
            exchange_address=exchange_address,
            fee_rate_bps=fee_rate_bps,
        )

        # Store EOA address
        self.eoa_address = self.order_builder.eoa_address

        # Get or set proxy wallet
        self._proxy_wallet = proxy_wallet
        if self._proxy_wallet is None:
            self._proxy_wallet = self._fetch_proxy_wallet()

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
            raise GraphQLError(f"Failed to parse proxy wallet from response: {e}") from e

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

            return Market(
                id=market_data["id"],
                outcomes=outcomes,
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

        # Convert price and size to decimal format with 1e6 precision
        # User provides: price (0.01-0.99), size (number of shares)
        # API expects: price and shares as decimal strings with 6 decimal places
        price_decimal = Decimal(str(order_args.price)) * Decimal("1000000")
        shares_decimal = Decimal(str(order_args.size)) * Decimal("1000000")

        variables = {
            "input": {
                "marketId": market_id,
                "outcomeId": outcome.id,
                "side": order_args.side.value,
                "orderType": order_type.value,
                "price": str(int(price_decimal)),  # Convert to integer string
                "shares": str(int(shares_decimal)),  # Convert to integer string
                "eoaWallet": self.eoa_address,
                "orderData": signed_order.to_dict(),
            }
        }

        try:
            data = self.graphql.mutate(mutation, variables)
            return data["placeOrder"]
        except (KeyError, TypeError) as e:
            raise GraphQLError(f"Failed to parse order response: {e}") from e

    def _resolve_outcome(self, market_id: str, outcome_label: str) -> Outcome:
        """
        Resolve outcome label to outcome object.

        Args:
            market_id: Market UUID
            outcome_label: Outcome label (e.g., "YES", "NO")

        Returns:
            Outcome object

        Raises:
            ValueError: If outcome not found
        """
        market = self.get_market(market_id)
        outcome_label_upper = outcome_label.upper()

        for outcome in market.outcomes:
            if outcome.label.upper() == outcome_label_upper:
                return outcome

        # If not found, raise error with available outcomes
        available = ", ".join([o.label for o in market.outcomes])
        raise ValueError(f"Outcome '{outcome_label}' not found. Available outcomes: {available}")

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
        # Resolve outcome from label
        outcome = self._resolve_outcome(order_args.market_id, order_args.outcome)

        # Create internal order args with resolved outcome
        from lume_market_maker.order_builder import OrderBuilder

        # Build and sign order
        signed_order = self.order_builder.build_and_sign_order(
            proxy_wallet=self.proxy_wallet,
            order_args=order_args,
            outcome_id=outcome.id,
            token_id=outcome.token_id,
            nonce=nonce,
        )

        return self.place_order(order_args.market_id, signed_order, order_args, outcome, order_type)

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

    def get_orderbook(self, market_id: str, outcome_id: str) -> OrderBook:
        """
        Get order book for a market outcome.

        Args:
            market_id: Market UUID
            outcome_id: Outcome UUID

        Returns:
            Order book data

        Raises:
            GraphQLError: If the query fails
        """
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
        variables = {"marketId": market_id, "outcomeId": outcome_id}

        try:
            data = self.graphql.query(query, variables)
            orderbook_data = data["orderBook"]

            outcome = Outcome(
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

            return OrderBook(outcome=outcome, bids=bids, asks=asks)
        except (KeyError, TypeError) as e:
            raise GraphQLError(f"Failed to parse orderbook data from response: {e}") from e

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
