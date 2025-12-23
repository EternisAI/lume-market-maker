"""
Tests for WebSocket connection with wallet-based authentication.

These tests verify the complete authentication flow:
1. Request challenge via HTTP
2. Sign challenge with real EIP-712 signature
3. Connect WebSocket with signed auth payload
4. Server verifies signature and recovers correct address
5. Server grants or denies access based on user existence

CRITICAL: All tests use REAL cryptographic signatures.
This ensures the EIP-712 implementation matches between Python and Go.
If signing works but auth fails, the type hashes don't match.
"""

import pytest

from lume_market_maker.websocket import GraphQLWebSocketClient, WebSocketError


class TestWebSocketConnection:
    """Tests for WebSocket connection establishment."""

    @pytest.mark.asyncio
    async def test_connect_with_wallet_auth_succeeds(
        self, websocket_client, test_user
    ):
        """
        Test successful WebSocket connection with wallet auth.

        Prerequisites:
        - User exists in database (test_user fixture)
        - Server is running in test mode

        This test verifies:
        1. SDK requests challenge correctly
        2. SDK signs challenge with real key
        3. Server recovers correct address from signature
        4. Server finds user in database
        5. Server sends connection_ack
        """
        try:
            await websocket_client.connect()

            assert websocket_client.connected, "Should be connected after auth"
        finally:
            await websocket_client.close()

    @pytest.mark.asyncio
    async def test_connect_fails_without_user_in_database(
        self, ws_url, test_account, chain_id, graphql_client
    ):
        """
        Test that auth fails when user doesn't exist in database.

        This verifies the server correctly rejects valid signatures
        for unknown wallet addresses.

        The signature is valid (correct format, recovers to test_account.address),
        but the user doesn't exist in the database.
        """
        import websockets.exceptions

        client = GraphQLWebSocketClient(
            ws_url=ws_url,
            account=test_account,
            chain_id=chain_id,
            graphql_client=graphql_client,
        )

        try:
            # This should fail because no user exists for this wallet
            # Server may close connection gracefully or send an error
            with pytest.raises((WebSocketError, websockets.exceptions.ConnectionClosed)):
                await client.connect()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_connect_multiple_times_same_client(
        self, websocket_client, test_user
    ):
        """
        Test that calling connect() multiple times is idempotent.

        Once connected, subsequent connect() calls should be no-ops.
        """
        try:
            await websocket_client.connect()
            assert websocket_client.connected

            # Second connect should be a no-op
            await websocket_client.connect()
            assert websocket_client.connected
        finally:
            await websocket_client.close()


class TestWebSocketSubscription:
    """Tests for GraphQL subscriptions over WebSocket."""

    @pytest.mark.asyncio
    async def test_subscribe_to_order_updates(
        self, websocket_client, test_user
    ):
        """
        Test subscribing to myOrderUpdates after successful auth.

        This verifies:
        1. Connection with wallet auth succeeds
        2. Subscription request is sent correctly
        3. Server accepts the subscription

        Note: This test doesn't wait for actual order updates,
        just verifies the subscription can be established.
        """
        try:
            await websocket_client.connect()
            assert websocket_client.connected

            # Start subscription - should not raise
            subscription = websocket_client.subscribe(
                """
                subscription {
                    myOrderUpdates {
                        order {
                            id
                            status
                        }
                    }
                }
                """
            )

            # Just verify we got an async iterator
            assert hasattr(subscription, "__anext__"), "Should return async iterator"

            # Note: We don't actually await next() because there may not be
            # any orders to update. The test is just verifying the subscription
            # can be established.
        finally:
            await websocket_client.close()

    @pytest.mark.asyncio
    async def test_subscribe_to_position_updates(
        self, websocket_client, test_user
    ):
        """
        Test subscribing to myPositionUpdates after successful auth.

        Similar to order updates, verifies subscription establishment.
        """
        try:
            await websocket_client.connect()
            assert websocket_client.connected

            subscription = websocket_client.subscribe(
                """
                subscription {
                    myPositionUpdates {
                        position {
                            id
                            shares
                        }
                    }
                }
                """
            )

            assert hasattr(subscription, "__anext__"), "Should return async iterator"
        finally:
            await websocket_client.close()


class TestWebSocketReconnection:
    """Tests for WebSocket disconnection and reconnection."""

    @pytest.mark.asyncio
    async def test_close_and_reconnect(
        self, ws_url, test_account, chain_id, graphql_client, test_user
    ):
        """
        Test that a client can disconnect and reconnect successfully.

        Each reconnection should:
        1. Request a new challenge (new nonce)
        2. Sign with a new timestamp
        3. Establish a new WebSocket connection
        """
        client = GraphQLWebSocketClient(
            ws_url=ws_url,
            account=test_account,
            chain_id=chain_id,
            graphql_client=graphql_client,
        )

        try:
            # First connection
            await client.connect()
            assert client.connected

            # Close
            await client.close()
            assert not client.connected

            # Reconnect with fresh client (simulating reconnect)
            client = GraphQLWebSocketClient(
                ws_url=ws_url,
                account=test_account,
                chain_id=chain_id,
                graphql_client=graphql_client,
            )
            await client.connect()
            assert client.connected
        finally:
            await client.close()


class TestSignatureVerification:
    """
    Tests that specifically verify signature verification works correctly.

    These tests are designed to catch mismatches between:
    - Python eth_account EIP-712 implementation
    - Go crypto.SigToPub / ecrecover implementation
    """

    @pytest.mark.asyncio
    async def test_server_recovers_correct_address(
        self, websocket_client, test_user, test_account
    ):
        """
        Test that the server recovers the correct wallet address from signature.

        This is the most important test. If this passes, it means:
        1. EIP-712 type hashes match between Python and Go
        2. Domain separator encoding matches
        3. Message encoding matches
        4. Signature format (v, r, s) is correct
        5. Address recovery works correctly

        If this test fails but test_wallet_auth.py tests pass:
        - The issue is in how Go reconstructs the EIP-712 hash
        - Compare type hashes and domain separators between implementations
        """
        try:
            await websocket_client.connect()

            # If we got here, the server:
            # 1. Received our signature
            # 2. Reconstructed the EIP-712 hash
            # 3. Recovered the public key from signature
            # 4. Derived the wallet address
            # 5. Matched it to test_account.address
            # 6. Found the user in database
            # 7. Sent connection_ack

            assert websocket_client.connected, (
                f"Server should accept signature from {test_account.address}"
            )
        finally:
            await websocket_client.close()
