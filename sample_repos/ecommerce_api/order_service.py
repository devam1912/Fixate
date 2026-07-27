"""Ecommerce Order Service sample target repo with type and validation bugs."""

def calculate_order_total(items: list, tax_rate: float) -> float:
    """Calculate total price of order items including tax."""
    subtotal = 0.0
    for item in items:
        # Bug: item is a dict, but code attempts to access item.price attribute instead of item["price"]
        subtotal += item.price
    return subtotal * (1.0 + tax_rate)

def validate_user_auth(token: str) -> bool:
    """Validate bearer token."""
    if not token or len(token) < 10:
        return False
    return token.startswith("Bearer_")
