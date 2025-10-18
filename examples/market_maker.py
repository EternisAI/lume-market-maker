"""Example market maker script with ladder orders."""

import os
import time
from typing import List

from lume_market_maker import LumeClient, OrderArgs, OrderSide, OrderType


def calculate_ladder(
    center: float,
    spread: float,
    num_orders: int,
    total_amount: float,
    is_buy: bool,
) -> List[dict]:
    """
    Calculate ladder of orders around a center price.

    Args:
        center: Center price (probability)
        spread: Price spread (can be negative for buy orders)
        num_orders: Number of orders
        total_amount: Total USDC (for buys) or shares (for sells)
        is_buy: True for buy orders, False for sell orders

    Returns:
        List of order parameters
    """
    if num_orders == 0:
        return []

    delta = spread / num_orders
    orders = []

    for i in range(num_orders):
        price = center + (i * delta)

        # Clamp price to valid range
        if price < 0.01:
            price = 0.01
        if price > 0.99:
            price = 0.99

        # Calculate size (in decimal format)
        if is_buy:
            # For buy orders: divide total USDC across orders
            size = total_amount / num_orders / price
        else:
            # For sell orders: divide shares evenly
            size = total_amount / num_orders

        if size < 0.01:
            size = 0.01

        orders.append({
            "price": price,
            "size": size,  # Keep as float for decimal support
        })

    return orders


def place_orders(
    client: LumeClient,
    market_id: str,
    outcome_id: str,
    token_id: str,
    orders: List[dict],
    side: OrderSide,
):
    """Place multiple orders."""
    if not orders:
        return

    print(f"\nPlacing {len(orders)} {side.value} orders...")

    for i, order in enumerate(orders):
        order_args = OrderArgs(
            price=order["price"],
            size=order["size"],
            side=side,
            outcome_id=outcome_id,
            token_id=token_id,
        )

        try:
            response = client.create_and_place_order(
                market_id=market_id,
                order_args=order_args,
                order_type=OrderType.GTC,
            )
            print(f"  [{i+1}/{len(orders)}] ✓ {order['price']:.4f} × {order['size']} (ID: {response['id']})")
        except Exception as e:
            print(f"  [{i+1}/{len(orders)}] ✗ {e}")

        # Small delay between orders
        time.sleep(0.1)


def main():
    """Run market maker with ladder orders."""
    # Configuration
    private_key = os.getenv("PRIVATE_KEY", "")
    market_id = os.getenv("MARKET_ID", "")

    # Market making parameters
    probability = float(os.getenv("PROBABILITY", "0.5"))
    buy_amount = float(os.getenv("BUY_AMOUNT", "0"))  # USDC
    sell_shares = int(os.getenv("SELL_SHARES", "0"))  # Shares
    num_orders = int(os.getenv("NUM_ORDERS", "5"))
    spread = float(os.getenv("SPREAD", "0.3"))

    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable is required")
    if not market_id:
        raise ValueError("MARKET_ID environment variable is required")
    if probability <= 0 or probability >= 1:
        raise ValueError("PROBABILITY must be between 0 and 1")
    if buy_amount <= 0 and sell_shares <= 0:
        raise ValueError("Either BUY_AMOUNT or SELL_SHARES must be > 0")

    # Initialize client (uses default API URL and chain_id)
    print("Initializing Lume client...")
    client = LumeClient(private_key=private_key)

    print(f"EOA Address: {client.eoa_address}")
    print(f"Proxy Wallet: {client.proxy_wallet}")

    # Get market information
    print(f"\nFetching market {market_id}...")
    market = client.get_market(market_id)

    print(f"Market outcomes:")
    for i, outcome in enumerate(market.outcomes):
        print(f"  [{i}] {outcome.label}")

    # Select outcome (default to first one, or YES if available)
    outcome = market.outcomes[0]
    for o in market.outcomes:
        if o.label.upper() == "YES":
            outcome = o
            break

    print(f"\nSelected outcome: {outcome.label}")
    print(f"Probability: {probability:.2%}")
    print(f"Spread: {spread:.2%}")
    print(f"Orders per side: {num_orders}")

    # Calculate and place buy orders
    if buy_amount > 0:
        buy_orders = calculate_ladder(
            center=probability,
            spread=-spread,  # Negative spread for buy orders (below center)
            num_orders=num_orders,
            total_amount=buy_amount,
            is_buy=True,
        )
        print(f"\nBuy orders (${buy_amount} USDC):")
        for i, order in enumerate(buy_orders):
            print(f"  [{i+1}] {order['price']:.4f} × {order['size']}")

        place_orders(client, market_id, outcome.id, outcome.token_id, buy_orders, OrderSide.BUY)

    # Calculate and place sell orders
    if sell_shares > 0:
        sell_orders = calculate_ladder(
            center=probability,
            spread=spread,  # Positive spread for sell orders (above center)
            num_orders=num_orders,
            total_amount=float(sell_shares),
            is_buy=False,
        )
        print(f"\nSell orders ({sell_shares} shares):")
        for i, order in enumerate(sell_orders):
            print(f"  [{i+1}] {order['price']:.4f} × {order['size']}")

        place_orders(client, market_id, outcome.id, outcome.token_id, sell_orders, OrderSide.SELL)

    print("\n✓ Complete")


if __name__ == "__main__":
    main()
