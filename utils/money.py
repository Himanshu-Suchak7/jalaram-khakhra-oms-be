from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


_MONEY_QUANT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """
    Quantize to 2 decimal places using ROUND_HALF_UP for consistent monetary math.
    """
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)

