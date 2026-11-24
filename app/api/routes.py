"""FastAPI route definitions for QueryLens."""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.schemas import (
    ChartSpecSchema,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    TelemetrySummaryResponse,
)
from app.core.config import Settings
from app.core.exceptions import (
    LLMGenerationError,
    QueryExecutionError,
    QuotaLimitExceededError,
    UnsafeSQLError,
)
from app.services.cache_service import CacheAndTelemetryService, build_cache_key
from app.services.chart_builder import recommend_chart
from app.services.nl2sql_agent import NL2SQLAgent

router = APIRouter()


def get_agent(request: Request) -> NL2SQLAgent:
    return request.app.state.agent


def get_cache_service(request: Request) -> CacheAndTelemetryService:
    return request.app.state.cache


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


AgentDep = Annotated[NL2SQLAgent, Depends(get_agent)]
CacheDep = Annotated[CacheAndTelemetryService, Depends(get_cache_service)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health_check(settings: SettingsDep) -> HealthResponse:
    """Return service status and active free-tier configuration."""
    return HealthResponse(
        status="ok",
        dataset=settings.bigquery_dataset,
        model=settings.llm_model,
        max_bytes_per_query=settings.max_bytes_per_query,
    )


@router.get("/telemetry", response_model=TelemetrySummaryResponse, tags=["observability"])
def get_telemetry(cache: CacheDep, limit: int = 10) -> TelemetrySummaryResponse:
    """Return aggregate query latency, cache hit rate, and repair telemetry."""
    summary = cache.get_telemetry_summary(recent_limit=limit)
    return TelemetrySummaryResponse(**summary)


@router.get("/schema", tags=["metadata"])
def get_indexed_schema(agent: AgentDep, settings: SettingsDep) -> dict[str, Any]:
    """Return indexed table schema previews from local ChromaDB."""
    ctx = agent.retriever.retrieve(
        "list all tables and columns",
        n_schemas=20,
        n_glossary=0,
        n_examples=0,
    )
    return {
        "dataset": settings.bigquery_dataset,
        "indexed_table_count": len(ctx.schemas),
        "schemas": ctx.schemas,
    }


@router.post("/query", response_model=QueryResponse, tags=["analytics"])
def run_natural_language_query(
    payload: QueryRequest,
    agent: AgentDep,
    cache: CacheDep,
    settings: SettingsDep,
) -> QueryResponse:
    """Translate a natural language question to BigQuery SQL, run it, and chart results."""
    req_start = time.perf_counter()
    history_dicts = [turn.model_dump() for turn in payload.history]
    cache_key = build_cache_key(
        question=payload.question,
        dataset=settings.bigquery_dataset,
        history=history_dicts,
    )

    if payload.use_cache:
        cached_payload = cache.get_cached_response(cache_key)
        if cached_payload is not None:
            elapsed_ms = round((time.perf_counter() - req_start) * 1000, 2)
            cached_payload["cached"] = True
            cached_payload["total_latency_ms"] = elapsed_ms
            cache.record_telemetry(
                question=payload.question,
                sql=str(cached_payload.get("sql", "")),
                bytes_processed=0,
                total_latency_ms=elapsed_ms,
                attempts=0,
                repaired=False,
                cached=True,
                success=True,
            )
            return QueryResponse(**cached_payload)

    try:
        result = agent.ask(
            question=payload.question,
            history=history_dicts,
            generate_insight=payload.generate_insight,
            max_rows=payload.max_rows,
        )
    except UnsafeSQLError as exc:
        _log_failure(cache, payload.question, req_start, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except QuotaLimitExceededError as exc:
        _log_failure(cache, payload.question, req_start, exc)
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except (QueryExecutionError, LLMGenerationError) as exc:
        _log_failure(cache, payload.question, req_start, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    chart_spec = recommend_chart(
        columns=result.columns,
        rows=result.rows,
        title=result.question,
    )
    response = QueryResponse(
        question=result.question,
        sql=result.sql,
        columns=result.columns,
        rows=result.rows,
        total_rows=result.total_rows,
        insight=result.insight,
        chart=ChartSpecSchema(**chart_spec.to_dict()),
        bytes_processed=result.bytes_processed,
        execution_time_ms=result.execution_time_ms,
        llm_latency_ms=result.llm_latency_ms,
        total_latency_ms=result.total_latency_ms,
        attempts=result.attempts,
        repaired=result.repaired,
        cached=False,
        model=result.model,
    )

    if payload.use_cache:
        cache.set_cached_response(cache_key, response.model_dump())

    cache.record_telemetry(
        question=result.question,
        sql=result.sql,
        bytes_processed=result.bytes_processed,
        execution_time_ms=result.execution_time_ms,
        llm_latency_ms=result.llm_latency_ms,
        total_latency_ms=result.total_latency_ms,
        attempts=result.attempts,
        repaired=result.repaired,
        cached=False,
        success=True,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
    return response


def _log_failure(
    cache: CacheAndTelemetryService,
    question: str,
    start_time: float,
    exc: Exception,
) -> None:
    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
    cache.record_telemetry(
        question=question,
        total_latency_ms=elapsed_ms,
        success=False,
        error_type=type(exc).__name__,
    )