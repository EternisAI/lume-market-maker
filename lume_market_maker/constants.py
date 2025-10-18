"""Constants for Lume Market Maker."""

# Default values
DEFAULT_API_URL = "https://server-graphql-dev.up.railway.app/query"
DEFAULT_CHAIN_ID = 84532  # Base Sepolia
DEFAULT_EXCHANGE_ADDRESS = "0xCf4a367D980a8FB9D4d64a3851C3b77FE3801f97"
DEFAULT_FEE_RATE_BPS = 0

# EIP-712 Domain
DOMAIN_NAME = "Polymarket CTF Exchange"
DOMAIN_VERSION = "1"

# Order constants
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ORDER_STRUCTURE_HASH = "Order(uint256 salt,address maker,address signer,address taker,uint256 tokenId,uint256 makerAmount,uint256 takerAmount,uint256 expiration,uint256 nonce,uint256 feeRateBps,uint8 side,uint8 signatureType)"

# USDC decimals
USDC_DECIMALS = 6

# Order expiration (30 days)
DEFAULT_ORDER_EXPIRATION_DAYS = 30
