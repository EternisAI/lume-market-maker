"""Example script for populating an orderbook with realistic spread."""

import os
import time
from typing import List, Tuple

from lume_market_maker import LumeClient, OrderArgs, OrderSide


def calculate_orderbook_levels(
    mid_price: float,
    total_capital: float,
    total_yes_shares: float,
    total_no_shares: float,
    num_levels: int = 5,
    spread_bps: int = 50,  # 50 basis points = 0.5%
) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """
    Calculate orderbook levels for YES outcome.

    Args:
        mid_price: Initial mid price for YES shares (0.01 to 0.99)
        total_capital: Total capital available for buy orders (USDC)
        total_yes_shares: Total YES shares available for sell orders
        total_no_shares: Total NO shares available (affects implied NO price)
        num_levels: Number of price levels on each side
        spread_bps: Spread in basis points (100 bps = 1%)

    Returns:
        Tuple of (buy_orders, sell_orders) where each is [(price, size), ...]
    """
    # Calculate spread
    spread = spread_bps / 10000.0
    half_spread = spread / 2

    # Best bid and ask around mid price
    best_bid = mid_price - half_spread
    best_ask = mid_price + half_spread

    # Ensure prices stay within valid range [0.01, 0.99]
    best_bid = max(0.01, min(0.99, best_bid))
    best_ask = max(0.01, min(0.99, best_ask))

    # Generate price levels
    # Bids: decreasing from best_bid
    bid_prices = []
    for i in range(num_levels):
        price = best_bid - (i * spread)
        price = max(0.01, min(0.99, price))
        bid_prices.append(price)

    # Asks: increasing from best_ask
    ask_prices = []
    for i in range(num_levels):
        price = best_ask + (i * spread)
        price = max(0.01, min(0.99, price))
        ask_prices.append(price)

    # Distribute capital across buy orders (more at worse prices - lowest prices, further from spread)
    buy_orders = []
    total_weight = sum(i + 1 for i in range(num_levels))

    for i, price in enumerate(bid_prices):
        # Weight: more capital at worse prices (i+1 means lower prices get more weight)
        weight = (i + 1) / total_weight
        capital_for_level = total_capital * weight
        size = capital_for_level / price
        buy_orders.append((price, size))

    # Distribute shares across sell orders (more at worse prices - higher prices, further from spread)
    sell_orders = []
    for i, price in enumerate(ask_prices):
        # Weight: more shares at worse prices (i+1 means higher prices get more weight)
        weight = (i + 1) / total_weight
        size = total_yes_shares * weight
        sell_orders.append((price, size))

    return buy_orders, sell_orders


def print_orderbook_preview(
    buy_orders: List[Tuple[float, float]],
    sell_orders: List[Tuple[float, float]],
    outcome: str = "YES",
):
    """Print a preview of the orderbook that will be created."""
    print(f"\n{'='*60}")
    print(f"Orderbook Preview for {outcome} Outcome")
    print(f"{'='*60}\n")

    if sell_orders:
        print(f"{'SELL ORDERS (ASKS)':<30s}")
        print(f"{'Price':<15s} {'Size':<15s} {'Total':<15s}")
        print("-" * 60)
        # Print in reverse order (highest ask first)
        for price, size in reversed(sell_orders):
            total = price * size
            print(f"${price:<14.6f} {size:<14.2f} ${total:<14.2f}")
    else:
        print(f"{'SELL ORDERS (ASKS)':<30s}")
        print("  (none - no shares available)")

    print(f"\n{'-'*60}\n")

    if buy_orders:
        print(f"{'BUY ORDERS (BIDS)':<30s}")
        print(f"{'Price':<15s} {'Size':<15s} {'Total':<15s}")
        print("-" * 60)
        for price, size in buy_orders:
            total = price * size
            print(f"${price:<14.6f} {size:<14.2f} ${total:<14.2f}")
    else:
        print(f"{'BUY ORDERS (BIDS)':<30s}")
        print("  (none - no capital available)")

    # Summary
    total_buy_capital = sum(p * s for p, s in buy_orders) if buy_orders else 0
    total_sell_shares = sum(s for _, s in sell_orders) if sell_orders else 0

    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Total Buy Orders: {len(buy_orders)}")
    print(f"  Total Buy Capital: ${total_buy_capital:.2f}")
    print(f"  Total Sell Orders: {len(sell_orders)}")
    print(f"  Total Sell Shares: {total_sell_shares:.2f}")
    print(f"{'='*60}\n")


def place_orderbook(
    client: LumeClient,
    market_id: str,
    outcome: str,
    buy_orders: List[Tuple[float, float]],
    sell_orders: List[Tuple[float, float]],
    dry_run: bool = True,
):
    """
    Place all orders in the orderbook.

    Args:
        client: Initialized LumeClient
        market_id: Market UUID
        outcome: Outcome label (e.g., "YES" or "NO")
        buy_orders: List of (price, size) tuples for buy orders
        sell_orders: List of (price, size) tuples for sell orders
        dry_run: If True, only print orders without placing them
    """
    if dry_run:
        print("\n*** DRY RUN MODE - No orders will be placed ***\n")
        return

    print(f"\nPlacing orders on market {market_id}...")
    print(f"Outcome: {outcome}\n")

    placed_orders = []

    # Place buy orders
    print(f"Placing {len(buy_orders)} buy orders...")
    for i, (price, size) in enumerate(buy_orders, 1):
        try:
            order_args = OrderArgs(
                market_id=market_id,
                side=OrderSide.BUY,
                outcome=outcome,
                price=price,
                size=size,
            )

            response = client.create_and_place_order(order_args)
            order_id = response["id"]
            placed_orders.append(order_id)
            print(
                f"  [{i}/{len(buy_orders)}] BUY  @ ${price:.6f} x {size:.2f} shares - Order ID: {order_id}"
            )

            # Small delay to avoid rate limiting
            time.sleep(0.1)

        except Exception as e:
            print(f"  [ERROR] Failed to place buy order @ ${price:.6f}: {e}")

    # Place sell orders
    print(f"\nPlacing {len(sell_orders)} sell orders...")
    for i, (price, size) in enumerate(sell_orders, 1):
        try:
            order_args = OrderArgs(
                market_id=market_id,
                side=OrderSide.SELL,
                outcome=outcome,
                price=price,
                size=size,
            )

            response = client.create_and_place_order(order_args)
            order_id = response["id"]
            placed_orders.append(order_id)
            print(
                f"  [{i}/{len(sell_orders)}] SELL @ ${price:.6f} x {size:.2f} shares - Order ID: {order_id}"
            )

            # Small delay to avoid rate limiting
            time.sleep(0.1)

        except Exception as e:
            print(f"  [ERROR] Failed to place sell order @ ${price:.6f}: {e}")

    print(f"\n✓ Successfully placed {len(placed_orders)} orders")
    return placed_orders


def main():
    """Populate orderbook with realistic spread."""
    # Configuration from environment
    private_key = os.getenv("PRIVATE_KEY", "")
    market_id = os.getenv("MARKET_ID", "")

    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable is required")
    if not market_id:
        raise ValueError("MARKET_ID environment variable is required")

    # Orderbook parameters (can be overridden via env vars)
    initial_yes_price = float(os.getenv("INITIAL_YES_PRICE", "0.50"))
    total_capital = float(os.getenv("TOTAL_CAPITAL", "5000.0"))
    total_yes_shares = float(os.getenv("TOTAL_YES_SHARES", "5000.0"))
    total_no_shares = float(os.getenv("TOTAL_NO_SHARES", "5000.0"))
    num_levels = int(os.getenv("NUM_LEVELS", "20"))
    spread_bps = int(os.getenv("SPREAD_BPS", "100"))
    outcome = os.getenv("OUTCOME", "YES")
    dry_run = False

    # Calculate NO price (complementary to YES price)
    initial_no_price = 1.0 - initial_yes_price

    print("\n" + "=" * 60)
    print("Lume Market Maker - Orderbook Population")
    print("=" * 60)
    print(f"\nConfiguration:")
    print(f"  Market ID: {market_id}")
    print(f"  Outcome: {outcome}")
    print(f"  Initial YES price: ${initial_yes_price:.6f}")
    print(f"  Initial NO price: ${initial_no_price:.6f}")
    print(f"  Total Capital: ${total_capital:.2f}")
    print(f"  Total YES Shares: {total_yes_shares:.2f}")
    print(f"  Total NO Shares: {total_no_shares:.2f}")
    print(f"  Price Levels: {num_levels} per side")
    print(f"  Spread: {spread_bps} basis points ({spread_bps/100:.2f}%)")
    print(f"  Dry Run: {dry_run}")

    # Use the appropriate price based on outcome
    mid_price = initial_yes_price if outcome == "YES" else initial_no_price
    shares_for_sell = total_yes_shares if outcome == "YES" else total_no_shares

    # Calculate orderbook levels only if we have capital or shares
    buy_orders = []
    sell_orders = []

    if total_capital > 0 or shares_for_sell > 0:
        buy_orders, sell_orders = calculate_orderbook_levels(
            mid_price=mid_price,
            total_capital=total_capital,
            total_yes_shares=shares_for_sell,
            total_no_shares=total_no_shares,
            num_levels=num_levels,
            spread_bps=spread_bps,
        )

        # Filter out orders based on available resources
        if total_capital == 0:
            buy_orders = []
        if shares_for_sell == 0:
            sell_orders = []

    if not buy_orders and not sell_orders:
        print("\n⚠ No orders to place: total_capital and shares are both 0")
        return

    # Print preview
    print_orderbook_preview(buy_orders, sell_orders, outcome)

    # Initialize client only if not in dry run mode
    if not dry_run:
        print("Initializing Lume client...")
        client = LumeClient(private_key=private_key)
        print(f"EOA Address: {client.eoa_address}")
        print(f"Proxy Wallet: {client.proxy_wallet}")
    else:
        client = None

    # Place orders
    placed_orders = place_orderbook(
        client=client,
        market_id=market_id,
        outcome=outcome,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
        dry_run=dry_run,
    )

    if not dry_run and placed_orders:
        print(f"\n{'='*60}")
        print("All orders placed successfully!")
        print(f"Total orders: {len(placed_orders)}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
