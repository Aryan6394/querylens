"""Automated benchmark runner for QueryLens against the golden dataset."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.exceptions import (
    LLMGenerationError,
    QueryExecutionError,
    QuotaLimitExceededError,
    UnsafeSQLError,
)
from app.core.logging import setup_logging
from app.services.bigquery_client import BigQueryService
from app.services.nl2sql_agent import NL2SQLAgent
from eval.metrics import (
    EvalCaseResult,
    format_markdown_report,
    results_match,
    summarize_results,
)


def evaluate_case(
    case: dict[str, Any],
    agent: NL2SQLAgent,
    bq_service: BigQueryService,
) -> EvalCaseResult:
    """Run a single benchmark question and grade the result."""
    case_id = str(case["id"])
    difficulty = str(case["difficulty"])
    question = str(case["question"])
    expect_blocked = bool(case.get("expect_blocked", False))
    ordered = bool(case.get("ordered", False))

    start = time.perf_counter()
    try:
        agent_resp = agent.ask(question, generate_insight=False, max_rows=200)
    except (UnsafeSQLError, QuotaLimitExceededError) as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return EvalCaseResult(
            case_id=case_id,
            difficulty=difficulty,
            expect_blocked=expect_blocked,
            passed=expect_blocked,
            valid_first_attempt=False,
            repaired_successfully=False,
            blocked=True,
            latency_ms=elapsed_ms,
            error=str(exc),
        )
    except (QueryExecutionError, LLMGenerationError) as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return EvalCaseResult(
            case_id=case_id,
            difficulty=difficulty,
            expect_blocked=expect_blocked,
            passed=False,
            valid_first_attempt=False,
            repaired_successfully=False,
            blocked=False,
            latency_ms=elapsed_ms,
            error=str(exc),
        )

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    if expect_blocked:
        return EvalCaseResult(
            case_id=case_id,
            difficulty=difficulty,
            expect_blocked=True,
            passed=False,
            valid_first_attempt=False,
            repaired_successfully=False,
            blocked=False,
            latency_ms=elapsed_ms,
            generated_sql=agent_resp.sql,
            error="Expected guardrail block, but query executed.",
        )

    gold_sql = str(case["ground_truth_sql"])
    gold_result = bq_service.execute_query(gold_sql, max_rows=200)
    matched = results_match(agent_resp.rows, gold_result.rows, ordered=ordered)

    return EvalCaseResult(
        case_id=case_id,
        difficulty=difficulty,
        expect_blocked=False,
        passed=matched,
        valid_first_attempt=agent_resp.attempts == 1,
        repaired_successfully=agent_resp.repaired,
        blocked=False,
        latency_ms=elapsed_ms,
        generated_sql=agent_resp.sql,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run QueryLens evaluation benchmarks.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("eval/golden_dataset.json"),
        help="Path to the golden evaluation JSON file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("storage/eval_report.json"),
        help="Path to save the detailed JSON report.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optionally evaluate only the first N cases.",
    )
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level)

    cases: list[dict[str, Any]] = json.loads(args.dataset.read_text(encoding="utf-8"))
    if args.limit > 0:
        cases = cases[: args.limit]

    bq_service = BigQueryService(settings=settings)
    agent = NL2SQLAgent(settings=settings, bq_service=bq_service)

    results: list[EvalCaseResult] = []
    for idx, case in enumerate(cases, start=1):
        print(f"[{idx}/{len(cases)}] Evaluating {case['id']}...")
        res = evaluate_case(case, agent=agent, bq_service=bq_service)
        status = "PASS" if res.passed else "FAIL"
        print(f"    -> {status} | {res.latency_ms:.0f} ms")
        results.append(res)

    summary = summarize_results(results)
    report = {
        "summary": summary,
        "cases": [asdict(r) for r in results],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + format_markdown_report(summary))
    print(f"\nDetailed report saved to: {args.output}")


if __name__ == "__main__":
    main()