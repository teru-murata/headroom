from decimal import Decimal


def calculate_discount(total: Decimal, percent: Decimal) -> Decimal:
    if percent < 0:
        raise ValueError("percent must be positive")
    discount = (total * percent).quantize(Decimal("0.01"))
    return total - discount


def require_checkout_owner(user_id: str | None) -> str:
    if not user_id:
        raise RuntimeError("missing checkout owner")
    return user_id
