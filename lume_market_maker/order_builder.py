"""Order builder and signer for Lume Market Maker."""

import time
from decimal import Decimal

from eth_account import Account
from eth_account.signers.local import LocalAccount

from lume_market_maker.constants import (
    DEFAULT_CHAIN_ID,
    DEFAULT_EXCHANGE_ADDRESS,
    DEFAULT_FEE_RATE_BPS,
    DOMAIN_NAME,
    DOMAIN_VERSION,
    USDC_DECIMALS,
    ZERO_ADDRESS,
)
from lume_market_maker.types import OrderArgs, OrderSide, SignedOrder

USDC_TICK = 1000
TOKEN_TICK = 10000


def align_down(amount: int) -> int:
    return (amount // TOKEN_TICK) * TOKEN_TICK


def align_up(amount: int) -> int:
    return ((amount + USDC_TICK - 1) // USDC_TICK) * USDC_TICK


class OrderBuilder:
    """Builder for creating and signing orders using EIP-712."""

    def __init__(
        self,
        private_key: str,
        chain_id: int = DEFAULT_CHAIN_ID,
        exchange_address: str = DEFAULT_EXCHANGE_ADDRESS,
        fee_rate_bps: int = DEFAULT_FEE_RATE_BPS,
    ):
        """
        Initialize order builder.

        Args:
            private_key: Private key for signing orders (hex string with or without 0x prefix)
            chain_id: Chain ID for the network
            exchange_address: Exchange contract address
            fee_rate_bps: Fee rate in basis points
        """
        self.chain_id = chain_id
        self.exchange_address = exchange_address
        self.fee_rate_bps = fee_rate_bps

        # Initialize account
        if not private_key.startswith("0x"):
            private_key = f"0x{private_key}"
        self.account: LocalAccount = Account.from_key(private_key)
        self.eoa_address = self.account.address

    def build_and_sign_order(
        self,
        proxy_wallet: str,
        order_args: OrderArgs,
        outcome_id: str,
        token_id: str,
        nonce: int = 0,
        expiration_days: int | None = None,
    ) -> SignedOrder:
        """
        Build and sign an order using EIP-712.

        Args:
            proxy_wallet: Proxy wallet address (maker)
            order_args: Order arguments
            outcome_id: Outcome ID from market
            token_id: Token ID from outcome
            nonce: Order nonce
            expiration_days: Deprecated - use order_args.expiration instead

        Returns:
            Signed order
        """
        # Calculate amounts
        # User provides price and size in decimal format (e.g., 0.5, 10.0)
        # We need to convert to integer amounts with proper decimals
        price_decimal = Decimal(str(order_args.price))
        size_decimal = Decimal(str(order_args.size))

        # Convert to integer amounts (multiply by 1e6 for USDC decimals)
        shares_amount = int(size_decimal * Decimal(10**USDC_DECIMALS))
        usdc_amount = int(price_decimal * size_decimal * Decimal(10**USDC_DECIMALS))

        # Determine order side (0 = BUY, 1 = SELL)
        order_side = 0 if order_args.side == OrderSide.BUY else 1

        if order_args.side == OrderSide.BUY:
            maker_amount = align_up(usdc_amount)
            taker_amount = align_down(shares_amount)
        else:
            maker_amount = align_down(shares_amount)
            taker_amount = align_up(usdc_amount)

        # Generate salt and expiration
        salt = int(time.time() * 1_000_000_000)  # nanoseconds

        # Use order_args.expiration if provided, otherwise default to 1 year from now
        if order_args.expiration is not None:
            expiration = order_args.expiration
        else:
            expiration = int(time.time()) + (365 * 24 * 60 * 60)  # 1 year from now

        # Build EIP-712 typed data
        structured_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Order": [
                    {"name": "salt", "type": "uint256"},
                    {"name": "maker", "type": "address"},
                    {"name": "signer", "type": "address"},
                    {"name": "taker", "type": "address"},
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "makerAmount", "type": "uint256"},
                    {"name": "takerAmount", "type": "uint256"},
                    {"name": "expiration", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "feeRateBps", "type": "uint256"},
                    {"name": "side", "type": "uint8"},
                    {"name": "signatureType", "type": "uint8"},
                ],
            },
            "primaryType": "Order",
            "domain": {
                "name": DOMAIN_NAME,
                "version": DOMAIN_VERSION,
                "chainId": self.chain_id,
                "verifyingContract": self.exchange_address,
            },
            "message": {
                "salt": salt,
                "maker": proxy_wallet,
                "signer": self.eoa_address,
                "taker": ZERO_ADDRESS,
                "tokenId": int(token_id),
                "makerAmount": maker_amount,
                "takerAmount": taker_amount,
                "expiration": expiration,
                "nonce": nonce,
                "feeRateBps": self.fee_rate_bps,
                "side": order_side,
                "signatureType": 1,  # EOA signature
            },
        }

        # Sign the EIP-712 typed data
        signed_message = self.account.sign_typed_data(full_message=structured_data)

        # Return signed order
        return SignedOrder(
            salt=str(salt),
            maker=proxy_wallet,
            signer=self.eoa_address,
            taker=ZERO_ADDRESS,
            token_id=token_id,
            maker_amount=str(maker_amount),
            taker_amount=str(taker_amount),
            expiration=str(expiration),
            nonce=str(nonce),
            fee_rate_bps=str(self.fee_rate_bps),
            side=order_side,
            signature_type=1,
            signature=f"0x{signed_message.signature.hex()}",
        )
