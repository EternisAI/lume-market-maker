"""Example: Subscribe to real-time order updates.

This example demonstrates how to use wallet-based authentication to subscribe
to real-time order updates for your account.

Prerequisites:
- Set PRIVATE_KEY environment variable with your wallet's private key
- Optionally set LUME_ENV=prod (defaults to dev)
- Optionally override endpoint with LUME_API_URL (or legacy API_URL)

Usage:
    export PRIVATE_KEY=your_private_key_here
    python examples/subscribe_orders.py
"""

import asyncio
import os
import signal
import sys

# Add parent directory to path for local development
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lume_market_maker import LumeClient


async def subscribe_to_orders():
    """Subscribe to order updates and print them to console."""
    private_key = os.environ.get("PRIVATE_KEY")
    if not private_key:
        print("Error: PRIVATE_KEY environment variable is required")
        print("Usage: PRIVATE_KEY=0x... python examples/subscribe_orders.py")
        sys.exit(1)

    # Prefer new env-based config; keep API_URL as a backward-compatible alias.
    api_url = os.environ.get("LUME_API_URL") or os.environ.get("API_URL")

    print(f"Connecting to {api_url or '(default from LUME_ENV)'}...")
    client = LumeClient(private_key=private_key, api_url=api_url)
    print(f"Wallet: {client.eoa_address}")
    print(f"Proxy wallet: {client.proxy_wallet}")
    print()

    # Set up graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler():
        print("\nShutting down...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        print("Subscribing to order updates...")
        print("(Press Ctrl+C to exit)")
        print("-" * 60)

        async for update in client.subscribe_to_order_updates():
            if shutdown_event.is_set():
                break

            order = update.order
            print(f"[{update.type}] Order {order.id[:8]}...")
            print(f"  Status:  {order.status}")
            print(f"  Side:    {order.side}")
            print(f"  Price:   ${order.price}")
            print(f"  Shares:  {order.shares} (filled: {order.filled_shares})")
            print(f"  Time:    {update.timestamp}")
            print("-" * 60)

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        print("Closing WebSocket connection...")
        await client.close_websocket()
        print("Done")


async def subscribe_to_positions():
    """Subscribe to position updates and print them to console."""
    private_key = os.environ.get("PRIVATE_KEY")
    if not private_key:
        print("Error: PRIVATE_KEY environment variable is required")
        sys.exit(1)

    # Prefer new env-based config; keep API_URL as a backward-compatible alias.
    api_url = os.environ.get("LUME_API_URL") or os.environ.get("API_URL")

    print(f"Connecting to {api_url or '(default from LUME_ENV)'}...")
    client = LumeClient(private_key=private_key, api_url=api_url)
    print(f"Wallet: {client.eoa_address}")
    print()

    try:
        print("Subscribing to position updates...")
        print("(Press Ctrl+C to exit)")
        print("-" * 60)

        async for update in client.subscribe_to_position_updates():
            position = update.position
            print(f"[{update.type}] Position {position.id[:8]}...")
            print(f"  Outcome: {position.outcome.label}")
            print(f"  Shares:  {position.shares}")
            print(f"  Avg Price: ${position.average_price}")
            print(f"  PnL:     ${position.pnl_unrealized} ({position.percent_pnl}%)")
            print(f"  Time:    {update.timestamp}")
            print("-" * 60)

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        await client.close_websocket()
        print("Done")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Subscribe to real-time updates")
    parser.add_argument(
        "--type",
        choices=["orders", "positions"],
        default="orders",
        help="Type of updates to subscribe to (default: orders)",
    )
    args = parser.parse_args()

    if args.type == "orders":
        asyncio.run(subscribe_to_orders())
    else:
        asyncio.run(subscribe_to_positions())
