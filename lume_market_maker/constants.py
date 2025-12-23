"""Constants for Lume Market Maker."""

# Default values
DEFAULT_API_URL = "https://server-graphql-dev.up.railway.app/query"
DEFAULT_CHAIN_ID = 10143

# Exchange addresses
CTF_EXCHANGE_ADDRESS = "0x4fEa4E2B6B90f8940ff9A5C7dd75c1299584522D"
NEGRISK_EXCHANGE_ADDRESS = "0x2cCE4F55DAcab307b48D4d8C1139F1425cCF6759"
DEFAULT_FEE_RATE_BPS = 0

# EIP-712 Domain
DOMAIN_NAME = "Lume CTF Exchange"
DOMAIN_VERSION = "1"

# Order constants
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ORDER_STRUCTURE_HASH = "Order(uint256 salt,address maker,address signer,address taker,uint256 tokenId,uint256 makerAmount,uint256 takerAmount,uint256 expiration,uint256 nonce,uint256 feeRateBps,uint8 side,uint8 signatureType)"

# USDC decimals
USDC_DECIMALS = 6

# Signature Types
SIGNATURE_TYPE_EOA = 0
SIGNATURE_TYPE_POLY_PROXY = 1
SIGNATURE_TYPE_POLY_GNOSIS_SAFE = 2
