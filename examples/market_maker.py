"""Example: Simple market maker bot with delta-fill hedging.

This bot:
- Loads config from env vars
- Checks if you already have OPEN orders on a given market
- If not, populates a two-sided book using BUY YES and BUY NO ladders
- Starts:
  - HTTP polling of the YES/NO orderbooks (printing a compact top-of-book view)
  - Websocket subscription to myOrderUpdates
- On fills (delta filledShares) for non-hedge orders, places an opposite-side hedge
  order and records its id so updates for that hedge order are ignored.

Run:
  PRIVATE_KEY=... MARKET_ID=... uv run examples/market_maker.py
"""

import asyncio
import os
import signal
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

# Add parent directory to path for local development (matches other examples)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from lume_market_maker import LumeClient, OrderArgs, OrderSide, WebSocketError
from lume_market_maker.graphql import GraphQLError


MIN_ORDER_SIZE_SHARES = 5.0


def _clamp_price(p: float) -> float:
    return max(0.01, min(0.99, p))

def _parse_iso_z(ts: str) -> datetime | None:
    """
    Parse timestamps like '2025-12-23T17:04:04Z' into an aware datetime.
    Returns None if parsing fails.
    """
    try:
        s = (ts or "").strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _num_str_to_float(x: str) -> float:
    """
    Parse numeric strings that may come back either as:
    - human decimals: "0.46", "28.99"
    - atomic ints (1e6): "460000", "28990000"
    """
    try:
        s = str(x).strip()
        if not s:
            return 0.0
        if any(c in s for c in (".", "e", "E")):
            return float(s)
        i = int(s)
        # Heuristic: atomic values are typically large (scaled by 1e6).
        if abs(i) >= 10_000:
            return float(i) / 1_000_000.0
        return float(i)
    except (TypeError, ValueError, OverflowError):
        return 0.0


@dataclass(frozen=True)
class BotConfig:
    private_key: str
    market_id: str
    api_url: str | None
    mid_price: float
    spread_bps: int
    num_levels: int
    total_capital_yes: float
    total_capital_no: float
    orderbook_poll_secs: float

    @property
    def spread(self) -> float:
        return self.spread_bps / 10000.0


def _mid_from_orderbook(orderbook) -> float | None:
    """
    Compute a mid price from an orderbook.

    - If both sides exist: (bestBid + bestAsk) / 2
    - If only one side exists: that side's best price
    - If empty: None
    """
    best_bid = orderbook.bids[0] if getattr(orderbook, "bids", None) else None
    best_ask = orderbook.asks[0] if getattr(orderbook, "asks", None) else None

    bid = _num_str_to_float(best_bid.price) if best_bid else None
    ask = _num_str_to_float(best_ask.price) if best_ask else None

    if bid is None and ask is None:
        return None
    if bid is None:
        return _clamp_price(float(ask))
    if ask is None:
        return _clamp_price(float(bid))
    return _clamp_price((float(bid) + float(ask)) / 2.0)


def _get_mid_yes(
    client: LumeClient,
    cfg: BotConfig,
) -> float:
    """
    Prefer deriving mid from the live orderbook (YES first, else NO),
    and only fall back to MID_PRICE if the orderbook is empty.
    """
    try:
        yes_ob = client.get_orderbook(cfg.market_id, "YES")
        mid_yes = _mid_from_orderbook(yes_ob)
        if mid_yes is not None:
            return mid_yes
    except (GraphQLError, RuntimeError, ValueError):
        pass

    try:
        no_ob = client.get_orderbook(cfg.market_id, "NO")
        mid_no = _mid_from_orderbook(no_ob)
        if mid_no is not None:
            return _clamp_price(1.0 - mid_no)
    except (GraphQLError, RuntimeError, ValueError):
        pass

    return cfg.mid_price


@dataclass
class PendingFill:
    shares: float = 0.0
    notional: float = 0.0  # sum(price * shares) in YES/NO price units

    def add(self, shares: float, price: float) -> None:
        if shares <= 0:
            return
        self.shares += shares
        self.notional += price * shares

    @property
    def avg_price(self) -> float:
        if self.shares <= 0:
            return 0.0
        return self.notional / self.shares

    def _round_down_2(self, x: float) -> float:
        # AmountCalculator rounds sizes down to 2 decimals; mirror that here.
        return int(x * 100.0) / 100.0

    def size_ready_to_place(self, min_size: float) -> float:
        """
        Returns the largest size we can place now (rounded down to 2 decimals)
        while satisfying the minimum size requirement.
        """
        size = self._round_down_2(self.shares)
        return size if size >= min_size else 0.0

    def consume(self, size: float) -> None:
        """
        Remove `size` shares from the pending buffer, preserving avg price for the remainder.
        """
        if size <= 0 or self.shares <= 0:
            return
        if size >= self.shares:
            self.shares = 0.0
            self.notional = 0.0
            return
        frac = size / self.shares
        self.shares -= size
        self.notional -= self.notional * frac



def _load_config() -> BotConfig:
    # Load .env from repo root (one level above examples/)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(repo_root, ".env"), override=False)

    private_key = os.getenv("PRIVATE_KEY", "").strip()
    market_id = os.getenv("MARKET_ID", "").strip()
    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable is required")
    if not market_id:
        raise ValueError("MARKET_ID environment variable is required")

    # Prefer new env-based config; keep API_URL as a backward-compatible alias.
    api_url = os.getenv("LUME_API_URL") or os.getenv("API_URL")
    api_url = api_url.strip() if api_url else None

    mid_price = float(os.getenv("MID_PRICE", "0.50"))
    spread_bps = int(os.getenv("SPREAD_BPS", "100"))
    num_levels = int(os.getenv("NUM_LEVELS", "20"))
    total_capital_yes = float(os.getenv("TOTAL_CAPITAL", "5000.0"))
    total_capital_no = float(os.getenv("TOTAL_CAPITAL_NO", str(total_capital_yes)))
    orderbook_poll_secs = float(os.getenv("ORDERBOOK_POLL_SECS", "5"))

    return BotConfig(
        private_key=private_key,
        market_id=market_id,
        api_url=api_url,
        mid_price=_clamp_price(mid_price),
        spread_bps=spread_bps,
        num_levels=num_levels,
        total_capital_yes=total_capital_yes,
        total_capital_no=total_capital_no,
        orderbook_poll_secs=orderbook_poll_secs,
    )


def _generate_buy_ladders(
    *,
    mid_price: float,
    spread_bps: int,
    num_levels: int,
    total_capital_yes: float,
    total_capital_no: float,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """
    Generate two-sided ladders as BUYs only:
    - Bid side: BUY YES @ p
    - Ask-equivalent: BUY NO @ (1 - p_ask)
    """
    spread = spread_bps / 10000.0
    half_spread = spread / 2.0

    best_bid = _clamp_price(mid_price - half_spread)
    best_ask = _clamp_price(mid_price + half_spread)

    bid_prices: list[float] = []
    ask_prices: list[float] = []
    for i in range(num_levels):
        bid_prices.append(_clamp_price(best_bid - i * spread))
        ask_prices.append(_clamp_price(best_ask + i * spread))

    total_weight = sum(i + 1 for i in range(num_levels)) or 1

    yes_orders: list[tuple[float, float]] = []
    if total_capital_yes > 0:
        for i, p in enumerate(bid_prices):
            weight = (i + 1) / total_weight
            capital = total_capital_yes * weight
            size = capital / p
            yes_orders.append((p, size))

    no_orders: list[tuple[float, float]] = []
    if total_capital_no > 0:
        for i, p_ask in enumerate(ask_prices):
            p_no = _clamp_price(1.0 - p_ask)
            weight = (i + 1) / total_weight
            capital = total_capital_no * weight
            size = capital / p_no
            no_orders.append((p_no, size))

    return yes_orders, no_orders


def _populate_if_empty(client: LumeClient, cfg: BotConfig) -> None:
    market = client.get_market(cfg.market_id)
    outcome_id_to_label = {o.id: o.label.upper() for o in market.outcomes}
    print(f"Market: {cfg.market_id}")
    print(f"Outcomes: {', '.join(sorted(set(outcome_id_to_label.values())))}")

    open_orders = client.list_user_orders_for_market(
        address=client.eoa_address, market_id=cfg.market_id, status="OPEN", first=100
    )
    open_orders = [o for o in open_orders if o.market_id == cfg.market_id]

    if open_orders:
        print(f"Open orders: {len(open_orders)} (skipping populate)")
        return

    mid_yes = _get_mid_yes(client, cfg)
    mid_no = _clamp_price(1.0 - mid_yes)
    source = "orderbook" if mid_yes != cfg.mid_price else "MID_PRICE (empty book)"
    print(
        f"No OPEN orders found; populating two-sided BUY ladders (mid YES={mid_yes:.4f}, mid NO={mid_no:.4f}, source={source})..."
    )
    yes_orders, no_orders = _generate_buy_ladders(
        mid_price=mid_yes,
        spread_bps=cfg.spread_bps,
        num_levels=cfg.num_levels,
        total_capital_yes=cfg.total_capital_yes,
        total_capital_no=cfg.total_capital_no,
    )

    placed = 0
    for p, sz in yes_orders:
        if sz < MIN_ORDER_SIZE_SHARES:
            print(f"Skipping BUY YES @ {p:.4f} x {sz:.2f} (< {MIN_ORDER_SIZE_SHARES} min)")
            continue
        resp = client.create_and_place_order(
            OrderArgs(
                market_id=cfg.market_id,
                side=OrderSide.BUY,
                outcome="YES",
                price=p,
                size=sz,
            )
        )
        placed += 1
        print(f"Placed BUY YES @ {p:.4f} x {sz:.2f} (id={resp['id']})")

    for p, sz in no_orders:
        if sz < MIN_ORDER_SIZE_SHARES:
            print(f"Skipping BUY NO  @ {p:.4f} x {sz:.2f} (< {MIN_ORDER_SIZE_SHARES} min)")
            continue
        resp = client.create_and_place_order(
            OrderArgs(
                market_id=cfg.market_id,
                side=OrderSide.BUY,
                outcome="NO",
                price=p,
                size=sz,
            )
        )
        placed += 1
        print(f"Placed BUY NO  @ {p:.4f} x {sz:.2f} (id={resp['id']})")

    print(f"Populate complete: placed {placed} orders")


async def _poll_orderbooks(client: LumeClient, cfg: BotConfig, shutdown: asyncio.Event) -> None:
    while not shutdown.is_set():
        try:
            yes_ob = await asyncio.to_thread(client.get_orderbook, cfg.market_id, "YES")
            no_ob = await asyncio.to_thread(client.get_orderbook, cfg.market_id, "NO")

            def top(ob):
                best_bid = ob.bids[0] if ob.bids else None
                best_ask = ob.asks[0] if ob.asks else None
                return best_bid, best_ask

            yb, ya = top(yes_ob)
            nb, na = top(no_ob)

            def fmt(level):
                if not level:
                    return "—"
                return f"{_num_str_to_float(level.price):.4f} x {_num_str_to_float(level.shares):.2f}"

            print(
                f"[OB] YES bid/ask: {fmt(yb)} / {fmt(ya)} | NO bid/ask: {fmt(nb)} / {fmt(na)}"
            )
        except (GraphQLError, RuntimeError, ValueError) as e:
            print(f"[OB] poll error: {e}")

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=cfg.orderbook_poll_secs)
        except asyncio.TimeoutError:
            pass


async def _hedge_on_fills(client: LumeClient, cfg: BotConfig, shutdown: asyncio.Event) -> None:
    bot_started_at = datetime.now(timezone.utc)
    market = await asyncio.to_thread(client.get_market, cfg.market_id)
    outcome_id_to_label = {o.id: o.label.upper() for o in market.outcomes}

    hedge_order_ids: set[str] = set()
    last_filled_by_order_id: dict[str, float] = {}
    pending_by_outcome: dict[str, PendingFill] = {"YES": PendingFill(), "NO": PendingFill()}

    async def _seed_last_filled_baseline() -> None:
        """
        Seed last filled from OPEN/PARTIALLY_FILLED orders so the first UPDATE
        after (re)connect doesn't treat filledShares as a full delta.
        """
        try:
            seeded: list = []
            for status in ("OPEN", "PARTIALLY_FILLED"):
                seeded.extend(
                    await asyncio.to_thread(
                        client.list_user_orders_for_market,
                        client.eoa_address,
                        cfg.market_id,
                        status,
                        100,
                    )
                )
            for o in seeded:
                last_filled_by_order_id[o.id] = _num_str_to_float(o.filled_shares)
        except (GraphQLError, RuntimeError, ValueError) as e:
            print(f"[WS] baseline seed failed: {e}")

    async def _handle_update(update) -> None:
        if update.type != "UPDATE":
            return

        order = update.order
        if order.market_id != cfg.market_id:
            return

        if order.id in hedge_order_ids:
            # We still track filled progress to prevent unbounded deltas if we ever stop ignoring.
            last_filled_by_order_id[order.id] = _num_str_to_float(order.filled_shares)
            return

        if order.side.upper() != "BUY":
            return

        outcome_label = outcome_id_to_label.get(order.outcome_id, "")
        if outcome_label not in ("YES", "NO"):
            return

        filled = _num_str_to_float(order.filled_shares)
        if order.id not in last_filled_by_order_id:
            # Avoid over-hedging on restart: if this order existed before we started and
            # already has filled shares, treat the first update as baseline only.
            created_at = _parse_iso_z(order.created_at)
            if filled > 0 and created_at is not None and created_at < bot_started_at:
                last_filled_by_order_id[order.id] = filled
                print(
                    f"[BASELINE] {order.id[:8]}... {outcome_label} filled={filled:.2f} createdAt={order.created_at} (pre-start; no hedge)"
                )
                return
            # Otherwise initialize baseline at 0.0 so any fill we see is hedged.
            last_filled_by_order_id[order.id] = 0.0

        prev = last_filled_by_order_id.get(order.id, 0.0)
        delta = filled - prev
        last_filled_by_order_id[order.id] = filled

        if delta <= 0:
            return

        p = _num_str_to_float(order.price)
        hedge_outcome = "NO" if outcome_label == "YES" else "YES"

        # Track pending shares + avg fill price until we can place >= MIN_ORDER_SIZE_SHARES
        pending = pending_by_outcome[outcome_label]
        pending.add(delta, p)

        print(
            f"[FILL] {order.id[:8]}... {outcome_label} deltaFilled={delta:.2f} @ {p:.4f} | pending={pending.shares:.2f} avg={pending.avg_price:.4f}"
        )

        size = pending.size_ready_to_place(MIN_ORDER_SIZE_SHARES)
        if size <= 0:
            return

        # Determine live mid for hedge outcome; only fall back to MID_PRICE when book is empty
        try:
            hedge_ob = await asyncio.to_thread(
                client.get_orderbook, cfg.market_id, hedge_outcome
            )
            hedge_mid = _mid_from_orderbook(hedge_ob)
        except (GraphQLError, RuntimeError, ValueError):
            hedge_mid = None

        if hedge_mid is None:
            # empty book fallback
            mid_yes = cfg.mid_price
            hedge_mid = mid_yes if hedge_outcome == "YES" else _clamp_price(1.0 - mid_yes)

        # Hedge pricing: derived from avg fill price, but never bid more aggressively than mid
        target = _clamp_price((1.0 - pending.avg_price) - cfg.spread)
        hedge_price = min(target, hedge_mid)

        print(
            f"[HEDGE] placing BUY {hedge_outcome} size={size:.2f} @ {hedge_price:.4f} (target={target:.4f}, mid={hedge_mid:.4f})"
        )

        try:
            resp = await asyncio.to_thread(
                client.create_and_place_order,
                OrderArgs(
                    market_id=cfg.market_id,
                    side=OrderSide.BUY,
                    outcome=hedge_outcome,
                    price=hedge_price,
                    size=size,
                ),
            )
            hedge_id = resp["id"]
            hedge_order_ids.add(hedge_id)
            pending.consume(size)
            print(f"[HEDGE] placed id={hedge_id}")
        except (GraphQLError, RuntimeError, ValueError, KeyError) as e:
            # Keep pending so we can retry on the next fill event.
            print(f"[HEDGE] failed (pending retained): {e}")

    backoff = 1.0
    max_backoff = 30.0
    while not shutdown.is_set():
        try:
            await _seed_last_filled_baseline()
            print("[WS] subscribing to myOrderUpdates...")
            async for update in client.subscribe_to_order_updates():
                if shutdown.is_set():
                    break
                await _handle_update(update)

            if shutdown.is_set():
                break
            # If the iterator ends without an exception, treat it as a disconnect.
            raise WebSocketError("Subscription ended")

        except (WebSocketError, GraphQLError, OSError) as e:
            if shutdown.is_set():
                break
            print(f"[WS] disconnected: {e}. Reconnecting in {backoff:.1f}s...")
            try:
                await client.close_websocket()
            except (WebSocketError, GraphQLError, OSError, RuntimeError, ValueError):
                pass
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(max_backoff, backoff * 2.0)

        else:
            backoff = 1.0


async def main() -> None:
    cfg = _load_config()
    client = LumeClient(private_key=cfg.private_key, api_url=cfg.api_url or None)

    print("Lume Market Maker - Hedged Ladder Bot")
    print(f"EOA Address: {client.eoa_address}")
    print(f"Proxy Wallet: {client.proxy_wallet}")
    print(
        f"Config: MID_PRICE={cfg.mid_price:.4f} SPREAD_BPS={cfg.spread_bps} NUM_LEVELS={cfg.num_levels} "
        f"TOTAL_CAPITAL={cfg.total_capital_yes:.2f} TOTAL_CAPITAL_NO={cfg.total_capital_no:.2f} "
        f"ORDERBOOK_POLL_SECS={cfg.orderbook_poll_secs}"
    )

    _populate_if_empty(client, cfg)

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        shutdown.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Fallback for environments without signal support
            pass

    poll_task = asyncio.create_task(_poll_orderbooks(client, cfg, shutdown))
    hedge_task = asyncio.create_task(_hedge_on_fills(client, cfg, shutdown))

    try:
        await shutdown.wait()
    finally:
        poll_task.cancel()
        hedge_task.cancel()
        await client.close_websocket()


if __name__ == "__main__":
    asyncio.run(main())

