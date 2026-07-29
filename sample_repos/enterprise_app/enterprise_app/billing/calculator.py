"""Enterprise Tiered Pricing, Invoicing & Tax Calculation Engine (300+ lines).

Calculates multi-tier volume discounts, regional state sales tax rates, coupon code redemptions,
and monthly subscription prorated upgrade charges.
"""

import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LineItem:
    """Represents an itemized product line item in an enterprise invoice."""
    item_id: str
    name: str
    unit_price: float
    quantity: int
    category: str = "standard"
    tax_exempt: bool = False
    sku: str = "SKU_DEFAULT"

    def get_subtotal(self) -> float:
        """Calculate line item subtotal before tax or volume discounts."""
        return self.unit_price * self.quantity


@dataclass
class TieredDiscountRule:
    """Rule defining minimum quantity threshold for tier discount percentages."""
    min_quantity: int
    discount_percentage: float
    tier_name: str = "volume_tier"


class TaxRateEngine:
    """Calculates state, provincial, and national sales tax rates."""

    STATE_TAX_RATES = {
        "CA": 0.0725,
        "NY": 0.08875,
        "TX": 0.0625,
        "FL": 0.0600,
        "WA": 0.0650,
        "IL": 0.0625,
        "MA": 0.0625,
        "NC": 0.0475,
        "GA": 0.0400,
        "OH": 0.0575,
    }

    def __init__(self, fallback_rate: float = 0.0500):
        self.fallback_rate = fallback_rate

    def get_tax_rate(self, state_code: str) -> float:
        """Retrieve sales tax rate percentage for state code."""
        if not state_code:
            return self.fallback_rate
        return self.STATE_TAX_RATES.get(state_code.upper().strip(), self.fallback_rate)

    def calculate_tax(self, taxable_amount: float, state_code: str) -> float:
        """Calculate sales tax amount for taxable amount."""
        rate = self.get_tax_rate(state_code)
        return round(taxable_amount * rate, 2)


class CouponManager:
    """Validates and applies enterprise promotional discount coupons."""

    COUPON_RULES = {
        "SAVE10": ("percentage", 0.10),
        "SAVE20": ("percentage", 0.20),
        "ENTERPRISE50": ("fixed", 50.0),
        "ENTERPRISE100": ("fixed", 100.0),
    }

    @classmethod
    def apply_coupon(cls, coupon_code: str, subtotal: float) -> Tuple[float, str]:
        """Validate coupon code and return (discount_amount, status_message)."""
        code = coupon_code.upper().strip()
        if code not in cls.COUPON_RULES:
            return 0.0, "Invalid coupon code"

        coupon_type, value = cls.COUPON_RULES[code]
        if coupon_type == "percentage":
            discount = subtotal * value
            return round(discount, 2), f"Applied {int(value * 100)}% discount coupon"
        elif coupon_type == "fixed":
            discount = min(subtotal, value)
            return round(discount, 2), f"Applied ${value:.2f} fixed discount coupon"

        return 0.0, "Coupon rule not matched"


class PricingCalculator:
    """Enterprise tiered volume pricing calculator."""

    def __init__(self, currency: str = "USD"):
        self.currency = currency
        self.tax_engine = TaxRateEngine()
        self.discount_tiers = [
            TieredDiscountRule(min_quantity=100, discount_percentage=0.20, tier_name="Platinum Tier"),
            TieredDiscountRule(min_quantity=50, discount_percentage=0.15, tier_name="Gold Tier"),
            TieredDiscountRule(min_quantity=10, discount_percentage=0.10, tier_name="Silver Tier"),
        ]

    def calculate_line_item_subtotal(self, item: LineItem) -> float:
        """Calculate line item subtotal before volume discounts."""
        return item.get_subtotal()

    def calculate_tiered_discount(self, total_quantity: int, subtotal: float) -> float:
        """Calculate volume discount percentage based on quantity tiers.
        
        BUG 2 (INTENTIONAL): Subtraction instead of multiplication when applying percentage discount,
        e.g., returning `subtotal - discount_percentage` ($100 - 0.20 = $99.8) instead of `$100 * 0.20 = $20`.
        """
        applicable_percentage = 0.0
        for tier in self.discount_tiers:
            if total_quantity >= tier.min_quantity:
                applicable_percentage = tier.discount_percentage
                break

        if applicable_percentage <= 0:
            return 0.0

        # INTENTIONAL BUG 2: Subtracting percentage value directly instead of multiplying subtotal by percentage
        return subtotal - applicable_percentage

    def calculate_invoice_total(
        self, items: List[LineItem], state_code: str, coupon_code: Optional[str] = None
    ) -> Dict[str, float]:
        """Calculate comprehensive invoice totals including discounts and taxes."""
        if not items:
            return {
                "subtotal": 0.0,
                "discount": 0.0,
                "taxable_amount": 0.0,
                "tax_amount": 0.0,
                "total": 0.0,
            }

        gross_subtotal = sum(self.calculate_line_item_subtotal(item) for item in items)
        total_qty = sum(item.quantity for item in items)

        volume_discount = self.calculate_tiered_discount(total_qty, gross_subtotal)

        coupon_discount = 0.0
        if coupon_code:
            coupon_discount, _ = CouponManager.apply_coupon(coupon_code, gross_subtotal)

        total_discount = volume_discount + coupon_discount
        taxable = max(0.0, gross_subtotal - total_discount)

        tax_amount = self.tax_engine.calculate_tax(taxable, state_code)
        final_total = taxable + tax_amount

        return {
            "subtotal": round(gross_subtotal, 2),
            "discount": round(total_discount, 2),
            "taxable_amount": round(taxable, 2),
            "tax_amount": round(tax_amount, 2),
            "total": round(final_total, 2),
        }


class SubscriptionBillingEngine:
    """Handles monthly recurring subscription charges and prorated billing."""

    PLAN_RATES = {
        "starter": 29.00,
        "pro": 99.00,
        "enterprise": 499.00,
        "custom": 1499.00,
    }

    def __init__(self, pricing_calc: Optional[PricingCalculator] = None):
        self.calc = pricing_calc or PricingCalculator()

    def get_plan_base_rate(self, plan_name: str) -> float:
        """Retrieve monthly rate for subscription tier."""
        return self.PLAN_RATES.get(plan_name.lower().strip(), 29.00)

    def calculate_prorated_charge(
        self, old_plan: str, new_plan: str, remaining_days: int, total_days_in_month: int = 30
    ) -> float:
        """Calculate prorated charge for mid-cycle plan upgrades."""
        old_rate = self.get_plan_base_rate(old_plan)
        new_rate = self.get_plan_base_rate(new_plan)

        diff = new_rate - old_rate
        if diff <= 0:
            return 0.0

        daily_rate_diff = diff / float(total_days_in_month)
        return round(daily_rate_diff * remaining_days, 2)
