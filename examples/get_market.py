"""Example script for fetching market information."""

import os

from lume_market_maker import LumeClient


def main():
    """Get market information."""
    # Configuration
    private_key = os.getenv("PRIVATE_KEY", "")
    market_id = os.getenv("MARKET_ID", "")

    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable is required")
    if not market_id:
        raise ValueError("MARKET_ID environment variable is required")

    # Initialize client (uses default API URL and chain_id)
    print("Initializing Lume client...")
    client = LumeClient(private_key=private_key)

    print(f"EOA Address: {client.eoa_address}")
    print(f"Proxy Wallet: {client.proxy_wallet}")

    # Get market information
    print(f"\nFetching market {market_id}...")
    market = client.get_market(market_id)

    print(f"\nMarket ID: {market.id}")
    print(f"Outcomes: {len(market.outcomes)}")
    print()

    for i, outcome in enumerate(market.outcomes):
        print(f"Outcome {i + 1}:")
        print(f"  ID: {outcome.id}")
        print(f"  Label: {outcome.label}")
        print(f"  Token ID: {outcome.token_id}")
        print()


if __name__ == "__main__":
    main()
