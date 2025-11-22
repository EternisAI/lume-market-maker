"""Amount calculator for order placement."""

from decimal import Decimal, localcontext, ROUND_FLOOR
from dataclasses import dataclass


@dataclass
class OrderAmounts:
    """Structured output for order amounts"""

    makerAmount: int
    takerAmount: int
    price: Decimal

    def __repr__(self):
        return (
            f"OrderAmounts(makerAmount={self.makerAmount}, "
            f"takerAmount={self.takerAmount}, "
            f"price={self.price})"
        )


class AmountCalculator:
    """Calculates makerAmount, takerAmount, and final price for order placement"""

    TICK_SIZE = Decimal("0.01")
    PRECISION_PRICE = 2
    PRECISION_SIZE = 2
    PRECISION_AMOUNT = 4

    DECIMALS = 6
    ATOMIC_SCALE = Decimal("10") ** DECIMALS

    def _round_down(self, value: Decimal, precision: int) -> Decimal:
        """Floors a Decimal to specific decimal places"""
        with localcontext() as ctx:
            ctx.rounding = ROUND_FLOOR
            quantizer = Decimal("1").scaleb(-precision)
            return value.quantize(quantizer)

    def calculate_amounts(self, side: str, price: float, size: float) -> OrderAmounts:
        """
        Calculates aligned maker/taker amounts in atomic units and final price.

        :param side: "BUY" or "SELL"
        :param price: Limit price in USDC (e.g. 0.55)
        :param size: Number of shares (e.g. 100.0)
        :return: OrderAmounts struct
        """

        d_price = Decimal(str(price))
        d_size = Decimal(str(size))

        aligned_price = self._round_down(d_price, self.PRECISION_PRICE)
        aligned_size = self._round_down(d_size, self.PRECISION_SIZE)

        if aligned_size <= 0:
            raise ValueError(f"Size {size} rounded down to 0.00")
        if aligned_price <= 0:
            raise ValueError(f"Price {price} rounded down to 0.00")

        if side.upper() == "BUY":
            raw_maker_amt = aligned_price * aligned_size
            raw_taker_amt = aligned_size
        elif side.upper() == "SELL":
            raw_maker_amt = aligned_size
            raw_taker_amt = aligned_price * aligned_size
        else:
            raise ValueError("Side must be 'BUY' or 'SELL'")

        usdc_component = raw_maker_amt if side.upper() == "BUY" else raw_taker_amt
        usdc_aligned = self._round_down(usdc_component, self.PRECISION_AMOUNT)

        if side.upper() == "BUY":
            raw_maker_amt = usdc_aligned
        else:
            raw_taker_amt = usdc_aligned

        maker_amount_atomic = int(raw_maker_amt * self.ATOMIC_SCALE)
        taker_amount_atomic = int(raw_taker_amt * self.ATOMIC_SCALE)

        return OrderAmounts(
            makerAmount=maker_amount_atomic,
            takerAmount=taker_amount_atomic,
            price=aligned_price,
        )

