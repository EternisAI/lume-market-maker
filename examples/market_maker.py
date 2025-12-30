"""Example: Multi-market market maker bot with delta-fill hedging and collateral recycling.

This bot:
- Loads market configs from a JSON file
- For each market:
  - Checks if you already have OPEN orders on that market
  - If not, populates a two-sided book using BUY YES and BUY NO ladders
  - HTTP polling of the YES/NO orderbooks
- Single WebSocket subscription to myOrderUpdates, dispatching to each market
- On fills (delta filledShares), places an opposite-side order
- Periodically checks if outcome tokens can be merged back to collateral

Run:
  PRIVATE_KEY=... MARKETS_CONFIG_PATH=markets.json uv run examples/market_maker.py
"""

import asyncio
import json
import os
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Add parent directory to path for local development (matches other examples)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from lume_market_maker import LumeClient, OrderArgs, OrderSide, WebSocketError
from lume_market_maker.graphql import GraphQLError
from lume_market_maker.types import Market

from safe_executor import SafeExecutor


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


# -----------------------------------------------------------------------------
# Configuration Dataclasses
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketConfig:
    """Per-market config from JSON."""

    market_id: str
    mid_price: float
    total_amount: float


@dataclass(frozen=True)
class SharedConfig:
    """Shared config from env vars."""

    private_key: str
    api_url: str | None
    spread_bps: int
    num_levels: int
    orderbook_poll_secs: float
    # Merge-related
    ctf_address: str | None
    neg_risk_adapter: str | None
    collateral_token: str | None
    rpc_url: str | None
    merge_check_interval_secs: float
    min_merge_amount: float

    @property
    def spread(self) -> float:
        return self.spread_bps / 10000.0


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


@dataclass
class MarketBotState:
    """Per-market runtime state."""

    market_cfg: MarketConfig
    shared_cfg: SharedConfig
    market: Market  # Includes condition_id, outcomes, is_neg_risk
    bot_started_at: datetime
    outcome_id_to_label: dict[str, str] = field(default_factory=dict)
    last_filled_by_order_id: dict[str, float] = field(default_factory=dict)
    pending_by_outcome: dict[str, PendingFill] = field(
        default_factory=lambda: {"YES": PendingFill(), "NO": PendingFill()}
    )


# -----------------------------------------------------------------------------
# Config Loading
# -----------------------------------------------------------------------------


def _load_shared_config() -> SharedConfig:
    """Load shared config from environment variables."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(repo_root, ".env"), override=False)

    private_key = os.getenv("PRIVATE_KEY", "").strip()
    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable is required")

    api_url = os.getenv("LUME_API_URL") or os.getenv("API_URL")
    api_url = api_url.strip() if api_url else None

    spread_bps = int(os.getenv("SPREAD_BPS", "100"))
    num_levels = int(os.getenv("NUM_LEVELS", "20"))
    orderbook_poll_secs = float(os.getenv("ORDERBOOK_POLL_SECS", "5"))

    # Merge-related config
    ctf_address = os.getenv("CTF_ADDRESS", "").strip() or None
    neg_risk_adapter = os.getenv("NEG_RISK_ADAPTER", "").strip() or None
    collateral_token = os.getenv("COLLATERAL_TOKEN", "").strip() or None
    rpc_url = os.getenv("RPC_URL", "").strip() or None
    merge_check_interval_secs = float(os.getenv("MERGE_CHECK_INTERVAL_SECS", "60"))
    min_merge_amount = float(os.getenv("MIN_MERGE_AMOUNT", "5"))

    return SharedConfig(
        private_key=private_key,
        api_url=api_url,
        spread_bps=spread_bps,
        num_levels=num_levels,
        orderbook_poll_secs=orderbook_poll_secs,
        ctf_address=ctf_address,
        neg_risk_adapter=neg_risk_adapter,
        collateral_token=collateral_token,
        rpc_url=rpc_url,
        merge_check_interval_secs=merge_check_interval_secs,
        min_merge_amount=min_merge_amount,
    )


def _load_markets_config() -> list[MarketConfig]:
    """Load market configs from JSON file."""
    config_path = os.getenv("MARKETS_CONFIG_PATH", "").strip()
    if not config_path:
        raise ValueError("MARKETS_CONFIG_PATH environment variable is required")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isabs(config_path):
        config_path = os.path.join(repo_root, config_path)

    with open(config_path) as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Markets config must be a JSON array")

    markets = []
    for item in data:
        markets.append(
            MarketConfig(
                market_id=item["market_id"],
                mid_price=_clamp_price(float(item["mid_price"])),
                total_amount=float(item["total_amount"]),
            )
        )

    if not markets:
        raise ValueError("Markets config must have at least one market")

    return markets


# -----------------------------------------------------------------------------
# Orderbook Helpers
# -----------------------------------------------------------------------------


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


def _get_mid_yes(client: LumeClient, state: MarketBotState) -> float:
    """
    Prefer deriving mid from the live orderbook (YES first, else NO),
    and only fall back to MID_PRICE if the orderbook is empty.
    """
    market_id = state.market_cfg.market_id
    mid_price = state.market_cfg.mid_price

    try:
        yes_ob = client.get_orderbook(market_id, "YES")
        mid_yes = _mid_from_orderbook(yes_ob)
        if mid_yes is not None:
            return mid_yes
    except (GraphQLError, RuntimeError, ValueError):
        pass

    try:
        no_ob = client.get_orderbook(market_id, "NO")
        mid_no = _mid_from_orderbook(no_ob)
        if mid_no is not None:
            return _clamp_price(1.0 - mid_no)
    except (GraphQLError, RuntimeError, ValueError):
        pass

    return mid_price


# -----------------------------------------------------------------------------
# Order Generation
# -----------------------------------------------------------------------------


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


# -----------------------------------------------------------------------------
# Population
# -----------------------------------------------------------------------------


def _populate_if_empty(client: LumeClient, state: MarketBotState) -> None:
    """Populate orders for a market if none exist."""
    market_id = state.market_cfg.market_id
    market = state.market
    shared_cfg = state.shared_cfg

    print(f"[{market_id[:8]}] Market: {market_id}")
    print(f"[{market_id[:8]}] ConditionId: {market.condition_id}")
    print(f"[{market_id[:8]}] Outcomes: {', '.join(sorted(state.outcome_id_to_label.values()))}")

    open_orders = client.list_user_orders_for_market(
        address=client.eoa_address, market_id=market_id, status="OPEN", first=100
    )
    open_orders = [o for o in open_orders if o.market_id == market_id]

    if open_orders:
        print(f"[{market_id[:8]}] Open orders: {len(open_orders)} (skipping populate)")
        return

    mid_yes = _get_mid_yes(client, state)
    mid_no = _clamp_price(1.0 - mid_yes)
    source = "orderbook" if mid_yes != state.market_cfg.mid_price else "MID_PRICE (empty book)"
    print(
        f"[{market_id[:8]}] No OPEN orders; populating (mid YES={mid_yes:.4f}, mid NO={mid_no:.4f}, source={source})..."
    )

    # Split total_amount equally between YES and NO
    total_capital = state.market_cfg.total_amount / 2.0

    yes_orders, no_orders = _generate_buy_ladders(
        mid_price=mid_yes,
        spread_bps=shared_cfg.spread_bps,
        num_levels=shared_cfg.num_levels,
        total_capital_yes=total_capital,
        total_capital_no=total_capital,
    )

    placed = 0
    for p, sz in yes_orders:
        if sz < MIN_ORDER_SIZE_SHARES:
            continue
        resp = client.create_and_place_order(
            OrderArgs(
                market_id=market_id,
                side=OrderSide.BUY,
                outcome="YES",
                price=p,
                size=sz,
            )
        )
        placed += 1
        print(f"[{market_id[:8]}] Placed BUY YES @ {p:.4f} x {sz:.2f} (id={resp['id']})")

    for p, sz in no_orders:
        if sz < MIN_ORDER_SIZE_SHARES:
            continue
        resp = client.create_and_place_order(
            OrderArgs(
                market_id=market_id,
                side=OrderSide.BUY,
                outcome="NO",
                price=p,
                size=sz,
            )
        )
        placed += 1
        print(f"[{market_id[:8]}] Placed BUY NO  @ {p:.4f} x {sz:.2f} (id={resp['id']})")

    print(f"[{market_id[:8]}] Populate complete: placed {placed} orders")


# -----------------------------------------------------------------------------
# Orderbook Polling (per market)
# -----------------------------------------------------------------------------


async def _poll_orderbooks(
    client: LumeClient, state: MarketBotState, shutdown: asyncio.Event
) -> None:
    """Poll orderbooks for a single market."""
    market_id = state.market_cfg.market_id
    poll_secs = state.shared_cfg.orderbook_poll_secs

    while not shutdown.is_set():
        try:
            yes_ob = await asyncio.to_thread(client.get_orderbook, market_id, "YES")
            no_ob = await asyncio.to_thread(client.get_orderbook, market_id, "NO")

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
                f"[{market_id[:8]}] [OB] YES: {fmt(yb)} / {fmt(ya)} | NO: {fmt(nb)} / {fmt(na)}"
            )
        except (GraphQLError, RuntimeError, ValueError) as e:
            print(f"[{market_id[:8]}] [OB] poll error: {e}")

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=poll_secs)
        except asyncio.TimeoutError:
            pass


# -----------------------------------------------------------------------------
# Fill Handling (all markets via single WS)
# -----------------------------------------------------------------------------


async def _handle_all_markets_fills(
    client: LumeClient,
    states: list[MarketBotState],
    shutdown: asyncio.Event,
) -> None:
    """Single WebSocket subscription that dispatches fills to appropriate market state."""

    # Build lookup by market_id
    state_by_market_id: dict[str, MarketBotState] = {
        s.market_cfg.market_id: s for s in states
    }

    async def _seed_all_baselines() -> None:
        """Seed last filled for all markets."""
        for state in states:
            market_id = state.market_cfg.market_id
            try:
                seeded: list = []
                for status in ("OPEN", "PARTIALLY_FILLED"):
                    seeded.extend(
                        await asyncio.to_thread(
                            client.list_user_orders_for_market,
                            client.eoa_address,
                            market_id,
                            status,
                            100,
                        )
                    )
                for o in seeded:
                    state.last_filled_by_order_id[o.id] = _num_str_to_float(o.filled_shares)
            except (GraphQLError, RuntimeError, ValueError) as e:
                print(f"[{market_id[:8]}] [WS] baseline seed failed: {e}")

    async def _handle_update(update) -> None:
        if update.type != "UPDATE":
            return

        order = update.order

        # Find the appropriate market state
        state = state_by_market_id.get(order.market_id)
        if state is None:
            return  # Not one of our markets

        if order.side.upper() != "BUY":
            return

        market_id = state.market_cfg.market_id
        outcome_label = state.outcome_id_to_label.get(order.outcome_id, "")
        if outcome_label not in ("YES", "NO"):
            return

        filled = _num_str_to_float(order.filled_shares)
        if order.id not in state.last_filled_by_order_id:
            # Avoid over-hedging on restart
            created_at = _parse_iso_z(order.created_at)
            if filled > 0 and created_at is not None and created_at < state.bot_started_at:
                state.last_filled_by_order_id[order.id] = filled
                print(
                    f"[{market_id[:8]}] [BASELINE] {order.id[:8]}... {outcome_label} filled={filled:.2f} (pre-start)"
                )
                return
            state.last_filled_by_order_id[order.id] = 0.0

        prev = state.last_filled_by_order_id.get(order.id, 0.0)
        delta = filled - prev
        state.last_filled_by_order_id[order.id] = filled

        if delta <= 0:
            return

        p = _num_str_to_float(order.price)
        hedge_outcome = "NO" if outcome_label == "YES" else "YES"

        pending = state.pending_by_outcome[outcome_label]
        pending.add(delta, p)

        print(
            f"[{market_id[:8]}] [FILL] {order.id[:8]}... {outcome_label} delta={delta:.2f} @ {p:.4f} | pending={pending.shares:.2f}"
        )

        size = pending.size_ready_to_place(MIN_ORDER_SIZE_SHARES)
        if size <= 0:
            return

        # Determine live mid for hedge outcome
        try:
            hedge_ob = await asyncio.to_thread(
                client.get_orderbook, market_id, hedge_outcome
            )
            hedge_mid = _mid_from_orderbook(hedge_ob)
        except (GraphQLError, RuntimeError, ValueError):
            hedge_mid = None

        if hedge_mid is None:
            mid_yes = state.market_cfg.mid_price
            hedge_mid = mid_yes if hedge_outcome == "YES" else _clamp_price(1.0 - mid_yes)

        target = _clamp_price((1.0 - pending.avg_price) - state.shared_cfg.spread)
        hedge_price = min(target, hedge_mid)

        print(
            f"[{market_id[:8]}] [HEDGE] placing BUY {hedge_outcome} size={size:.2f} @ {hedge_price:.4f}"
        )

        try:
            resp = await asyncio.to_thread(
                client.create_and_place_order,
                OrderArgs(
                    market_id=market_id,
                    side=OrderSide.BUY,
                    outcome=hedge_outcome,
                    price=hedge_price,
                    size=size,
                ),
            )
            pending.consume(size)
            print(f"[{market_id[:8]}] [HEDGE] placed id={resp['id']}")
        except (GraphQLError, RuntimeError, ValueError, KeyError) as e:
            print(f"[{market_id[:8]}] [HEDGE] failed: {e}")

    backoff = 1.0
    max_backoff = 30.0
    while not shutdown.is_set():
        try:
            await _seed_all_baselines()
            print("[WS] subscribing to myOrderUpdates for all markets...")
            async for update in client.subscribe_to_order_updates():
                if shutdown.is_set():
                    break
                await _handle_update(update)

            if shutdown.is_set():
                break
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


# -----------------------------------------------------------------------------
# Collateral Merge Task
# -----------------------------------------------------------------------------


async def _merge_collateral_task(
    client: LumeClient,
    states: list[MarketBotState],
    safe_executor: SafeExecutor | None,
    shutdown: asyncio.Event,
) -> None:
    """Periodically check and merge outcome tokens to recycle collateral."""

    if safe_executor is None:
        print("[MERGE] SafeExecutor not configured, merge task disabled")
        return

    shared_cfg = states[0].shared_cfg if states else None
    if not shared_cfg or not shared_cfg.ctf_address:
        print("[MERGE] CTF_ADDRESS not configured, merge task disabled")
        return

    check_interval = shared_cfg.merge_check_interval_secs
    min_merge_amount = shared_cfg.min_merge_amount

    while not shutdown.is_set():
        for state in states:
            market_id = state.market_cfg.market_id
            try:
                # Get YES and NO token_ids from outcomes
                outcomes_by_label = {o.label.upper(): o for o in state.market.outcomes}
                if "YES" not in outcomes_by_label or "NO" not in outcomes_by_label:
                    continue

                yes_token_id = int(outcomes_by_label["YES"].token_id)
                no_token_id = int(outcomes_by_label["NO"].token_id)

                # Query balances from CTF contract
                balances = await asyncio.to_thread(
                    safe_executor.get_token_balances,
                    shared_cfg.ctf_address,
                    client.proxy_wallet,
                    [yes_token_id, no_token_id],
                )
                yes_balance, no_balance = balances

                # Scale from atomic (1e6) to shares
                yes_shares = yes_balance / 1_000_000
                no_shares = no_balance / 1_000_000
                min_shares = min(yes_shares, no_shares)

                if min_shares >= min_merge_amount:
                    merge_amount = int(min_shares) * 1_000_000  # Back to atomic

                    condition_id = state.market.condition_id
                    if not condition_id:
                        print(f"[{market_id[:8]}] [MERGE] no condition_id, skipping")
                        continue

                    if state.market.is_neg_risk:
                        if not shared_cfg.neg_risk_adapter:
                            print(f"[{market_id[:8]}] [MERGE] NEG_RISK_ADAPTER not configured")
                            continue
                        tx_hash = await asyncio.to_thread(
                            safe_executor.execute_merge_neg_risk,
                            shared_cfg.neg_risk_adapter,
                            condition_id,
                            merge_amount,
                        )
                    else:
                        if not shared_cfg.collateral_token:
                            print(f"[{market_id[:8]}] [MERGE] COLLATERAL_TOKEN not configured")
                            continue
                        tx_hash = await asyncio.to_thread(
                            safe_executor.execute_merge_ctf,
                            shared_cfg.ctf_address,
                            shared_cfg.collateral_token,
                            condition_id,
                            merge_amount,
                        )
                    print(
                        f"[{market_id[:8]}] [MERGE] merged {int(min_shares)} shares, tx: {tx_hash}"
                    )

            except Exception as e:
                print(f"[{market_id[:8]}] [MERGE] error: {e}")

        # Wait for next check
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=check_interval)
        except asyncio.TimeoutError:
            pass


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


async def main() -> None:
    # Load configurations
    shared_cfg = _load_shared_config()
    market_configs = _load_markets_config()

    # Create shared client
    client = LumeClient(private_key=shared_cfg.private_key, api_url=shared_cfg.api_url or None)

    print("Lume Multi-Market Maker - Hedged Ladder Bot")
    print(f"EOA Address: {client.eoa_address}")
    print(f"Proxy Wallet: {client.proxy_wallet}")
    print(f"Markets: {len(market_configs)}")
    print(
        f"Config: SPREAD_BPS={shared_cfg.spread_bps} NUM_LEVELS={shared_cfg.num_levels} "
        f"ORDERBOOK_POLL_SECS={shared_cfg.orderbook_poll_secs}"
    )

    # Initialize SafeExecutor if configured
    safe_executor: SafeExecutor | None = None
    if shared_cfg.rpc_url and shared_cfg.ctf_address:
        try:
            safe_executor = SafeExecutor(
                private_key=shared_cfg.private_key,
                safe_address=client.proxy_wallet,
                rpc_url=shared_cfg.rpc_url,
            )
            print(f"SafeExecutor initialized for merge operations")
        except Exception as e:
            print(f"SafeExecutor initialization failed: {e}")

    # Create per-market states
    states: list[MarketBotState] = []
    for market_cfg in market_configs:
        print(f"\nInitializing market: {market_cfg.market_id}")
        market = client.get_market(market_cfg.market_id)
        outcome_id_to_label = {o.id: o.label.upper() for o in market.outcomes}

        state = MarketBotState(
            market_cfg=market_cfg,
            shared_cfg=shared_cfg,
            market=market,
            bot_started_at=datetime.now(timezone.utc),
            outcome_id_to_label=outcome_id_to_label,
        )
        states.append(state)

        # Populate orders if empty
        _populate_if_empty(client, state)

    print(f"\nStarting market maker for {len(states)} markets...")

    # Setup shutdown
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        print("\nShutdown signal received...")
        shutdown.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    # Create tasks
    tasks: list[asyncio.Task] = []

    # Per-market orderbook polling
    for state in states:
        task = asyncio.create_task(_poll_orderbooks(client, state, shutdown))
        tasks.append(task)

    # Single WS subscription for all markets
    hedge_task = asyncio.create_task(_handle_all_markets_fills(client, states, shutdown))
    tasks.append(hedge_task)

    # Merge task
    merge_task = asyncio.create_task(_merge_collateral_task(client, states, safe_executor, shutdown))
    tasks.append(merge_task)

    try:
        await shutdown.wait()
    finally:
        for task in tasks:
            task.cancel()
        await client.close_websocket()
        print("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
