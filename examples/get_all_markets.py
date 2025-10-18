"""Example script for fetching all markets."""

import os

from lume_market_maker import LumeClient


def main():
    """Get all markets from the API."""
    # Configuration
    private_key = os.getenv("PRIVATE_KEY", "")

    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable is required")

    print("Initializing Lume client...")
    client = LumeClient(private_key=private_key)

    print(f"EOA Address: {client.eoa_address}")
    print(f"Proxy Wallet: {client.proxy_wallet}")

    # Get all markets
    print("\nFetching all markets...")
    markets = client.get_all_markets(status="ACTIVE")

    print(f"\nTotal markets: {len(markets)}")
    print()

    for i, market in enumerate(markets):
        print(f"Market {i + 1}:")
        print(f"  ID: {market.id}")
        if market.slug:
            print(f"  Slug: {market.slug}")
        if market.question:
            print(f"  Question: {market.question}")
        if market.status:
            print(f"  Status: {market.status}")
        print(f"  Outcomes: {len(market.outcomes)}")
        for outcome in market.outcomes:
            print(f"    - {outcome.label} (ID: {outcome.id})")
        if market.volume:
            print(f"  Volume: {market.volume}")
        if market.liquidity:
            print(f"  Liquidity: {market.liquidity}")
        if market.open_interest:
            print(f"  Open Interest: {market.open_interest}")
        print()


if __name__ == "__main__":
    main()
