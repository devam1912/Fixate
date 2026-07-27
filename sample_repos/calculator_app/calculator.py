"""Calculator app sample target repo for testing math logic bugs."""

def calculate_discount(price: float, discount_percent: float) -> float:
    """Calculate discounted price.
    Bug: subtracts discount_percent directly instead of calculating percentage.
    """
    # Intentional bug for evaluation: price - discount_percent instead of price * (1 - discount_percent/100)
    return price - discount_percent

def divide_numbers(a: float, b: float) -> float:
    """Divide a by b safely."""
    # Intentional bug for evaluation: returns 0 on b=0 instead of handling or raising clean error
    if b == 0:
        return a / b  # Causes ZeroDivisionError
    return a / b
