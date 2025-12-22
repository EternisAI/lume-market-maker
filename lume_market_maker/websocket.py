"""WebSocket client for GraphQL subscriptions with wallet-based authentication."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import websockets
from eth_account.signers.local import LocalAccount

from lume_market_maker.graphql import GraphQLClient, GraphQLError


@dataclass
class WalletAuthDomain:
    """EIP-712 domain for wallet authentication."""

    name: str
    version: str
    chain_id: int


@dataclass
class WalletAuthChallenge:
    """Challenge response from server."""

    nonce: str
    expires_at: str
    domain: WalletAuthDomain


class WebSocketError(Exception):
    """WebSocket-related error."""

    pass


class GraphQLWebSocketClient:
    """
    WebSocket client for GraphQL subscriptions with wallet-based authentication.

    Uses the graphql-ws protocol (graphql-transport-ws) for subscriptions.
    Authenticates using EIP-712 signed messages with server-provided nonces.
    """

    # graphql-ws protocol message types
    GQL_CONNECTION_INIT = "connection_init"
    GQL_CONNECTION_ACK = "connection_ack"
    GQL_PING = "ping"
    GQL_PONG = "pong"
    GQL_SUBSCRIBE = "subscribe"
    GQL_NEXT = "next"
    GQL_ERROR = "error"
    GQL_COMPLETE = "complete"

    def __init__(
        self,
        ws_url: str,
        account: LocalAccount,
        chain_id: int,
        graphql_client: GraphQLClient,
        connection_timeout: float = 30.0,
        ping_interval: float = 30.0,
    ):
        """
        Initialize WebSocket client.

        Args:
            ws_url: WebSocket URL (wss://...)
            account: Ethereum account for signing
            chain_id: Chain ID for EIP-712 domain
            graphql_client: HTTP GraphQL client for fetching challenges
            connection_timeout: Timeout for connection handshake
            ping_interval: Interval for ping/pong keepalive
        """
        self.ws_url = ws_url
        self.account = account
        self.chain_id = chain_id
        self.graphql_client = graphql_client
        self.connection_timeout = connection_timeout
        self.ping_interval = ping_interval

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._subscriptions: dict[str, asyncio.Queue] = {}
        self._receive_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """
        Connect to WebSocket with wallet authentication.

        1. Requests challenge via HTTP
        2. Signs challenge with EIP-712
        3. Connects WebSocket with walletAuth in init payload
        4. Waits for connection_ack
        """
        if self._connected:
            return

        # Step 1: Request challenge
        challenge = await self._request_challenge()

        # Step 2: Sign challenge
        signature, timestamp = self._sign_challenge(challenge)

        # Step 3: Connect WebSocket
        self._ws = await websockets.connect(
            self.ws_url,
            subprotocols=["graphql-transport-ws"],
        )

        # Step 4: Send connection_init with wallet auth
        init_payload = {
            "type": self.GQL_CONNECTION_INIT,
            "payload": {
                "walletAuth": {
                    "walletAddress": self.account.address,
                    "nonce": challenge.nonce,
                    "timestamp": timestamp,
                    "signature": signature,
                }
            },
        }
        await self._ws.send(json.dumps(init_payload))

        # Step 5: Wait for connection_ack
        try:
            response = await asyncio.wait_for(
                self._ws.recv(), timeout=self.connection_timeout
            )
            msg = json.loads(response)

            if msg.get("type") == self.GQL_CONNECTION_ACK:
                self._connected = True
            else:
                raise WebSocketError(
                    f"Expected connection_ack, got: {msg.get('type')}"
                )
        except asyncio.TimeoutError:
            await self._ws.close()
            raise WebSocketError("Connection timeout waiting for connection_ack")

        # Start background tasks
        self._receive_task = asyncio.create_task(self._receive_loop())
        self._ping_task = asyncio.create_task(self._ping_loop())

    async def _request_challenge(self) -> WalletAuthChallenge:
        """Request authentication challenge from server via HTTP."""
        mutation = """
        mutation($walletAddress: String!) {
            requestWalletAuthChallenge(walletAddress: $walletAddress) {
                nonce
                expiresAt
                domain {
                    name
                    version
                    chainId
                }
            }
        }
        """
        variables = {"walletAddress": self.account.address}

        try:
            data = self.graphql_client.mutate(mutation, variables)
            challenge_data = data["requestWalletAuthChallenge"]

            domain = WalletAuthDomain(
                name=challenge_data["domain"]["name"],
                version=challenge_data["domain"]["version"],
                chain_id=challenge_data["domain"]["chainId"],
            )

            return WalletAuthChallenge(
                nonce=challenge_data["nonce"],
                expires_at=challenge_data["expiresAt"],
                domain=domain,
            )
        except (KeyError, TypeError) as e:
            raise WebSocketError(f"Failed to parse challenge response: {e}") from e

    def _sign_challenge(self, challenge: WalletAuthChallenge) -> tuple[str, int]:
        """
        Sign authentication challenge using EIP-712.

        Args:
            challenge: Challenge from server

        Returns:
            Tuple of (signature hex string, timestamp)
        """
        timestamp = int(time.time())

        # Build EIP-712 typed data (no verifyingContract)
        structured_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ],
                "AuthMessage": [
                    {"name": "nonce", "type": "string"},
                    {"name": "wallet", "type": "address"},
                    {"name": "timestamp", "type": "uint256"},
                ],
            },
            "primaryType": "AuthMessage",
            "domain": {
                "name": challenge.domain.name,
                "version": challenge.domain.version,
                "chainId": challenge.domain.chain_id,
            },
            "message": {
                "nonce": challenge.nonce,
                "wallet": self.account.address,
                "timestamp": timestamp,
            },
        }

        signed_message = self.account.sign_typed_data(full_message=structured_data)
        signature = f"0x{signed_message.signature.hex()}"

        return signature, timestamp

    async def _receive_loop(self) -> None:
        """Background task to receive and dispatch messages."""
        try:
            async for message in self._ws:
                msg = json.loads(message)
                msg_type = msg.get("type")

                if msg_type == self.GQL_NEXT:
                    sub_id = msg.get("id")
                    if sub_id in self._subscriptions:
                        await self._subscriptions[sub_id].put(msg.get("payload", {}))

                elif msg_type == self.GQL_ERROR:
                    sub_id = msg.get("id")
                    if sub_id in self._subscriptions:
                        errors = msg.get("payload", [])
                        error_msg = (
                            errors[0].get("message", "Unknown error")
                            if errors
                            else "Unknown error"
                        )
                        await self._subscriptions[sub_id].put(
                            GraphQLError(f"Subscription error: {error_msg}")
                        )

                elif msg_type == self.GQL_COMPLETE:
                    sub_id = msg.get("id")
                    if sub_id in self._subscriptions:
                        await self._subscriptions[sub_id].put(None)  # Signal completion

                elif msg_type == self.GQL_PING:
                    await self._ws.send(json.dumps({"type": self.GQL_PONG}))

        except websockets.exceptions.ConnectionClosed:
            self._connected = False

    async def _ping_loop(self) -> None:
        """Background task to send periodic pings."""
        try:
            while self._connected:
                await asyncio.sleep(self.ping_interval)
                if self._ws and self._connected:
                    await self._ws.send(json.dumps({"type": self.GQL_PING}))
        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            pass

    async def subscribe(
        self, query: str, variables: Optional[dict[str, Any]] = None
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Subscribe to a GraphQL subscription.

        Args:
            query: GraphQL subscription query
            variables: Query variables

        Yields:
            Subscription data payloads

        Raises:
            WebSocketError: If not connected
            GraphQLError: If subscription errors
        """
        if not self._connected or not self._ws:
            raise WebSocketError("Not connected. Call connect() first.")

        sub_id = str(uuid.uuid4())
        queue: asyncio.Queue = asyncio.Queue()
        self._subscriptions[sub_id] = queue

        # Send subscribe message
        subscribe_msg = {
            "id": sub_id,
            "type": self.GQL_SUBSCRIBE,
            "payload": {
                "query": query,
                "variables": variables or {},
            },
        }
        await self._ws.send(json.dumps(subscribe_msg))

        try:
            while True:
                item = await queue.get()

                if item is None:
                    # Subscription completed
                    break
                elif isinstance(item, Exception):
                    raise item
                else:
                    yield item
        finally:
            # Cleanup subscription
            del self._subscriptions[sub_id]

            # Send complete message
            if self._connected and self._ws:
                complete_msg = {"id": sub_id, "type": self.GQL_COMPLETE}
                try:
                    await self._ws.send(json.dumps(complete_msg))
                except websockets.exceptions.ConnectionClosed:
                    pass

    async def close(self) -> None:
        """Close WebSocket connection."""
        self._connected = False

        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.close()
            self._ws = None

    @property
    def connected(self) -> bool:
        """Check if connected."""
        return self._connected
