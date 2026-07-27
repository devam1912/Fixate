"""Unit tests for calculator app."""

from calculator import calculate_discount, divide_numbers

def test_calculate_discount():
    # Price $100 with 20% discount should be $80
    result = calculate_discount(100.0, 20.0)
    assert result == 80.0

def test_divide_numbers_valid():
    assert divide_numbers(10.0, 2.0) == 5.0
