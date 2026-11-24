"""Unit tests for the NL2SQL agent, self-healing loop, and conversation context."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.core.exceptions import (
    QueryExecutionError,
    QuotaLimitExceededError,
    UnsafeSQLError,
)
from app.services.bigquery_client import QueryResult
from app.services.llm_client import LLMResponse
from app.services.nl2sql_agent import NL2SQLAgent
from app.services.rag_retriever import RetrievedContext

DATASET = "bigquery-public-data.thelook_ecommerce"


def _make_settings(max_retries: int = 2) -> Settings:
    return Settings(
        gcp_project_id="test-sandbox",
        bigquery_dataset=DATASET,
        max_repair_retries=max_retries,
    )


def _mock_retriever() -> MagicMock:
    retriever = MagicMock()
    retriever.retrieve.return_value = RetrievedContext(
        schemas=[f"Table: `{DATASET}.orders`\nColumns:\n  - order_id (INT64)"],
        glossary=["- **Net Revenue**: SUM(sale_price)"],
        examples=[],
    )
    return retriever


def _sample_query_result(sql: str, rows: list[dict] | None = None) -> QueryResult:
    data = rows if rows is not None else [{"category": "Jeans", "net_revenue": 12500.5}]
    columns = list(data[0].keys()) if data else ["category", "net_revenue"]
    return QueryResult(
        sql=sql,
        columns=columns,
        rows=data,
        total_rows=len(data),
        bytes_processed=1_048_576,
        execution_time_ms=120.5,
    )


def test_agent_succeeds_on_first_attempt() -> None:
    sql = f"SELECT category, net_revenue FROM `{DATASET}.products` LIMIT 5"
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        LLMResponse(
            content=f"```sql\n{sql}\n```",
            model="qwen2.5-coder:7b",
            latency_ms=300.0,
            prompt_tokens=150,
            completion_tokens=40,
        ),
        LLMResponse(
            content="Jeans led net revenue at 12,500.50.",
            model="qwen2.5-coder:7b",
            latency_ms=200.0,
            prompt_tokens=100,
            completion_tokens=20,
        ),
    ]
    mock_bq = MagicMock()
    mock_bq.execute_query.return_value = _sample_query_result(sql)

    agent = NL2SQLAgent(
        settings=_make_settings(),
        bq_service=mock_bq,
        retriever=_mock_retriever(),
        llm_client=mock_llm,
    )
    response = agent.ask("Top categories by net revenue?")

    assert response.attempts == 1
    assert response.repaired is False
    assert response.sql == sql
    assert response.insight == "Jeans led net revenue at 12,500.50."
    assert response.prompt_tokens == 250
    assert response.completion_tokens == 60
    assert response.llm_latency_ms == 500.0


def test_agent_self_heals_after_bigquery_error() -> None:
    bad_sql = f"SELECT bogus_col FROM `{DATASET}.orders` LIMIT 5"
    good_sql = f"SELECT order_id FROM `{DATASET}.orders` LIMIT 5"

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        LLMResponse(content=bad_sql, model="qwen2.5-coder:7b", latency_ms=250.0),
        LLMResponse(content=good_sql, model="qwen2.5-coder:7b", latency_ms=220.0),
        LLMResponse(content="Returned top orders.", model="qwen2.5-coder:7b", latency_ms=180.0),
    ]
    mock_bq = MagicMock()
    mock_bq.execute_query.side_effect = [
        QueryExecutionError("Unrecognized name: bogus_col"),
        _sample_query_result(good_sql, rows=[{"order_id": 1}]),
    ]

    agent = NL2SQLAgent(
        settings=_make_settings(max_retries=2),
        bq_service=mock_bq,
        retriever=_mock_retriever(),
        llm_client=mock_llm,
    )
    response = agent.ask("Show 5 order IDs")

    assert response.attempts == 2
    assert response.repaired is True
    assert response.sql == good_sql

    # Verify the repair prompt received the BigQuery error trace
    repair_messages = mock_llm.chat.call_args_list[1].args[0]
    assert "Unrecognized name: bogus_col" in repair_messages[-1]["content"]


def test_agent_raises_after_exhausting_retries() -> None:
    sql = f"SELECT * FROM `{DATASET}.events`"
    mock_llm = MagicMock()
    mock_llm.chat.return_value = LLMResponse(
        content=sql,
        model="qwen2.5-coder:7b",
        latency_ms=100.0,
    )
    mock_bq = MagicMock()
    mock_bq.execute_query.side_effect = QuotaLimitExceededError(
        estimated_bytes=2_000_000_000,
        max_bytes=1_000_000_000,
    )

    agent = NL2SQLAgent(
        settings=_make_settings(max_retries=2),
        bq_service=mock_bq,
        retriever=_mock_retriever(),
        llm_client=mock_llm,
    )

    with pytest.raises(QuotaLimitExceededError):
        agent.ask("Dump all events")

    # 1 initial attempt + 2 repair retries = 3 total attempts
    assert mock_bq.execute_query.call_count == 3


def test_agent_stops_immediately_on_unsafe_sql() -> None:
    sql = f"DROP TABLE `{DATASET}.orders`"
    mock_llm = MagicMock()
    mock_llm.chat.return_value = LLMResponse(
        content=sql,
        model="qwen2.5-coder:7b",
        latency_ms=100.0,
    )
    mock_bq = MagicMock()
    mock_bq.execute_query.side_effect = UnsafeSQLError(
        "Forbidden SQL operation: Drop"
    )

    agent = NL2SQLAgent(
        settings=_make_settings(max_retries=2),
        bq_service=mock_bq,
        retriever=_mock_retriever(),
        llm_client=mock_llm,
    )

    with pytest.raises(UnsafeSQLError):
        agent.ask("Drop the orders table")

    assert mock_bq.execute_query.call_count == 1
    assert mock_llm.chat.call_count == 1


def test_agent_passes_conversation_history_to_prompt() -> None:
    sql = f"SELECT order_id FROM `{DATASET}.orders` WHERE status = 'Complete' LIMIT 5"
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        LLMResponse(content=sql, model="qwen2.5-coder:7b", latency_ms=100.0),
        LLMResponse(
            content="Filtered completed orders.",
            model="qwen2.5-coder:7b",
            latency_ms=80.0,
        ),
    ]
    mock_bq = MagicMock()
    mock_bq.execute_query.return_value = _sample_query_result(sql, rows=[{"order_id": 42}])

    agent = NL2SQLAgent(
        settings=_make_settings(),
        bq_service=mock_bq,
        retriever=_mock_retriever(),
        llm_client=mock_llm,
    )
    history = [
        {
            "question": "Show 5 orders",
            "sql": f"SELECT order_id FROM `{DATASET}.orders` LIMIT 5",
        }
    ]
    agent.ask("Filter only completed ones", history=history)

    first_call_messages = mock_llm.chat.call_args_list[0].args[0]
    contents = [m["content"] for m in first_call_messages]
    assert "Show 5 orders" in contents
    assert f"SELECT order_id FROM `{DATASET}.orders` LIMIT 5" in contents


def test_agent_handles_empty_rows_without_insight_llm_call() -> None:
    sql = f"SELECT order_id FROM `{DATASET}.orders` WHERE order_id = -1"
    mock_llm = MagicMock()
    mock_llm.chat.return_value = LLMResponse(
        content=sql,
        model="qwen2.5-coder:7b",
        latency_ms=100.0,
    )
    mock_bq = MagicMock()
    mock_bq.execute_query.return_value = _sample_query_result(sql, rows=[])

    agent = NL2SQLAgent(
        settings=_make_settings(),
        bq_service=mock_bq,
        retriever=_mock_retriever(),
        llm_client=mock_llm,
    )
    response = agent.ask("Find order -1")

    assert mock_llm.chat.call_count == 1
    assert "No matching records" in response.insight