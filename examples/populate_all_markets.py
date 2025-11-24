import os
import time
from typing import List, Tuple

from lume_market_maker import LumeClient, OrderArgs, OrderSide


def calculate_orderbook_levels(
    mid_price: float,
    total_capital: float,
    num_levels: int = 5,
    spread_bps: int = 50,
) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    spread = spread_bps / 10000.0
    half_spread = spread / 2
    capital_per_side = total_capital / 2

    yes_best_bid = max(0.01, min(0.99, mid_price - half_spread))
    no_best_bid = max(0.01, min(0.99, (1.0 - mid_price) - half_spread))

    yes_bid_prices = []
    for i in range(num_levels):
        price = max(0.01, min(0.99, yes_best_bid - (i * spread)))
        yes_bid_prices.append(price)

    no_bid_prices = []
    for i in range(num_levels):
        price = max(0.01, min(0.99, no_best_bid - (i * spread)))
        no_bid_prices.append(price)

    total_weight = sum(i + 1 for i in range(num_levels))

    yes_buy_orders = []
    for i, price in enumerate(yes_bid_prices):
        weight = (i + 1) / total_weight
        capital_for_level = capital_per_side * weight
        size = capital_for_level / price
        yes_buy_orders.append((price, size))

    no_buy_orders = []
    for i, price in enumerate(no_bid_prices):
        weight = (i + 1) / total_weight
        capital_for_level = capital_per_side * weight
        size = capital_for_level / price
        no_buy_orders.append((price, size))

    return yes_buy_orders, no_buy_orders


def print_orderbook_preview(
    yes_buy_orders: List[Tuple[float, float]],
    no_buy_orders: List[Tuple[float, float]],
    mid_price: float,
):
    print(f"\n  Orderbook Preview (YES mid: ${mid_price:.4f})")
    print(f"  {'-'*60}")

    if yes_buy_orders and no_buy_orders:
        highest_yes_bid = max(p for p, _ in yes_buy_orders)
        highest_no_bid = max(p for p, _ in no_buy_orders)
        implied_yes_ask = 1.0 - highest_no_bid

        print(f"  Highest YES bid: ${highest_yes_bid:.4f}")
        print(
            f"  Highest NO bid: ${highest_no_bid:.4f} → implied YES ask: ${implied_yes_ask:.4f}"
        )

        if highest_yes_bid >= implied_yes_ask:
            print(f"  ⚠ WARNING: Overlap detected!")
        else:
            spread_pct = (implied_yes_ask - highest_yes_bid) * 100
            print(f"  ✓ No overlap - spread: {spread_pct:.2f}%")

    print(f"\n  YES BUY Orders (YES bids):")
    total_yes_capital = 0
    for price, size in yes_buy_orders:
        capital = price * size
        total_yes_capital += capital
        print(f"    BUY YES @ ${price:.4f} x {size:>10.2f} = ${capital:>10.2f}")

    print(f"\n  NO BUY Orders (equivalent to YES asks):")
    total_no_capital = 0
    for price, size in no_buy_orders:
        capital = price * size
        implied_yes = 1.0 - price
        total_no_capital += capital
        print(
            f"    BUY NO  @ ${price:.4f} x {size:>10.2f} = ${capital:>10.2f}  (YES ask @ ${implied_yes:.4f})"
        )

    print(f"\n  Total capital for YES buys: ${total_yes_capital:.2f}")
    print(f"  Total capital for NO buys: ${total_no_capital:.2f}")
    print(f"  {'-'*60}")


def place_orders(
    client: LumeClient,
    market_id: str,
    yes_buy_orders: List[Tuple[float, float]],
    no_buy_orders: List[Tuple[float, float]],
):
    placed_orders = []

    for price, size in yes_buy_orders:
        try:
            order_args = OrderArgs(
                market_id=market_id,
                side=OrderSide.BUY,
                outcome="YES",
                price=price,
                size=size,
            )
            response = client.create_and_place_order(order_args)
            placed_orders.append(response["id"])
            print(f"    ✓ BUY YES @ ${price:.4f} x {size:.2f} - ID: {response['id']}")
            time.sleep(0.1)
        except Exception as e:
            print(f"    ✗ BUY YES @ ${price:.4f}: {e}")

    for price, size in no_buy_orders:
        try:
            order_args = OrderArgs(
                market_id=market_id,
                side=OrderSide.BUY,
                outcome="NO",
                price=price,
                size=size,
            )
            response = client.create_and_place_order(order_args)
            placed_orders.append(response["id"])
            implied_yes = 1.0 - price
            print(
                f"    ✓ BUY NO  @ ${price:.4f} x {size:.2f} (YES ask @ ${implied_yes:.4f}) - ID: {response['id']}"
            )
            time.sleep(0.1)
        except Exception as e:
            print(f"    ✗ BUY NO  @ ${price:.4f}: {e}")

    return placed_orders


def main():
    private_key = os.getenv("PRIVATE_KEY", "")
    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable is required")

    mid_price = float(os.getenv("MID_PRICE", "0.50"))
    total_capital = float(os.getenv("TOTAL_CAPITAL", "1000.0"))
    num_levels = int(os.getenv("NUM_LEVELS", "5"))
    spread_bps = int(os.getenv("SPREAD_BPS", "200"))
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    print("=" * 80)
    print("Lume Market Maker - Populate All Markets (Collateral Only)")
    print("=" * 80)
    print(f"\nStrategy: BUY YES + BUY NO (collateral only, no shares needed)")
    print(f"  - BUY YES creates YES bids")
    print(f"  - BUY NO creates YES asks (at 1 - NO_price)")
    print(f"\nConfiguration:")
    print(f"  Mid Price (YES): ${mid_price:.4f}")
    print(f"  Total Capital: ${total_capital:.2f}")
    print(f"  Price Levels: {num_levels} per side")
    print(f"  Spread: {spread_bps} bps ({spread_bps/100:.2f}%)")
    print(f"  Dry Run: {dry_run}")

    print("\nInitializing Lume client...")
    client = LumeClient(private_key=private_key)
    print(f"EOA Address: {client.eoa_address}")
    print(f"Proxy Wallet: {client.proxy_wallet}")

    print("\nFetching all active markets...")
    markets = client.get_all_markets(status="ACTIVE")
    print(f"Found {len(markets)} active markets")

    yes_buy_orders, no_buy_orders = calculate_orderbook_levels(
        mid_price=mid_price,
        total_capital=total_capital,
        num_levels=num_levels,
        spread_bps=spread_bps,
    )

    total_orders_placed = 0
    successful_markets = 0
    failed_markets = 0

    for i, market in enumerate(markets, 1):
        print(f"\n{'='*80}")
        print(
            f"[{i}/{len(markets)}] Market: {market.question[:60] if market.question else market.id}..."
        )
        print(f"ID: {market.id}")
        print(f"Outcomes: {[o.label for o in market.outcomes]}")

        if i == 1:
            print_orderbook_preview(yes_buy_orders, no_buy_orders, mid_price)

        if dry_run:
            print(
                f"\n  [DRY RUN] Would place {len(yes_buy_orders) + len(no_buy_orders)} orders"
            )
            successful_markets += 1
            continue

        try:
            placed_orders = place_orders(
                client=client,
                market_id=market.id,
                yes_buy_orders=yes_buy_orders,
                no_buy_orders=no_buy_orders,
            )

            total_orders_placed += len(placed_orders)
            successful_markets += 1
            print(f"\n  ✓ Market complete: {len(placed_orders)} orders placed")

        except Exception as e:
            failed_markets += 1
            print(f"\n  ✗ Market failed: {e}")
            continue

        if i < len(markets):
            time.sleep(0.5)

    print(f"\n{'='*80}")
    print("Summary")
    print(f"{'='*80}")
    print(f"Total markets processed: {len(markets)}")
    print(f"  Successful: {successful_markets}")
    print(f"  Failed: {failed_markets}")
    if not dry_run:
        print(f"Total orders placed: {total_orders_placed}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
