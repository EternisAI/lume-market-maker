"""Example script for placing orders on Lume markets."""

import os

from lume_market_maker import LumeClient, OrderArgs, OrderSide


def main():
    """Place a simple buy order."""
    # Configuration
    private_key = os.getenv("PRIVATE_KEY", "")
    market_id = os.getenv("MARKET_ID", "")

    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable is required")
    if not market_id:
        raise ValueError("MARKET_ID environment variable is required")

    print("Initializing Lume client...")
    client = LumeClient(private_key=private_key)

    print(f"EOA Address: {client.eoa_address}")
    print(f"Proxy Wallet: {client.proxy_wallet}")

    # Create order arguments
    order_args = OrderArgs(
        market_id=market_id,
        side=OrderSide.BUY,
        outcome="YES",  # Simple outcome label
        price=0.50,  # 0.50 USDC per share
        size=10.0,  # 10 shares
    )

    # Print order details
    order_args.print_order()

    # Place order
    try:
        response = client.create_and_place_order(order_args)
        order_id = response['id']
        print(f"\n✓ Order placed successfully!")
        print(f"{'Order ID':<30s}: {order_id}")

        # Fetch order details
        print(f"\nFetching order details...")
        order = client.get_order(order_id)

        print(f"\n{'Order Details':<30s}")
        print(f"{'Status':<30s}: {order.status}")
        print(f"{'Side':<30s}: {order.side}")
        print(f"{'Type':<30s}: {order.type}")
        print(f"{'Price':<30s}: {float(order.price) / 1_000_000:.6f}")
        print(f"{'Shares':<30s}: {float(order.shares) / 1_000_000:.2f}")
        print(f"{'Filled Shares':<30s}: {float(order.filled_shares) / 1_000_000:.2f}")
        print(f"{'Collateral Locked':<30s}: {float(order.collateral_locked) / 1_000_000:.2f}")
        print(f"{'Fee Amount':<30s}: {float(order.fee_amount) / 1_000_000:.6f}")
        print(f"{'Created At':<30s}: {order.created_at}")
        print(f"{'Expires At':<30s}: {order.expires_at}")

    except Exception as e:
        print(f"\n✗ Order failed: {e}")
        raise


if __name__ == "__main__":
    main()
