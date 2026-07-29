"""Unit tests for calculator app."""

from calculator import calculate_discount, divide_numbers


def test_calculate_discount():
    # $200 with a 10% discount should be $180.
    #
    # The inputs matter. The seeded bug subtracts the percentage as a raw amount,
    # so $100 with a 20% discount yields 80 either way and the defect stays
    # invisible to its own test. These inputs separate the two behaviours
    # (correct: 180, buggy: 190).
    result = calculate_discount(200.0, 10.0)
    assert result == 180.0


def test_divide_numbers_valid():
    assert divide_numbers(10.0, 2.0) == 5.0


def test_divide_numbers_zero():
    # Division by zero should be handled, not raised at the caller.
    assert divide_numbers(10.0, 0.0) == 0.0
