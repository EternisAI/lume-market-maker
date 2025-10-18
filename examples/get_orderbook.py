"""Example script for fetching orderbook data."""

import os

from lume_market_maker import LumeClient


def main():
    """Fetch and display orderbook for a market outcome."""
    # Configuration
    private_key = os.getenv("PRIVATE_KEY", "")
    market_id = os.getenv("MARKET_ID", "")

    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable is required")
    if not market_id:
        raise ValueError("MARKET_ID environment variable is required")

    print("Initializing Lume client...")
    client = LumeClient(private_key=private_key)

    # Get orderbook
    print(f"\nFetching orderbook for market: {market_id}")
    try:
        orderbook = client.get_orderbook(market_id=market_id, outcome="YES")

        print(f"\n{'Orderbook':<30s}: {orderbook.outcome.label}")
        print(f"{'Outcome ID':<30s}: {orderbook.outcome.id}")
        print(f"{'Token ID':<30s}: {orderbook.outcome.token_id}")

        print(f"\n{'BIDS':<30s}")
        print(f"{'Price':<15s} {'Shares':<15s}")
        print("-" * 30)
        for bid in orderbook.bids[:10]:  # Show top 10 bids
            price_decimal = float(bid.price) / 1_000_000
            shares_decimal = float(bid.shares) / 1_000_000
            print(f"${price_decimal:<14.6f} {shares_decimal:<15.2f}")

        print(f"\n{'ASKS':<30s}")
        print(f"{'Price':<15s} {'Shares':<15s}")
        print("-" * 30)
        for ask in orderbook.asks[:10]:  # Show top 10 asks
            price_decimal = float(ask.price) / 1_000_000
            shares_decimal = float(ask.shares) / 1_000_000
            print(f"${price_decimal:<14.6f} {shares_decimal:<15.2f}")

    except Exception as e:
        print(f"\n✗ Failed to fetch orderbook: {e}")
        raise


if __name__ == "__main__":
    main()
