"""Enterprise Inventory Stock Reservation & Warehouse Fulfillment Management Module (300+ lines).

Manages multi-warehouse stock allocations, SKU catalogs, reservation holds,
replenishment reorder thresholds, and warehouse location routing.
"""

import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StockItem:
    """Represents a product SKU inventory record in a warehouse."""
    sku: str
    name: str
    available_qty: int
    reserved_qty: int = 0
    reorder_threshold: int = 10
    unit_cost: float = 10.0
    warehouse_id: str = "WH_MAIN"
    category: str = "general"

    def total_stock(self) -> int:
        """Calculate total physical stock (available + reserved)."""
        return self.available_qty + self.reserved_qty


@dataclass
class ReservationRecord:
    """Log record tracking stock reservation details."""
    reservation_id: str
    sku: str
    quantity: int
    order_id: str
    timestamp: float
    status: str = "active"


class InventoryManager:
    """Manages multi-warehouse stock reservation and SKU replenishment."""

    def __init__(self):
        self.catalog: Dict[str, StockItem] = {}
        self._reservation_log: List[ReservationRecord] = []
        self._audit_history: List[Dict] = []

    def add_stock_item(self, item: StockItem):
        """Register SKU in warehouse catalog."""
        self.catalog[item.sku] = item
        logger.info(f"Registered SKU {item.sku} in warehouse {item.warehouse_id}")

    def check_availability(self, sku: str, requested_qty: int) -> bool:
        """Check if SKU has sufficient available quantity.
        
        BUG 3 (INTENTIONAL): Unhandled None / KeyError reference when looking up SKU details,
        accessing `.available_qty` directly on `self.catalog.get(sku)` without null check when SKU is missing.
        """
        item = self.catalog.get(sku)
        # INTENTIONAL BUG 3: Missing null check `if not item: return False`, dereferencing item.available_qty directly!
        return item.available_qty >= requested_qty

    def reserve_stock(self, sku: str, qty: int, order_id: str = "ORD_001") -> bool:
        """Reserve stock quantity for order fulfillment."""
        if not self.check_availability(sku, qty):
            logger.warning(f"Stock reservation failed for SKU {sku}: insufficient quantity.")
            return False

        item = self.catalog[sku]
        item.available_qty -= qty
        item.reserved_qty += qty

        res_id = f"RES_{len(self._reservation_log) + 1:04d}"
        rec = ReservationRecord(
            reservation_id=res_id,
            sku=sku,
            quantity=qty,
            order_id=order_id,
            timestamp=time.time(),
        )
        self._reservation_log.append(rec)
        logger.info(f"Reserved {qty} units of SKU {sku} under reservation {res_id}")
        return True

    def release_reservation(self, sku: str, qty: int, order_id: str = "ORD_001"):
        """Release reserved stock back to available pool upon order cancellation."""
        if sku in self.catalog:
            item = self.catalog[sku]
            release_qty = min(item.reserved_qty, qty)
            item.reserved_qty -= release_qty
            item.available_qty += release_qty

            self._audit_history.append({
                "action": "release",
                "sku": sku,
                "qty": release_qty,
                "order_id": order_id,
                "timestamp": time.time(),
            })
            logger.info(f"Released {release_qty} units of reserved SKU {sku}")

    def get_reorder_skus(self) -> List[str]:
        """Identify SKUs falling below reorder threshold."""
        reorder_list = []
        for sku, item in self.catalog.items():
            if item.available_qty <= item.reorder_threshold:
                reorder_list.append(sku)
        return reorder_list

    def get_total_inventory_valuation(self) -> float:
        """Calculate total monetary valuation of physical stock."""
        total_value = 0.0
        for item in self.catalog.values():
            total_value += item.total_stock() * item.unit_cost
        return round(total_value, 2)


class WarehouseLocator:
    """Routes order fulfillments to the nearest warehouse with available stock."""

    WAREHOUSES = {
        "WH_US_EAST": ["NY", "MA", "PA", "NJ", "CT", "VA"],
        "WH_US_WEST": ["CA", "OR", "WA", "NV", "AZ"],
        "WH_US_CENTRAL": ["IL", "TX", "OH", "MI", "MO"],
        "WH_MAIN": [],
    }

    @classmethod
    def locate_optimal_warehouse(cls, destination_state: str) -> str:
        """Find optimal warehouse location for state code."""
        state = destination_state.upper().strip()
        for wh_id, states in cls.WAREHOUSES.items():
            if state in states:
                return wh_id
        return "WH_MAIN"
