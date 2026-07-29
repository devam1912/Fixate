"""Unit tests for AST parser, graph builder, and graph traversal algorithms."""

import os
import tempfile
import pytest
from fixate.graph.python_parser import PythonASTParser
from fixate.graph.ts_parser import TypeScriptParser
from fixate.graph.builder import CodebaseGraphBuilder
from fixate.graph.traversal import GraphTraversal
from fixate.graph.base_parser import SymbolType


SAMPLE_PYTHON_CODE = """
import math

def calculate_tax(price: float) -> float:
    \"\"\"Calculate tax for a given price.\"\"\"
    rate = 0.2
    return multiply(price, rate)

def multiply(a: float, b: float) -> float:
    return a * b

class PricingService:
    def process_order(self, amount: float) -> float:
        return calculate_tax(amount)

def test_calculate_tax():
    res = calculate_tax(100.0)
    assert res == 20.0
"""


def test_python_ast_parser_extraction():
    parser = PythonASTParser()
    symbols = parser.parse_code(SAMPLE_PYTHON_CODE, file_path="sample.py")

    assert len(symbols) >= 4

    names = {s.name for s in symbols}
    assert "calculate_tax" in names
    assert "multiply" in names
    assert "PricingService" in names
    assert "test_calculate_tax" in names

    calc_tax_sym = next(s for s in symbols if s.name == "calculate_tax")
    assert calc_tax_sym.symbol_type == SymbolType.FUNCTION
    assert "multiply" in calc_tax_sym.calls
    assert "Calculate tax for a given price." in calc_tax_sym.docstring

    test_sym = next(s for s in symbols if s.name == "test_calculate_tax")
    assert test_sym.is_test is True
    assert test_sym.symbol_type == SymbolType.TEST
    assert "calculate_tax" in test_sym.calls


def test_typescript_parser():
    parser = TypeScriptParser()
    assert parser.supports_file("app.ts") is True
    assert parser.supports_file("index.jsx") is True
    assert parser.supports_file("main.py") is False

    js_code = """
export function processPayment(amount) {
    return applyFee(amount);
}
it('should process payment', () => {
    expect(processPayment(10)).toBe(11);
});
"""
    symbols = parser.parse_code(js_code, file_path="payment.ts")
    by_name = {s.name: s for s in symbols}

    assert "processPayment" in by_name
    # The stub recorded a single line and never populated calls, so JS symbols
    # entered the graph with no edges at all.
    payment = by_name["processPayment"]
    assert "applyFee" in payment.calls
    assert payment.end_line > payment.start_line
    assert "return applyFee(amount);" in payment.code

    assert "should process payment" in by_name
    assert by_name["should process payment"].is_test is True


def test_graph_builder_and_traversal():
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = os.path.join(tmp_dir, "service.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_PYTHON_CODE)

        builder = CodebaseGraphBuilder()
        graph = builder.build_from_directory(tmp_dir)

        assert graph.number_of_nodes() >= 4

        traversal = GraphTraversal(builder)

        # Test line lookup
        sym = traversal.find_symbol_by_file_line("service.py", 4)
        assert sym is not None
        assert sym.name == "calculate_tax"

        # Test callers and callees
        calc_tax_id = next(s_id for s_id in builder.symbols if "calculate_tax" in s_id and "test_" not in s_id)
        callees = traversal.get_callees(calc_tax_id)
        callee_names = [c.name for c in callees]
        assert "multiply" in callee_names

        # Test backward trace from failing test
        test_id = next(s_id for s_id in builder.symbols if "test_calculate_tax" in s_id)
        candidates = traversal.backward_trace(test_id, max_depth=3)
        candidate_names = [c.name for c in candidates]
        assert "calculate_tax" in candidate_names
