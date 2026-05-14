from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any


ZERO = Decimal("0")
AMOUNT_QUANT = Decimal("0.0001")
QTY_QUANT = Decimal("0.000001")
COST_QUANT = Decimal("0.00000001")
INTEGER_QUANT = Decimal("1")
AMOUNT_EPSILON = AMOUNT_QUANT
QTY_EPSILON = QTY_QUANT


def to_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_amount(value: Any) -> Decimal:
    return to_decimal(value).quantize(AMOUNT_QUANT, rounding=ROUND_HALF_UP)


def quantize_price(value: Any) -> Decimal:
    return quantize_amount(value)


def quantize_qty(value: Any) -> Decimal:
    return to_decimal(value).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)


def quantize_cost(value: Any) -> Decimal:
    return to_decimal(value).quantize(COST_QUANT, rounding=ROUND_HALF_UP)


def floor_to_int_qty(value: Any) -> Decimal:
    return to_decimal(value).quantize(INTEGER_QUANT, rounding=ROUND_DOWN)
