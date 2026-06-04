from decimal import ROUND_HALF_UP, Decimal


class CartLine:
    def __init__(self, unit_price: Decimal, quantity: int) -> None:
        self.unit_price = unit_price
        self.quantity = quantity


def apply_discount(lines: list[CartLine], percentage: Decimal) -> Decimal:
    subtotal = sum((line.unit_price * line.quantity for line in lines), Decimal("0.00"))
    discount = subtotal * percentage
    return discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
