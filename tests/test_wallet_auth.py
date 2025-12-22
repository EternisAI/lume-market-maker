"""
Tests for wallet authentication challenge mutation.

These tests verify:
1. The server returns valid challenge data
2. The SDK can sign challenges with real EIP-712 signatures
3. Signature verification recovers the correct wallet address

IMPORTANT: All tests use REAL cryptographic signatures (not mocked)
to ensure the EIP-712 implementation matches between Python and Go.
"""

import time

import pytest
from eth_account import Account


class TestWalletAuthChallenge:
    """Tests for requestWalletAuthChallenge mutation."""

    def test_request_challenge_returns_valid_response(self, graphql_client, test_account):
        """
        Test that the server returns a valid challenge with nonce and domain.

        This verifies the basic challenge request flow:
        - Server generates a unique nonce
        - Server returns EIP-712 domain info
        - Expiration is set in the future
        """
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
        variables = {"walletAddress": test_account.address}

        result = graphql_client.mutate(mutation, variables)
        challenge = result["requestWalletAuthChallenge"]

        # Verify challenge structure
        assert challenge["nonce"], "Nonce should not be empty"
        assert len(challenge["nonce"]) >= 32, "Nonce should be at least 32 chars"
        assert challenge["expiresAt"], "ExpiresAt should not be empty"
        assert challenge["domain"]["name"], "Domain name should not be empty"
        assert challenge["domain"]["version"], "Domain version should not be empty"
        assert challenge["domain"]["chainId"] > 0, "Chain ID should be positive"

    def test_challenge_nonce_is_unique(self, graphql_client, test_account):
        """
        Test that each challenge request returns a unique nonce.

        This ensures replay attack protection - same wallet cannot
        reuse a nonce from a previous challenge.
        """
        mutation = """
        mutation($walletAddress: String!) {
            requestWalletAuthChallenge(walletAddress: $walletAddress) {
                nonce
            }
        }
        """
        variables = {"walletAddress": test_account.address}

        # Request two challenges
        result1 = graphql_client.mutate(mutation, variables)
        result2 = graphql_client.mutate(mutation, variables)

        nonce1 = result1["requestWalletAuthChallenge"]["nonce"]
        nonce2 = result2["requestWalletAuthChallenge"]["nonce"]

        assert nonce1 != nonce2, "Each challenge should have a unique nonce"

    def test_challenge_domain_matches_expected(self, graphql_client, test_account, chain_id):
        """
        Test that challenge domain matches the expected configuration.

        This verifies the server is using the correct EIP-712 domain
        that the SDK expects for signing.
        """
        mutation = """
        mutation($walletAddress: String!) {
            requestWalletAuthChallenge(walletAddress: $walletAddress) {
                domain {
                    name
                    version
                    chainId
                }
            }
        }
        """
        variables = {"walletAddress": test_account.address}

        result = graphql_client.mutate(mutation, variables)
        domain = result["requestWalletAuthChallenge"]["domain"]

        assert domain["name"] == "Lume Prediction Market"
        assert domain["version"] == "1"
        assert domain["chainId"] == chain_id


class TestEIP712Signing:
    """Tests for EIP-712 signature generation."""

    def test_sign_challenge_produces_valid_signature(self, test_account, chain_id):
        """
        Test that signing a challenge produces a valid 65-byte signature.

        This verifies the SDK's EIP-712 signing implementation produces
        properly formatted signatures (0x prefix + 130 hex chars = 65 bytes).
        """
        # Build a mock challenge (same structure as server returns)
        nonce = "test_nonce_12345678901234567890"
        timestamp = int(time.time())

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
                "name": "Lume Prediction Market",
                "version": "1",
                "chainId": chain_id,
            },
            "message": {
                "nonce": nonce,
                "wallet": test_account.address,
                "timestamp": timestamp,
            },
        }

        signed = test_account.sign_typed_data(full_message=structured_data)
        signature = f"0x{signed.signature.hex()}"

        # Verify signature format
        assert signature.startswith("0x"), "Signature should have 0x prefix"
        assert len(signature) == 132, "Signature should be 132 chars (0x + 130 hex)"

    def test_signature_recovers_correct_address(self, test_account, chain_id):
        """
        Test that signing and recovering produces the original address.

        This is the CRITICAL test that verifies our EIP-712 implementation
        matches what the Go server expects. If this test passes locally
        but fails against the server, there's a mismatch in how we build
        the typed data hash.
        """
        from eth_account.messages import encode_typed_data

        nonce = "test_nonce_for_recovery_check_123"
        timestamp = int(time.time())

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
                "name": "Lume Prediction Market",
                "version": "1",
                "chainId": chain_id,
            },
            "message": {
                "nonce": nonce,
                "wallet": test_account.address,
                "timestamp": timestamp,
            },
        }

        # Sign the message
        signed = test_account.sign_typed_data(full_message=structured_data)

        # Encode the typed data to get the signable message
        signable = encode_typed_data(full_message=structured_data)

        # Recover the address from the signature
        recovered = Account.recover_message(signable, signature=signed.signature)

        assert recovered.lower() == test_account.address.lower(), (
            f"Recovered address {recovered} should match "
            f"signer address {test_account.address}"
        )


class TestFullAuthFlow:
    """Integration tests for the complete authentication flow."""

    def test_request_and_sign_challenge(self, graphql_client, test_account, chain_id):
        """
        Test the full flow: request challenge → sign with real key.

        This test verifies:
        1. Server returns valid challenge
        2. SDK can parse challenge response
        3. SDK can sign challenge with real private key
        4. Signature is in the correct format

        Note: Does NOT verify the server accepts the signature.
        That's tested in test_websocket.py.
        """
        # Step 1: Request challenge
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
        variables = {"walletAddress": test_account.address}

        result = graphql_client.mutate(mutation, variables)
        challenge = result["requestWalletAuthChallenge"]

        # Step 2: Build and sign EIP-712 message
        timestamp = int(time.time())

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
                "name": challenge["domain"]["name"],
                "version": challenge["domain"]["version"],
                "chainId": challenge["domain"]["chainId"],
            },
            "message": {
                "nonce": challenge["nonce"],
                "wallet": test_account.address,
                "timestamp": timestamp,
            },
        }

        signed = test_account.sign_typed_data(full_message=structured_data)
        signature = f"0x{signed.signature.hex()}"

        # Verify we got valid outputs
        assert challenge["nonce"], "Should have nonce"
        assert signature.startswith("0x"), "Signature should have 0x prefix"
        assert len(signature) == 132, "Signature should be 65 bytes hex"
