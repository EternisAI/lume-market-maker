"""
Test fixtures for SDK integration tests.

These tests use REAL cryptographic signatures to verify EIP-712 address recovery
works correctly between the Python SDK and Go server.

Requirements:
- PostgreSQL running on localhost:5432 (use make start-infrastructure in pm-backend)
- pm-backend server running in test mode (use make server-test-mode in pm-backend)
"""

import os

import psycopg
import pytest
from eth_account import Account

# Test configuration
TEST_API_URL = os.environ.get("TEST_API_URL", "http://localhost:8888/query")
TEST_WS_URL = os.environ.get("TEST_WS_URL", "ws://localhost:8888/query")
TEST_DB_URL = os.environ.get(
    "TEST_DB_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)
TEST_CHAIN_ID = int(os.environ.get("TEST_CHAIN_ID", "10143"))

# Deterministic test private key (DO NOT USE IN PRODUCTION)
# This generates the same wallet address for reproducible tests
TEST_PRIVATE_KEY = "0x" + "1" * 64


@pytest.fixture(scope="session")
def test_private_key() -> str:
    """Return the test private key."""
    return TEST_PRIVATE_KEY


@pytest.fixture(scope="session")
def test_account() -> Account:
    """
    Create a test Ethereum account with a deterministic private key.

    This account is used for signing EIP-712 messages.
    The same private key produces the same address for reproducible tests.
    """
    return Account.from_key(TEST_PRIVATE_KEY)


@pytest.fixture(scope="session")
def api_url() -> str:
    """Return the GraphQL API URL."""
    return TEST_API_URL


@pytest.fixture(scope="session")
def ws_url() -> str:
    """Return the WebSocket URL."""
    return TEST_WS_URL


@pytest.fixture(scope="session")
def chain_id() -> int:
    """Return the chain ID for EIP-712 domain."""
    return TEST_CHAIN_ID


@pytest.fixture(scope="session")
def db_connection():
    """
    Create a database connection for test setup/teardown.

    Used to insert test users before running tests that require
    a user to exist in the database.
    """
    try:
        conn = psycopg.connect(TEST_DB_URL)
        yield conn
        conn.close()
    except psycopg.Error as e:
        pytest.skip(f"Database not available: {e}")


@pytest.fixture
def test_user(db_connection, test_account):
    """
    Insert a test user into the database and clean up after test.

    This fixture:
    1. Creates a user with the test account's wallet address
    2. Yields the wallet address for use in tests
    3. Deletes the user after the test completes

    Required for tests that need a user to exist (e.g., WebSocket auth).
    """
    import uuid

    wallet = test_account.address.lower()
    user_id = str(uuid.uuid4())

    cursor = db_connection.cursor()

    # Insert test user - using the actual users table schema
    # external_id is required (non-nullable in Go struct)
    external_id = f"test_{wallet[:10]}"
    cursor.execute(
        """
        INSERT INTO users (id, eoa_wallet_address, role, external_id)
        VALUES (%s, %s, 'USER', %s)
        ON CONFLICT (lower(eoa_wallet_address)) WHERE eoa_wallet_address IS NOT NULL DO NOTHING
        RETURNING id
        """,
        (user_id, wallet, external_id),
    )
    db_connection.commit()

    yield wallet

    # Cleanup
    cursor.execute(
        "DELETE FROM users WHERE LOWER(eoa_wallet_address) = %s",
        (wallet,),
    )
    db_connection.commit()
    cursor.close()


@pytest.fixture
def graphql_client(api_url):
    """Create a GraphQL client for the test API."""
    from lume_market_maker.graphql import GraphQLClient
    return GraphQLClient(api_url)


@pytest.fixture
def websocket_client(ws_url, test_account, chain_id, graphql_client):
    """
    Create a WebSocket client for testing subscriptions.

    Note: The client is NOT connected by default.
    Tests should call `await client.connect()` when ready.
    """
    from lume_market_maker.websocket import GraphQLWebSocketClient

    return GraphQLWebSocketClient(
        ws_url=ws_url,
        account=test_account,
        chain_id=chain_id,
        graphql_client=graphql_client,
    )
