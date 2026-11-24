from __future__ import annotations

from eval.metrics import results_match


def test_results_match_allows_consistent_projection_of_extra_columns() -> None:
    predicted = [
        {"category": "Jeans", "debug_value": "x", "revenue": 12.5},
        {"category": "Shoes", "debug_value": "y", "revenue": 8.0},
    ]
    expected = [
        {"category": "Jeans", "revenue": 12.5},
        {"category": "Shoes", "revenue": 8.0},
    ]

    assert results_match(predicted, expected)


def test_results_match_projection_respects_ordered_flag() -> None:
    predicted = [
        {"support": "x", "value": 1},
        {"support": "y", "value": 2},
    ]
    expected = [{"value": 2}, {"value": 1}]

    assert results_match(predicted, expected)
    assert not results_match(predicted, expected, ordered=True)


def test_results_match_rejects_projection_when_values_do_not_match() -> None:
    predicted = [{"category": "Jeans", "revenue": 12.5, "extra": True}]
    expected = [{"category": "Jeans", "revenue": 15.0}]

    assert not results_match(predicted, expected)
