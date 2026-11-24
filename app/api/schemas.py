"""Pydantic v2 request and response schemas for the QueryLens API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConversationTurn(BaseModel):
    question: str = Field(..., min_length=1)
    sql: str = Field(..., min_length=1)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    history: list[ConversationTurn] = Field(default_factory=list)
    use_cache: bool = True
    generate_insight: bool = True
    max_rows: int = Field(default=500, ge=1, le=2000)


class ChartSpecSchema(BaseModel):
    chart_type: str
    title: str = ""
    x: str | None = None
    y: list[str] = Field(default_factory=list)
    kpis: list[dict[str, Any]] = Field(default_factory=list)


class QueryResponse(BaseModel):
    question: str
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int
    insight: str
    chart: ChartSpecSchema
    bytes_processed: int
    execution_time_ms: float
    llm_latency_ms: float
    total_latency_ms: float
    attempts: int
    repaired: bool
    cached: bool
    model: str


class HealthResponse(BaseModel):
    status: str
    dataset: str
    model: str
    max_bytes_per_query: int


class TelemetrySummaryResponse(BaseModel):
    total_queries: int
    success_rate_pct: float
    cache_hit_rate_pct: float
    repair_rate_pct: float
    avg_latency_ms: float
    total_bytes_processed: int
    recent_queries: list[dict[str, Any]]