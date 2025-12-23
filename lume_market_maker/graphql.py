"""GraphQL client for Lume API."""

import json
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests
from eth_account import Account


class GraphQLError(Exception):
    """GraphQL error."""

    pass


@dataclass
class WalletAuthChallenge:
    """Challenge data for wallet authentication."""

    nonce: str
    expires_at: str
    domain_name: str
    domain_version: str
    domain_chain_id: int


class GraphQLClient:
    """Client for making GraphQL requests."""

    def __init__(self, api_url: str, timeout: int = 30):
        """
        Initialize GraphQL client.

        Args:
            api_url: GraphQL API endpoint URL
            timeout: Request timeout in seconds
        """
        self.api_url = api_url
        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        """Get headers for requests. Override in subclasses for auth."""
        return {"Content-Type": "application/json"}

    def query(self, query: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """
        Execute a GraphQL query.

        Args:
            query: GraphQL query string
            variables: Query variables

        Returns:
            Query response data

        Raises:
            GraphQLError: If the query fails
        """
        payload = {"query": query, "variables": variables or {}}

        headers = self._get_headers()

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            # Try to get error details before raising
            if not response.ok:
                error_body = response.text
                raise GraphQLError(f"HTTP {response.status_code}: {error_body}")
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            if isinstance(e, requests.exceptions.HTTPError):
                raise  # Re-raise if we already handled it above
            raise GraphQLError(f"Request failed: {e}") from e

        try:
            result = response.json()
        except json.JSONDecodeError as e:
            raise GraphQLError(f"Failed to parse response: {e}") from e

        if "errors" in result and result["errors"]:
            error_msg = result["errors"][0].get("message", "Unknown error")
            raise GraphQLError(f"GraphQL error: {error_msg}")

        if "data" not in result:
            raise GraphQLError("No data in response")

        return result["data"]

    def mutate(
        self, mutation: str, variables: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """
        Execute a GraphQL mutation.

        Args:
            mutation: GraphQL mutation string
            variables: Mutation variables

        Returns:
            Mutation response data

        Raises:
            GraphQLError: If the mutation fails
        """
        return self.query(mutation, variables)


class AuthenticatedGraphQLClient(GraphQLClient):
    """
    GraphQL client with wallet-based authentication.

    Uses EIP-712 signed challenges to authenticate HTTP requests via headers:
    - X-Wallet-Address: The wallet address
    - X-Wallet-Nonce: Server-provided nonce
    - X-Wallet-Timestamp: Unix timestamp
    - X-Wallet-Signature: EIP-712 signature
    """

    # Header names matching backend expectations
    HEADER_WALLET_ADDRESS = "X-Wallet-Address"
    HEADER_WALLET_NONCE = "X-Wallet-Nonce"
    HEADER_WALLET_TIMESTAMP = "X-Wallet-Timestamp"
    HEADER_WALLET_SIGNATURE = "X-Wallet-Signature"

    def __init__(self, api_url: str, account: Account, timeout: int = 30):
        """
        Initialize authenticated GraphQL client.

        Args:
            api_url: GraphQL API endpoint URL
            account: Ethereum account for signing
            timeout: Request timeout in seconds
        """
        super().__init__(api_url, timeout)
        self.account = account
        self._cached_auth: Optional[dict[str, str]] = None
        self._auth_expires_at: float = 0

    def _request_challenge(self) -> WalletAuthChallenge:
        """Request authentication challenge from server."""
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

        # Use parent's query to avoid auth headers for challenge request
        payload = {"query": mutation, "variables": variables}
        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(
                self.api_url, json=payload, headers=headers, timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()

            if "errors" in result and result["errors"]:
                error_msg = result["errors"][0].get("message", "Unknown error")
                raise GraphQLError(f"Challenge request failed: {error_msg}")

            challenge_data = result["data"]["requestWalletAuthChallenge"]

            return WalletAuthChallenge(
                nonce=challenge_data["nonce"],
                expires_at=challenge_data["expiresAt"],
                domain_name=challenge_data["domain"]["name"],
                domain_version=challenge_data["domain"]["version"],
                domain_chain_id=challenge_data["domain"]["chainId"],
            )
        except (KeyError, TypeError) as e:
            raise GraphQLError(f"Failed to parse challenge response: {e}") from e
        except requests.exceptions.RequestException as e:
            raise GraphQLError(f"Challenge request failed: {e}") from e

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
                "name": challenge.domain_name,
                "version": challenge.domain_version,
                "chainId": challenge.domain_chain_id,
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

    def _get_auth_headers(self) -> dict[str, str]:
        """Get wallet authentication headers, refreshing if needed."""
        # Check if cached auth is still valid (with 30s buffer)
        if self._cached_auth and time.time() < self._auth_expires_at - 30:
            return self._cached_auth

        # Request new challenge and sign it
        challenge = self._request_challenge()
        signature, timestamp = self._sign_challenge(challenge)

        self._cached_auth = {
            self.HEADER_WALLET_ADDRESS: self.account.address,
            self.HEADER_WALLET_NONCE: challenge.nonce,
            self.HEADER_WALLET_TIMESTAMP: str(timestamp),
            self.HEADER_WALLET_SIGNATURE: signature,
        }

        # Parse expires_at and cache expiry time
        # The nonce expires at a certain time, use that minus buffer
        # For now, use a 4-minute window (timestamp tolerance is 5 min)
        self._auth_expires_at = timestamp + 4 * 60

        return self._cached_auth

    def _get_headers(self) -> dict[str, str]:
        """Get headers including wallet auth."""
        headers = {"Content-Type": "application/json"}
        headers.update(self._get_auth_headers())
        return headers

    def clear_auth_cache(self) -> None:
        """Clear cached authentication, forcing re-authentication on next request."""
        self._cached_auth = None
        self._auth_expires_at = 0
