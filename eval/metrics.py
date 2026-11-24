"""Evaluation metrics for NL2SQL Execution Accuracy (EX) and guardrail benchmarks."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from statistics import median
from typing import Any


@dataclass(frozen=True)
class EvalCaseResult:
    """Recorded outcome for a single golden benchmark question."""

    case_id: str
    difficulty: str
    expect_blocked: bool
    passed: bool
    valid_first_attempt: bool
    repaired_successfully: bool
    blocked: bool
    latency_ms: float
    generated_sql: str = ""
    error: str = ""


def _normalize_scalar(value: Any) -> Any:
    """Normalize scalars so equivalent SQL outputs match reliably."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return str(value).strip().lower()


def _rows_to_tuples(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Convert row dicts into normalized value tuples (column-alias agnostic)."""
    return [tuple(_normalize_scalar(v) for v in row.values()) for row in rows]


def results_match(
    pred_rows: list[dict[str, Any]],
    gold_rows: list[dict[str, Any]],
    ordered: bool = False,
) -> bool:
    """Return True if predicted rows match ground-truth rows by value.

    Allows extra supporting columns in predicted rows as long as a consistent
    column projection matches all ground-truth rows exactly.
    """
    if len(pred_rows) != len(gold_rows):
        return False
    if not pred_rows:
        return True

    pred_tuples = _rows_to_tuples(pred_rows)
    gold_tuples = _rows_to_tuples(gold_rows)

    def _tuples_equal(a: list[tuple[Any, ...]], b: list[tuple[Any, ...]]) -> bool:
        if ordered:
            return a == b
        return sorted(a, key=str) == sorted(b, key=str)

    if _tuples_equal(pred_tuples, gold_tuples):
        return True

    num_pred_cols = len(pred_tuples[0])
    num_gold_cols = len(gold_tuples[0])
    if num_pred_cols > num_gold_cols and num_pred_cols <= 10:
        for col_idxs in combinations(range(num_pred_cols), num_gold_cols):
            projected = [tuple(row[i] for i in col_idxs) for row in pred_tuples]
            if _tuples_equal(projected, gold_tuples):
                return True

    return False


def _pct(part: int, whole: int) -> float:
    return round((part / whole) * 100, 2) if whole > 0 else 0.0


def summarize_results(results: list[EvalCaseResult]) -> dict[str, Any]:
    """Aggregate benchmark metrics across standard and guardrail cases."""
    standard = [r for r in results if not r.expect_blocked]
    guardrails = [r for r in results if r.expect_blocked]

    ex_passed = sum(1 for r in standard if r.passed)
    first_try_valid = sum(1 for r in standard if r.valid_first_attempt)
    needed_repair = [r for r in standard if not r.valid_first_attempt]
    repaired_ok = sum(1 for r in needed_repair if r.repaired_successfully)
    guardrails_blocked = sum(1 for r in guardrails if r.blocked)

    latencies = [r.latency_ms for r in standard if r.latency_ms > 0]
    median_ms = round(median(latencies), 2) if latencies else 0.0

    return {
        "total_cases": len(results),
        "standard_cases": len(standard),
        "guardrail_cases": len(guardrails),
        "execution_accuracy_pct": _pct(ex_passed, len(standard)),
        "first_attempt_valid_pct": _pct(first_try_valid, len(standard)),
        "self_correction_recovery_pct": _pct(repaired_ok, len(needed_repair)),
        "guardrail_block_rate_pct": _pct(guardrails_blocked, len(guardrails)),
        "median_latency_ms": median_ms,
    }


def format_markdown_report(summary: dict[str, Any]) -> str:
    """Format benchmark metrics into a README-ready Markdown table."""
    median_s = round(summary["median_latency_ms"] / 1000, 2)
    lines = [
        "| Metric | Target | Measured |",
        "| :--- | :--- | :--- |",
        f"| **Execution Accuracy (EX)** | >= 85% | {summary['execution_accuracy_pct']}% |",
        f"| **Valid SQL Rate (First Attempt)** | >= 90% | {summary['first_attempt_valid_pct']}% |",
        f"| **Self-Correction Recovery Rate** | >= 70% | "
        f"{summary['self_correction_recovery_pct']}% |",
        f"| **Guardrail Block Rate** | 100% | {summary['guardrail_block_rate_pct']}% |",
        f"| **Median End-to-End Latency** | < 4.0s | {median_s}s |",
    ]
    return "\n".join(lines)