# Lume Market Maker Examples

This directory contains example scripts demonstrating how to use the Lume Market Maker library.

## Setup

1. Install the package and dependencies:
```bash
pip install -e ..
```

2. Set up environment variables:
```bash
export PRIVATE_KEY="your_private_key_here"
export MARKET_ID="market_uuid_here"
# LUME_API_URL is optional - defaults to dev server
```

## Examples

### 1. Get Market Information

Fetch and display market details and outcomes.

```bash
python get_market.py
```

### 2. Place a Buy Order

Place a simple buy order on a market.

```bash
python place_buy_order.py
```

This will:
- Initialize the client and fetch your proxy wallet
- Get market information
- Place a BUY order for 10 shares at $0.50

### 3. Place a Sell Order

Place a simple sell order on a market.

```bash
python place_sell_order.py
```

This will:
- Initialize the client and fetch your proxy wallet
- Get market information
- Place a SELL order for 2 shares at $0.95

### 4. Market Maker with Ladder Orders

Place multiple buy and sell orders in a ladder pattern around a target probability.

```bash
# Place buy orders with $50 USDC
export BUY_AMOUNT=50
export PROBABILITY=0.5
export SPREAD=0.3
export NUM_ORDERS=5
python market_maker.py
```

```bash
# Place sell orders with 100 shares
export SELL_SHARES=100
export PROBABILITY=0.5
export SPREAD=0.3
export NUM_ORDERS=5
python market_maker.py
```

```bash
# Place both buy and sell orders
export BUY_AMOUNT=50
export SELL_SHARES=100
export PROBABILITY=0.5
export SPREAD=0.3
export NUM_ORDERS=5
python market_maker.py
```

#### Parameters

- `PRIVATE_KEY`: Your private key (required)
- `MARKET_ID`: Market UUID (required)
- `LUME_API_URL`: API endpoint (optional, defaults to dev server)
- `PROBABILITY`: Target probability/center price (default: 0.5)
- `BUY_AMOUNT`: Total USDC for buy orders (default: 0)
- `SELL_SHARES`: Total shares for sell orders (default: 0)
- `NUM_ORDERS`: Number of orders per side (default: 5)
- `SPREAD`: Price spread from center (default: 0.3)

## How It Works

1. **Initialization**: The client connects to the API and derives your proxy wallet address from your EOA
2. **Order Creation**: Orders are built with the specified parameters
3. **Order Signing**: Orders are signed using EIP-712 (same as Polymarket)
4. **Order Placement**: Signed orders are submitted via GraphQL mutation

## Notes

- The library uses the same order signing mechanism as Polymarket
- Orders are signed by your EOA but executed through your proxy wallet
- Make sure you have sufficient USDC in your proxy wallet for buy orders
- Make sure you have sufficient shares for sell orders
