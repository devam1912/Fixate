"""Benchmark suite of seeded defects across languages and bug categories.

No case carries a hand-written failure log. The harness runs each repository's own
suite and feeds the pipeline whatever the runner actually printed, so a case cannot
drift from the code it describes. If a repository's tests stop failing, the harness
says so rather than scoring against a traceback nobody produced.

Each entry names the symbol the localizer is expected to identify, which is what
`localization_accuracy_pct` measures.
"""

from typing import List

from fixate.eval.harness import BenchmarkTestCase

BENCHMARK_SUITE: List[BenchmarkTestCase] = [
    # ---- calculator_app: math and logic ----
    BenchmarkTestCase(
        case_id="case_calc_01",
        repo_name="calculator_app",
        target_rel_path="calculator.py",
        failing_test_name="test_calculate_discount",
        bug_category="logic_error",
        expected_root_cause_symbol="calculate_discount",
    ),
    BenchmarkTestCase(
        case_id="case_calc_02",
        repo_name="calculator_app",
        target_rel_path="calculator.py",
        failing_test_name="test_divide_numbers_zero",
        bug_category="zero_division",
        expected_root_cause_symbol="divide_numbers",
    ),
    # ---- ecommerce_api: type and validation ----
    BenchmarkTestCase(
        case_id="case_ecom_01",
        repo_name="ecommerce_api",
        target_rel_path="order_service.py",
        failing_test_name="test_calculate_order_total",
        bug_category="type_error",
        expected_root_cause_symbol="calculate_order_total",
    ),
    # ---- data_processor: boundaries and null handling ----
    BenchmarkTestCase(
        case_id="case_data_01",
        repo_name="data_processor",
        target_rel_path="pipeline.py",
        failing_test_name="test_compute_average",
        bug_category="off_by_one",
        expected_root_cause_symbol="compute_average",
    ),
    BenchmarkTestCase(
        case_id="case_data_02",
        repo_name="data_processor",
        target_rel_path="pipeline.py",
        failing_test_name="test_parse_user_record_null_safe",
        bug_category="null_reference",
        expected_root_cause_symbol="parse_user_record",
    ),
    # ---- enterprise_app: multi-module, >1k LOC ----
    BenchmarkTestCase(
        case_id="case_ent_01",
        repo_name="enterprise_app",
        target_rel_path="billing/calculator.py",
        failing_test_name="test_billing_tiered_discount_calculation",
        bug_category="logic_error",
        expected_root_cause_symbol="calculate_tiered_discount",
    ),
    # ---- ts_cart_app: JavaScript, verified with Vitest ----
    BenchmarkTestCase(
        case_id="case_ts_01",
        repo_name="ts_cart_app",
        target_rel_path="src/cart.js",
        failing_test_name="applies a percentage discount",
        bug_category="logic_error",
        expected_root_cause_symbol="applyDiscount",
    ),
]
