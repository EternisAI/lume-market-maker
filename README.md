# Lume Market Maker

Python SDK for interacting with Lume prediction markets. Built with EIP-712 signing and GraphQL API.

## Features

- Place buy and sell orders on prediction markets
- Get order details and status
- Fetch orderbook data
- Cancel orders

## Installation

### From GitHub

```bash
pip install git+https://github.com/EternisAI/lume-market-maker.git
```

Or with uv:

```bash
uv pip install git+https://github.com/EternisAI/lume-market-maker.git
```

### From Local Directory

```bash
pip install -e .
```

Or with uv:

```bash
uv pip install -e .
```

## Quick Start

### Prerequisites

Before using the API, you should login to the Lume platform and create a proxy wallet.

### Setup

Set your environment variable:

```bash
export PRIVATE_KEY="your_private_key_here"
```

### Environment selection (dev vs prod)

By default, the SDK uses the **dev** environment. You can switch defaults by setting:

```bash
export LUME_ENV=prod   # or dev
```

Optional hotfix overrides (take precedence over `LUME_ENV` defaults):

```bash
export LUME_API_URL="https://..."
export LUME_CHAIN_ID="10143"
export LUME_CTF_EXCHANGE_ADDRESS="0x..."
export LUME_NEGRISK_EXCHANGE_ADDRESS="0x..."
export LUME_FEE_RATE_BPS="0"
```

### Initialize Client

```python
from lume_market_maker import LumeClient

client = LumeClient(private_key="your_private_key")

print(f"EOA Address: {client.eoa_address}")
print(f"Proxy Wallet: {client.proxy_wallet}")
```

## Operations

### 1. Place Buy Order

```python
from lume_market_maker import LumeClient, OrderArgs, OrderSide

client = LumeClient(private_key="your_private_key")

# Create order arguments
order_args = OrderArgs(
    market_id="market_uuid",
    side=OrderSide.BUY,
    outcome="YES",  # Outcome label
    price=0.50,     # 0.50 USDC per share
    size=10.0,      # 10 shares
)

# Place order
response = client.create_and_place_order(order_args)
print(f"Order ID: {response['id']}")
```

### 2. Place Sell Order

```python
from lume_market_maker import LumeClient, OrderArgs, OrderSide

client = LumeClient(private_key="your_private_key")

order_args = OrderArgs(
    market_id="market_uuid",
    side=OrderSide.SELL,
    outcome="YES",
    price=0.95,  # 0.95 USDC per share
    size=2.0,    # 2 shares
)

response = client.create_and_place_order(order_args)
print(f"Order ID: {response['id']}")
```

### 3. Place Order with Custom Expiration

```python
import time
from lume_market_maker import LumeClient, OrderArgs, OrderSide

client = LumeClient(private_key="your_private_key")

# Set expiration to 7 days from now
expiration = int(time.time()) + (7 * 24 * 60 * 60)

order_args = OrderArgs(
    market_id="market_uuid",
    side=OrderSide.BUY,
    outcome="YES",
    price=0.50,
    size=10.0,
    expiration=expiration,  # Unix timestamp
)

response = client.create_and_place_order(order_args)
```

### 4. Get Order by ID

```python
from lume_market_maker import LumeClient

client = LumeClient(private_key="your_private_key")

order = client.get_order("order_uuid")

# Order fields
print(f"Status: {order.status}")
print(f"Side: {order.side}")
print(f"Type: {order.type}")
print(f"Price: {float(order.price) / 1_000_000:.6f}")
print(f"Shares: {float(order.shares) / 1_000_000:.2f}")
print(f"Filled Shares: {float(order.filled_shares) / 1_000_000:.2f}")
print(f"Created At: {order.created_at}")
print(f"Expires At: {order.expires_at}")
```

### 5. Get Market Information

```python
from lume_market_maker import LumeClient

client = LumeClient(private_key="your_private_key")

market = client.get_market("market_uuid")

print(f"Market ID: {market.id}")
for outcome in market.outcomes:
    print(f"  {outcome.label}: {outcome.id} (token: {outcome.token_id})")
```

### 6. Get Orderbook

```python
from lume_market_maker import LumeClient

client = LumeClient(private_key="your_private_key")

# Fetch orderbook
orderbook = client.get_orderbook(
    market_id="market_uuid",
    outcome="YES"  # Outcome label
)

print(f"Outcome: {orderbook.outcome.label}")

# Display bids
print("\nBIDS")
for bid in orderbook.bids[:10]:
    price = float(bid.price) / 1_000_000
    shares = float(bid.shares) / 1_000_000
    print(f"  ${price:.6f} - {shares:.2f} shares")

# Display asks
print("\nASKS")
for ask in orderbook.asks[:10]:
    price = float(ask.price) / 1_000_000
    shares = float(ask.shares) / 1_000_000
    print(f"  ${price:.6f} - {shares:.2f} shares")
```

### 7. Cancel Order

```python
from lume_market_maker import LumeClient

client = LumeClient(private_key="your_private_key")

response = client.cancel_order("order_uuid")

print(f"Order ID: {response['id']}")
print(f"Status: {response['status']}")
```

## Complete Example

```python
import os
from lume_market_maker import LumeClient, OrderArgs, OrderSide

# Initialize client
private_key = os.getenv("PRIVATE_KEY")
market_id = os.getenv("MARKET_ID")

client = LumeClient(private_key=private_key)

print(f"EOA Address: {client.eoa_address}")
print(f"Proxy Wallet: {client.proxy_wallet}")

# Create and place order
order_args = OrderArgs(
    market_id=market_id,
    side=OrderSide.BUY,
    outcome="YES",
    price=0.50,
    size=10.0,
)

# Print order details before placing
order_args.print_order()

# Place order
response = client.create_and_place_order(order_args)
order_id = response['id']
print(f"\nOrder placed: {order_id}")

# Get order details
order = client.get_order(order_id)
print(f"Order status: {order.status}")
print(f"Filled: {float(order.filled_shares) / 1_000_000:.2f} shares")

# Get orderbook
orderbook = client.get_orderbook(market_id, "YES")
print(f"\nOrderbook has {len(orderbook.bids)} bids and {len(orderbook.asks)} asks")

# Cancel order if needed
# cancel_response = client.cancel_order(order_id)
# print(f"Order cancelled: {cancel_response['status']}")
```

## API Reference

### LumeClient

#### Constructor

```python
LumeClient(
    private_key: str,
    api_url: Optional[str] = None,
    chain_id: Optional[int] = None,
    fee_rate_bps: Optional[int] = None,
    proxy_wallet: Optional[str] = None,
    signature_type: int = SIGNATURE_TYPE_POLY_GNOSIS_SAFE,
    ctf_exchange_address: Optional[str] = None,
    negrisk_exchange_address: Optional[str] = None,
)
```

**Parameters:**

- `private_key`: Private key for signing orders (hex string with or without 0x prefix)
- `api_url`: GraphQL API endpoint URL (default: from selected env config)
- `chain_id`: Chain ID for the network (default: from selected env config)
- `fee_rate_bps`: Fee rate in basis points (default: from selected env config)
- `proxy_wallet`: Optional proxy wallet address (if None, fetched from API)
- `signature_type`: Signature type (0=EOA, 1=POLY_PROXY, 2=POLY_GNOSIS_SAFE)
- `ctf_exchange_address`: Optional override for CTF exchange address
- `negrisk_exchange_address`: Optional override for NegRisk exchange address

#### Methods

##### `create_and_place_order(order_args, order_type=OrderType.LIMIT, nonce=0) -> dict`

Create, sign, and place an order.

**Returns:** `{"id": "order_uuid"}`

##### `get_order(order_id: str) -> Order`

Get order details by ID.

**Returns:** `Order` object with all order fields

##### `get_market(market_id: str) -> Market`

Get market information including outcomes.

**Returns:** `Market` object with outcomes list

##### `get_orderbook(market_id: str, outcome: str) -> OrderBook`

Get orderbook for a specific market outcome.

**Parameters:**

- `market_id`: Market UUID
- `outcome`: Outcome label (e.g., "YES", "NO")

**Returns:** `OrderBook` object with bids and asks

##### `cancel_order(order_id: str) -> dict`

Cancel an order.

**Returns:** `{"id": "order_uuid", "status": "CANCELLED"}`

### OrderArgs

```python
OrderArgs(
    market_id: str,
    side: OrderSide,
    outcome: str,
    price: float,
    size: float,
    expiration: int | None = None,
)
```

**Parameters:**

- `market_id`: Market UUID
- `side`: `OrderSide.BUY` or `OrderSide.SELL`
- `outcome`: Outcome label (e.g., "YES", "NO")
- `price`: Price per share (0.01 to 0.99)
- `size`: Number of shares
- `expiration`: Optional unix timestamp (default: 24 hours from now)

**Methods:**

- `print_order()`: Print formatted order details

### Types

#### Order

Contains order details: `id`, `market_id`, `outcome_id`, `user_id`, `side`, `type`, `status`, `time_in_force`, `price`, `shares`, `filled_shares`, `collateral_locked`, `fee_amount`, `eoa_wallet`, `created_at`, `updated_at`, `expires_at`

#### Market

Contains: `id`, `outcomes` (list of Outcome)

#### Outcome

Contains: `id`, `label`, `token_id`

#### OrderBook

Contains: `outcome` (Outcome), `bids` (list of OrderBookLevel), `asks` (list of OrderBookLevel)

#### OrderBookLevel

Contains: `price`, `shares`

## Examples

The `examples/` directory contains complete working examples:

- `place_buy_order.py` - Place a buy order and fetch details
- `place_sell_order.py` - Place a sell order and fetch details
- `get_orderbook.py` - Fetch and display orderbook data
- `populate_orderbook.py` - Populate orderbook with realistic spread (market making)

Run examples with:

```bash
export PRIVATE_KEY="your_private_key"
export MARKET_ID="your_market_id"

uv run examples/place_buy_order.py
uv run examples/place_sell_order.py
uv run examples/get_orderbook.py
```

### Market Making Example

The `populate_orderbook.py` script creates multiple orders at different price levels to simulate a real orderbook:

```bash
# Test in dry-run mode first
export PRIVATE_KEY="your_private_key"
export MARKET_ID="your_market_id"
export INITIAL_YES_PRICE="0.55"
export TOTAL_CAPITAL="1000"
export TOTAL_YES_SHARES="1000"

uv run examples/populate_orderbook.py

# Then place real orders
export DRY_RUN="false"
uv run examples/populate_orderbook.py
```

See [`examples/ORDERBOOK_POPULATION.md`](examples/ORDERBOOK_POPULATION.md) for detailed documentation.

## Decimal Precision

All prices and sizes are internally converted to 6 decimal precision (1e6):

- **Input:** User provides decimal values (e.g., `price=0.50`, `size=10.0`)
- **Internal:** Multiplied by 1,000,000 for API (e.g., `500000`, `10000000`)
- **Output:** API returns strings with 1e6 precision, divide by 1,000,000 to display

Example:

```python
# Input
order_args = OrderArgs(price=0.50, size=10.0, ...)

# What gets sent to API
{
    "price": "500000",      # 0.50 * 1,000,000
    "shares": "10000000"    # 10.0 * 1,000,000
}

# Display from API response
order = client.get_order(order_id)
price = float(order.price) / 1_000_000  # "500000" -> 0.50
shares = float(order.shares) / 1_000_000  # "10000000" -> 10.0
```

## Network Configuration

**Default Network (LUME_ENV=dev):**

- Chain ID: 10143
- CTF Exchange Address: `0x4fEa4E2B6B90f8940ff9A5C7dd75c1299584522D`
- NegRisk Exchange Address: `0x2cCE4F55DAcab307b48D4d8C1139F1425cCF6759`
- API URL: `https://server-graphql-dev.up.railway.app/query`

To use production defaults, set `LUME_ENV=prod` (and/or the `LUME_*` overrides above).

## License

MIT
