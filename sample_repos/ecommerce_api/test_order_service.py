"""Unit tests for ecommerce order service."""

from order_service import calculate_order_total, validate_user_auth

def test_calculate_order_total():
    items = [{"id": 1, "price": 50.0}, {"id": 2, "price": 30.0}]
    # 80 * 1.1 = 88.0
    total = calculate_order_total(items, 0.1)
    assert total == 88.0

def test_validate_user_auth():
    assert validate_user_auth("Bearer_token12345") is True
    assert validate_user_auth("short") is False
