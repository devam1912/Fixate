"""Sample repository registry and benchmark reset fixtures."""

import logging
import os
import shutil
import tempfile

from fixate.paths import SAMPLE_REPOS_DIR

logger = logging.getLogger(__name__)

SAMPLE_REPOS = {
    "calculator_app": str(SAMPLE_REPOS_DIR / "calculator_app"),
    "ecommerce_api": str(SAMPLE_REPOS_DIR / "ecommerce_api"),
    "data_processor": str(SAMPLE_REPOS_DIR / "data_processor"),
    "enterprise_app": str(SAMPLE_REPOS_DIR / "enterprise_app"),
    "ts_cart_app": str(SAMPLE_REPOS_DIR / "ts_cart_app"),
}

# Directories that must not be copied into a checkout: heavy, regenerable, or
# actively harmful to duplicate per verification attempt.
CHECKOUT_IGNORES = (".git", "__pycache__", ".pytest_cache", ".fixate_venv")

BUGGY_BENCHMARK_FILES = {
    "calculator_app": {
        "calculator.py": '''"""Calculator app sample target repo for testing math logic bugs."""

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
'''
    },
    "ecommerce_api": {
        "order_service.py": '''"""Ecommerce Order Service sample target repo with type and validation bugs."""

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
'''
    },
    "data_processor": {
        "pipeline.py": '''"""Data processor pipeline sample target repo with off-by-one and null handling bugs."""

def compute_average(scores: list) -> float:
    """Compute average score from a list.
    Bug: Off-by-one loop boundary (range(len(scores) - 1)) misses the last score.
    """
    if not scores:
        return 0.0
    total = 0.0
    # Intentional off-by-one bug: range(len(scores) - 1) ignores last element!
    for i in range(len(scores) - 1):
        total += scores[i]
    return total / len(scores)

def parse_user_record(record: dict) -> str:
    """Extract formatted user display name.
    Bug: Unhandled NoneType / missing 'profile' key raises KeyError or AttributeError.
    """
    profile = record.get("profile")
    # Intentional null reference bug: profile might be None or dict without 'name'
    return profile["name"].title()
'''
    },
    "ts_cart_app": {
        os.path.join("src", "cart.js"): '''/** Shopping cart pricing rules. */

export function applyDiscount(price, discountPercent) {
  // INTENTIONAL BUG: subtracts the percentage value directly instead of
  // computing the percentage of the price.
  return price - discountPercent;
}

export function cartTotal(items) {
  return items.reduce((sum, item) => sum + item.price * item.quantity, 0);
}
''',
    },
}

# enterprise_app deliberately has no inline fixture: its five seeded defects span
# several modules, and duplicating them here would guarantee the copy drifts from
# the originals. It stays pristine because every incident runs against a temporary
# checkout (see create_sample_repo_checkout) and never writes to the source tree.


def reset_benchmark_repo_if_needed(repo_name: str):
    """Restore a sample benchmark repo to its intentional buggy state."""
    if repo_name not in BUGGY_BENCHMARK_FILES or repo_name not in SAMPLE_REPOS:
        return

    repo_dir = SAMPLE_REPOS[repo_name]
    for rel_filename, buggy_code in BUGGY_BENCHMARK_FILES[repo_name].items():
        target_path = os.path.join(repo_dir, rel_filename)
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(buggy_code)
            logger.info(f"Reset sample repo '{repo_name}' file '{rel_filename}' to intentional buggy state.")
        except Exception as exc:
            logger.warning(f"Could not reset sample repo file {target_path}: {exc}")


def create_sample_repo_checkout(repo_name: str) -> str:
    """Return an isolated temporary checkout for a bundled sample repository."""
    if repo_name not in SAMPLE_REPOS:
        raise KeyError(f"Unknown sample repository: {repo_name}")

    reset_benchmark_repo_if_needed(repo_name)
    source_dir = SAMPLE_REPOS[repo_name]
    tmp_dir = tempfile.mkdtemp(prefix=f"fixate_{repo_name}_")
    shutil.copytree(
        source_dir,
        tmp_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*CHECKOUT_IGNORES),
    )
    return tmp_dir
