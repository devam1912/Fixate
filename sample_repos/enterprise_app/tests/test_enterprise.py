"""Comprehensive Pytest Unit Test Suite for Enterprise App (5 Intentional Bugs)."""

import pytest
from enterprise_app.auth.verifier import TokenVerifier
from enterprise_app.billing.calculator import PricingCalculator, LineItem
from enterprise_app.inventory.manager import InventoryManager, StockItem
from enterprise_app.analytics.aggregator import AnalyticsAggregator
from enterprise_app.notifications.dispatcher import NotificationDispatcher, NotificationMessage


def test_auth_bearer_token_verification():
    """Test Bug 1: Verify token verification accepts standard enterprise bearer tokens."""
    verifier = TokenVerifier()
    token = verifier.create_token(user_id="usr_100", username="john_doe", roles=["admin"])
    assert token.startswith("Bearer_")
    # Should pass verification cleanly
    assert verifier.verify_bearer_token(token) is True


def test_billing_tiered_discount_calculation():
    """Test Bug 2: Verify volume discount calculation returns correct dollar discount amount."""
    calc = PricingCalculator()
    # 100 items @ $10.00 each = $1,000 gross subtotal. 20% discount should be $200.00 discount!
    discount = calc.calculate_tiered_discount(total_quantity=100, subtotal=1000.0)
    assert discount == 200.0


def test_inventory_check_availability_missing_sku():
    """Test Bug 3: Verify checking stock availability for non-existent SKU returns False without crashing."""
    inv = InventoryManager()
    inv.add_stock_item(StockItem(sku="SKU_100", name="Widget A", available_qty=50))
    # Checking non-existent SKU should safely return False instead of raising AttributeError!
    assert inv.check_availability("SKU_999_NON_EXISTENT", requested_qty=5) is False


def test_analytics_moving_average_calculation():
    """Test Bug 4: Verify moving average calculation includes all recent values in window."""
    agg = AnalyticsAggregator()
    agg.record_metric("cpu_load", 10.0, timestamp=1.0)
    agg.record_metric("cpu_load", 20.0, timestamp=2.0)
    agg.record_metric("cpu_load", 30.0, timestamp=3.0)
    # Moving average of [10.0, 20.0, 30.0] should equal (10 + 20 + 30) / 3 = 20.0
    avg = agg.calculate_moving_average("cpu_load", window_size=3)
    assert avg == 20.0


def test_notifications_format_header_priority():
    """Test Bug 5: Verify formatting notification header handles missing priority metadata gracefully."""
    dispatcher = NotificationDispatcher()
    msg = NotificationMessage(
        recipient="user@enterprise.com",
        subject="System Alert",
        body="Server high load alert",
        metadata={"category": "system"}, # Missing 'priority' key!
    )
    # Formatting header should handle missing priority key without raising KeyError!
    header = dispatcher.format_notification_header(msg)
    assert "To: user@enterprise.com" in header
