"""Unit tests for data processor pipeline."""

from pipeline import compute_average, parse_user_record

def test_compute_average():
    # [10, 20, 30] average should be 20.0
    avg = compute_average([10, 20, 30])
    assert avg == 20.0

def test_parse_user_record_null_safe():
    res = parse_user_record({"profile": None})
    assert res == "Guest"
