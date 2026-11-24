"""Integration tests for FastAPI routes, caching, and telemetry."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import QuotaLimitExceededError, UnsafeSQLError
from app.main import create_app
from app.services.cache_service import CacheAndTelemetryService
from app.services.nl2sql_agent import AgentResponse

DATASET = "bigquery-public-data.thelook_ecommerce"


def _build_test_client(tmp_path: Path, mock_agent: MagicMock) -> TestClient:
    settings = Settings(
        gcp_project_id="test-sandbox",
        bigquery_dataset=DATASET,
        sqlite_db_path=tmp_path / "test_querylens.db",
        cache_ttl_seconds=3600,
    )
    cache = CacheAndTelemetryService(settings=settings)
    app = create_app(settings=settings, agent=mock_agent, cache=cache)
    return TestClient(app)


def _sample_agent_response() -> AgentResponse:
    return AgentResponse(
        question="Top 2 categories by revenue",
        sql=f"SELECT category, net_revenue FROM `{DATASET}.products` LIMIT 2",
        columns=["category", "net_revenue"],
        rows=[
            {"category": "Outerwear", "net_revenue": 54000.0},
            {"category": "Jeans", "net_revenue": 41200.5},
        ],
        total_rows=2,
        insight="Outerwear leads with 54,000 followed by Jeans at 41,200.5.",
        bytes_processed=2_097_152,
        execution_time_ms=110.0,
        llm_latency_ms=420.0,
        total_latency_ms=540.0,
        attempts=1,
        repaired=False,
        prompt_tokens=200,
        completion_tokens=50,
        model="qwen2.5-coder:7b",
    )


def test_health_endpoint(tmp_path: Path) -> None:
    mock_agent = MagicMock()
    with _build_test_client(tmp_path, mock_agent) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["dataset"] == DATASET


def test_query_endpoint_charts_and_caches_repeat_calls(tmp_path: Path) -> None:
    mock_agent = MagicMock()
    mock_agent.ask.return_value = _sample_agent_response()

    with _build_test_client(tmp_path, mock_agent) as client:
        first = client.post("/query", json={"question": "Top 2 categories by revenue"})
        second = client.post("/query", json={"question": "Top 2 categories by revenue"})
        telemetry = client.get("/telemetry")

    assert first.status_code == 200
    first_body = first.json()
    assert first_body["cached"] is False
    assert first_body["chart"]["chart_type"] == "bar"
    assert first_body["chart"]["x"] == "category"

    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert mock_agent.ask.call_count == 1

    stats = telemetry.json()
    assert stats["total_queries"] == 2
    assert stats["cache_hit_rate_pct"] == 50.0


def test_query_endpoint_maps_unsafe_sql_to_400(tmp_path: Path) -> None:
    mock_agent = MagicMock()
    mock_agent.ask.side_effect = UnsafeSQLError("Forbidden SQL operation: Drop")

    with _build_test_client(tmp_path, mock_agent) as client:
        resp = client.post("/query", json={"question": "Drop the orders table"})

    assert resp.status_code == 400
    assert "Forbidden SQL" in resp.json()["detail"]


def test_query_endpoint_maps_quota_exceeded_to_422(tmp_path: Path) -> None:
    mock_agent = MagicMock()
    mock_agent.ask.side_effect = QuotaLimitExceededError(2_000_000_000, 1_000_000_000)

    with _build_test_client(tmp_path, mock_agent) as client:
        resp = client.post("/query", json={"question": "Scan everything in events"})

    assert resp.status_code == 422
    assert "quota guard" in resp.json()["detail"]