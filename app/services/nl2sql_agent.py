"""End-to-end NL2SQL orchestration with RAG grounding and self-healing retries."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    LLMGenerationError,
    QueryExecutionError,
    QuotaLimitExceededError,
    UnsafeSQLError,
)
from app.core.logging import get_logger
from app.prompts.insight_prompt import build_insight_messages
from app.prompts.nl2sql_prompt import build_nl2sql_messages
from app.prompts.repair_prompt import build_repair_messages
from app.services.bigquery_client import BigQueryService, QueryResult
from app.services.llm_client import LLMClient, OllamaLLMClient
from app.services.rag_retriever import RAGRetriever
from app.services.sql_validator import strip_markdown_fences

logger = get_logger(__name__)

_RECOVERABLE_ERRORS = (QuotaLimitExceededError, QueryExecutionError)


@dataclass(frozen=True)
class AgentResponse:
    """Complete output and telemetry from an NL2SQL agent run."""

    question: str
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int
    insight: str
    bytes_processed: int
    execution_time_ms: float
    llm_latency_ms: float
    total_latency_ms: float
    attempts: int
    repaired: bool
    prompt_tokens: int
    completion_tokens: int
    model: str
    cached: bool = False


class NL2SQLAgent:
    """Orchestrates retrieval, SQL generation, guardrails, retries, and insights."""

    def __init__(
        self,
        settings: Settings | None = None,
        bq_service: BigQueryService | None = None,
        retriever: RAGRetriever | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.bq_service = bq_service or BigQueryService(settings=self.settings)
        self.retriever = retriever or RAGRetriever(settings=self.settings)
        self.llm_client = llm_client or OllamaLLMClient(settings=self.settings)

    def ask(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        generate_insight: bool = True,
        max_rows: int = 500,
    ) -> AgentResponse:
        """Convert a natural language question into validated BigQuery results."""
        clean_question = question.strip()
        if not clean_question:
            raise ValueError("Question must not be empty.")

        total_start = time.perf_counter()
        context = self.retriever.retrieve(clean_question)
        context_text = context.to_prompt_text()

        max_attempts = 1 + self.settings.max_repair_retries
        llm_latency_ms = 0.0
        prompt_tokens = 0
        completion_tokens = 0
        model_name = self.settings.llm_model

        last_sql = ""
        last_error = ""
        query_result: QueryResult | None = None
        attempts_used = 0

        for attempt in range(1, max_attempts + 1):
            attempts_used = attempt
            if attempt == 1:
                messages = build_nl2sql_messages(
                    question=clean_question,
                    context_text=context_text,
                    dataset=self.settings.bigquery_dataset,
                    history=history,
                )
            else:
                messages = build_repair_messages(
                    question=clean_question,
                    failed_sql=last_sql,
                    error_message=last_error,
                    context_text=context_text,
                    dataset=self.settings.bigquery_dataset,
                )

            llm_resp = self.llm_client.chat(messages, temperature=0.0)
            llm_latency_ms += llm_resp.latency_ms
            prompt_tokens += llm_resp.prompt_tokens
            completion_tokens += llm_resp.completion_tokens
            model_name = llm_resp.model

            candidate_sql = strip_markdown_fences(llm_resp.content)
            last_sql = candidate_sql

            try:
                query_result = self.bq_service.execute_query(
                    candidate_sql,
                    max_rows=max_rows,
                )
                break
            except UnsafeSQLError as exc:
                logger.warning(
                    "Blocked unsafe SQL immediately",
                    extra={
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                raise
            except _RECOVERABLE_ERRORS as exc:
                last_error = str(exc)
                logger.warning(
                    "SQL attempt failed",
                    extra={
                        "extra_data": {
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "error_type": type(exc).__name__,
                            "error": last_error,
                        }
                    },
                )
                if attempt == max_attempts:
                    raise

        assert query_result is not None

        insight_text = self._generate_insight(
            question=clean_question,
            result=query_result,
            enabled=generate_insight,
        )
        insight, extra_latency, extra_prompt_tok, extra_comp_tok = insight_text
        llm_latency_ms = round(llm_latency_ms + extra_latency, 2)
        prompt_tokens += extra_prompt_tok
        completion_tokens += extra_comp_tok

        total_latency_ms = round((time.perf_counter() - total_start) * 1000, 2)

        return AgentResponse(
            question=clean_question,
            sql=query_result.sql,
            columns=query_result.columns,
            rows=query_result.rows,
            total_rows=query_result.total_rows,
            insight=insight,
            bytes_processed=query_result.bytes_processed,
            execution_time_ms=query_result.execution_time_ms,
            llm_latency_ms=llm_latency_ms,
            total_latency_ms=total_latency_ms,
            attempts=attempts_used,
            repaired=attempts_used > 1,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model_name,
        )

    def _generate_insight(
        self,
        question: str,
        result: QueryResult,
        enabled: bool,
    ) -> tuple[str, float, int, int]:
        """Generate a grounded narrative summary, falling back safely on LLM errors."""
        if not enabled:
            return "", 0.0, 0, 0
        if not result.rows:
            return "No matching records were found for this query.", 0.0, 0, 0

        messages = build_insight_messages(
            question=question,
            sql=result.sql,
            rows=result.rows,
            total_rows=result.total_rows,
        )
        try:
            resp = self.llm_client.chat(messages, temperature=0.2)
            return resp.content, resp.latency_ms, resp.prompt_tokens, resp.completion_tokens
        except LLMGenerationError as exc:
            logger.warning(
                "Insight generation skipped after LLM error",
                extra={"extra_data": {"error": str(exc)}},
            )
            fallback = (
                f"Query succeeded and returned {len(result.rows)} "
                f"of {result.total_rows} total rows."
            )
            return fallback, 0.0, 0, 0