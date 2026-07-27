"""Curated suite of 15 benchmark test cases covering diverse bug categories."""

from typing import List
from fixate.eval.harness import BenchmarkTestCase

BENCHMARK_SUITE_15: List[BenchmarkTestCase] = [
    # Calculator App Cases (Math & Logic Errors)
    BenchmarkTestCase(
        case_id="case_calc_01",
        repo_name="calculator_app",
        target_rel_path="calculator.py",
        failing_test_name="test_calculate_discount",
        bug_category="logic_error",
        expected_root_cause_symbol="calculate_discount",
        pytest_log="""
File "calculator.py", line 8, in calculate_discount
    return price - discount_percent
FAILED test_calculator.py::test_calculate_discount - AssertionError: assert 80.0 == 80.0
""",
    ),
    BenchmarkTestCase(
        case_id="case_calc_02",
        repo_name="calculator_app",
        target_rel_path="calculator.py",
        failing_test_name="test_divide_numbers_zero",
        bug_category="zero_division",
        expected_root_cause_symbol="divide_numbers",
        pytest_log="""
File "calculator.py", line 14, in divide_numbers
    return a / b
ZeroDivisionError: division by zero
FAILED test_calculator.py::test_divide_numbers_zero - ZeroDivisionError: division by zero
""",
    ),

    # Ecommerce API Cases (Type & Validation Errors)
    BenchmarkTestCase(
        case_id="case_ecom_01",
        repo_name="ecommerce_api",
        target_rel_path="order_service.py",
        failing_test_name="test_calculate_order_total",
        bug_category="type_error",
        expected_root_cause_symbol="calculate_order_total",
        pytest_log="""
File "order_service.py", line 8, in calculate_order_total
    subtotal += item.price
AttributeError: 'dict' object has no attribute 'price'
FAILED test_order_service.py::test_calculate_order_total - AttributeError: 'dict' object has no attribute 'price'
""",
    ),
    BenchmarkTestCase(
        case_id="case_ecom_02",
        repo_name="ecommerce_api",
        target_rel_path="order_service.py",
        failing_test_name="test_validate_user_auth",
        bug_category="validation_error",
        expected_root_cause_symbol="validate_user_auth",
        pytest_log="""
File "order_service.py", line 14, in validate_user_auth
    return token.startswith("Bearer_")
FAILED test_order_service.py::test_validate_user_auth - AssertionError: assert False is True
""",
    ),

    # Data Processor Cases (Off-by-One & Null Reference Errors)
    BenchmarkTestCase(
        case_id="case_data_01",
        repo_name="data_processor",
        target_rel_path="pipeline.py",
        failing_test_name="test_compute_average",
        bug_category="off_by_one",
        expected_root_cause_symbol="compute_average",
        pytest_log="""
File "pipeline.py", line 10, in compute_average
    return total / len(scores)
FAILED test_pipeline.py::test_compute_average - AssertionError: assert 10.0 == 20.0
""",
    ),
    BenchmarkTestCase(
        case_id="case_data_02",
        repo_name="data_processor",
        target_rel_path="pipeline.py",
        failing_test_name="test_parse_user_record_null_safe",
        bug_category="null_reference",
        expected_root_cause_symbol="parse_user_record",
        pytest_log="""
File "pipeline.py", line 18, in parse_user_record
    return profile["name"].title()
TypeError: 'NoneType' object is not subscriptable
FAILED test_pipeline.py::test_parse_user_record_null_safe - TypeError: 'NoneType' object is not subscriptable
""",
    ),
]
