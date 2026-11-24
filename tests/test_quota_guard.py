"""Unit tests for the BigQuery dry-run quota guard and query runner."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import BadRequest

from app.core.config import Settings
from app.core.exceptions import (
    QueryExecutionError,
    QuotaLimitExceededError,
    UnsafeSQLError,
)
from app.services.bigquery_client import BigQueryService

DATASET = "bigquery-public-data.thelook_ecommerce"
CAP_BYTES = 100 * 1024 * 1024  # 100 MB test cap


def _make_settings() -> Settings:
    return Settings(
        gcp_project_id="test-sandbox-project",
        bigquery_dataset=DATASET,
        max_bytes_per_query=CAP_BYTES,
    )


def test_dry_run_allows_query_under_limit() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = SimpleNamespace(
        total_bytes_processed=25 * 1024 * 1024  # 25 MB
    )
    service = BigQueryService(settings=_make_settings(), client=mock_client)

    result = service.dry_run_check(f"SELECT order_id FROM `{DATASET}.orders` LIMIT 5")

    assert result.estimated_bytes == 25 * 1024 * 1024
    assert result.estimated_mb == 25.0
    assert mock_client.query.call_count == 1
    assert mock_client.query.call_args.kwargs["job_config"].dry_run is True


def test_dry_run_blocks_query_over_limit() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = SimpleNamespace(
        total_bytes_processed=250 * 1024 * 1024  # 250 MB > 100 MB cap
    )
    service = BigQueryService(settings=_make_settings(), client=mock_client)

    with pytest.raises(QuotaLimitExceededError) as exc_info:
        service.dry_run_check(f"SELECT * FROM `{DATASET}.events`")

    assert exc_info.value.estimated_bytes == 250 * 1024 * 1024
    assert exc_info.value.max_bytes == CAP_BYTES


def test_execute_query_stops_before_running_when_over_quota() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = SimpleNamespace(
        total_bytes_processed=500 * 1024 * 1024
    )
    service = BigQueryService(settings=_make_settings(), client=mock_client)

    with pytest.raises(QuotaLimitExceededError):
        service.execute_query(f"SELECT * FROM `{DATASET}.events`")

    # Only the dry-run call should happen; actual execution is never triggered
    assert mock_client.query.call_count == 1


def test_execute_query_blocks_unsafe_sql_before_hitting_bigquery() -> None:
    mock_client = MagicMock()
    service = BigQueryService(settings=_make_settings(), client=mock_client)

    with pytest.raises(UnsafeSQLError):
        service.execute_query(f"DROP TABLE `{DATASET}.orders`")

    assert mock_client.query.call_count == 0


def test_execute_query_returns_serialized_rows() -> None:
    dry_run_job = SimpleNamespace(total_bytes_processed=10 * 1024 * 1024)

    fake_rows = [
        {
            "order_id": 101,
            "revenue": Decimal("49.95"),
            "created_at": datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc),
        }
    ]
    fake_iterator = MagicMock()
    fake_iterator.schema = [
        SimpleNamespace(name="order_id"),
        SimpleNamespace(name="revenue"),
        SimpleNamespace(name="created_at"),
    ]
    fake_iterator.total_rows = 1
    fake_iterator.__iter__.return_value = iter(fake_rows)

    exec_job = MagicMock()
    exec_job.total_bytes_processed = 10 * 1024 * 1024
    exec_job.result.return_value = fake_iterator

    mock_client = MagicMock()
    mock_client.query.side_effect = [dry_run_job, exec_job]
    service = BigQueryService(settings=_make_settings(), client=mock_client)

    result = service.execute_query(f"SELECT order_id, revenue, created_at FROM `{DATASET}.orders`")

    assert mock_client.query.call_count == 2
    assert result.columns == ["order_id", "revenue", "created_at"]
    assert result.total_rows == 1
    assert result.rows[0]["revenue"] == 49.95
    assert result.rows[0]["created_at"] == "2025-01-15T10:30:00+00:00"


def test_execute_query_wraps_bigquery_api_error() -> None:
    mock_client = MagicMock()
    mock_client.query.side_effect = BadRequest("Unrecognized name: bogus_col")
    service = BigQueryService(settings=_make_settings(), client=mock_client)

    with pytest.raises(QueryExecutionError, match="bogus_col"):
        service.execute_query(f"SELECT bogus_col FROM `{DATASET}.orders`")