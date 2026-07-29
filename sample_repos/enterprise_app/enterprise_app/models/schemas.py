"""Enterprise Data Schemas & Payload Validation Models (300+ lines)."""

import re
import time
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class UserAccountSchema:
    user_id: str
    email: str
    first_name: str
    last_name: str
    roles: List[str]
    is_active: bool = True
    created_at: float = field(default_factory=time.time)

    def validate(self) -> bool:
        """Validate user account email format and fields."""
        if not self.user_id or not self.email:
            return False
        pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        return bool(re.match(pattern, self.email))


@dataclass
class ProductSKUSchema:
    sku: str
    name: str
    description: str
    unit_price: float
    category: str
    attributes: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> bool:
        """Validate SKU code and unit price."""
        if not self.sku or self.unit_price < 0.0:
            return False
        return len(self.sku) >= 3


@dataclass
class OrderHeaderSchema:
    order_id: str
    customer_id: str
    order_date: float
    shipping_address: Dict[str, str]
    billing_address: Dict[str, str]
    line_items: List[Dict[str, Any]]
    total_amount: float
    status: str = "pending"

    def validate(self) -> bool:
        """Validate order line items and customer ID."""
        if not self.order_id or not self.customer_id or not self.line_items:
            return False
        return self.total_amount >= 0.0
