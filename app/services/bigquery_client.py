"""BigQuery Sandbox client with schema introspection and dry-run quota guard."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery

from app.core.config import Settings, get_settings
from app.core.exceptions import QueryExecutionError, QuotaLimitExceededError
from app.core.logging import get_logger
from app.services.sql_validator import validate_sql

logger = get_logger(__name__)


@dataclass(frozen=True)
class DryRunResult:
    """Estimated scan size from a free BigQuery dry-run."""

    sql: str
    estimated_bytes: int
    estimated_mb: float
    max_bytes: int


@dataclass(frozen=True)
class QueryResult:
    """Validated query output and execution telemetry."""

    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int
    bytes_processed: int
    execution_time_ms: float


@dataclass(frozen=True)
class TableSchemaInfo:
    """Metadata and sample rows for a single BigQuery table."""

    table_name: str
    full_table_id: str
    columns: list[dict[str, str]]
    sample_rows: list[dict[str, Any]]


def _serialize_value(value: Any) -> Any:
    """Convert BigQuery scalar types into JSON-safe Python values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class BigQueryService:
    """Read-only BigQuery runner protected by AST validation and dry-run caps."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: bigquery.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def client(self) -> bigquery.Client:
        if self._client is None:
            project = self.settings.gcp_project_id or None
            self._client = bigquery.Client(project=project)
        return self._client

    def dry_run_check(self, raw_sql: str) -> DryRunResult:
        """Validate SQL and run a free BigQuery dry-run to enforce byte caps."""
        validated_sql = validate_sql(
            raw_sql,
            allowed_dataset=self.settings.bigquery_dataset,
        )
        job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)

        try:
            job = self.client.query(validated_sql, job_config=job_config)
        except GoogleAPIError as exc:
            raise QueryExecutionError(f"BigQuery dry-run failed: {exc}") from exc

        estimated_bytes = int(job.total_bytes_processed or 0)
        max_bytes = self.settings.max_bytes_per_query

        if estimated_bytes > max_bytes:
            logger.warning(
                "Query blocked by free-tier quota guard",
                extra={
                    "extra_data": {
                        "estimated_bytes": estimated_bytes,
                        "max_bytes": max_bytes,
                    }
                },
            )
            raise QuotaLimitExceededError(estimated_bytes, max_bytes)

        return DryRunResult(
            sql=validated_sql,
            estimated_bytes=estimated_bytes,
            estimated_mb=round(estimated_bytes / (1024 * 1024), 3),
            max_bytes=max_bytes,
        )

    def execute_query(self, raw_sql: str, max_rows: int = 500) -> QueryResult:
        """Validate, dry-run check, and execute a read-only BigQuery query."""
        dry_run = self.dry_run_check(raw_sql)

        job_config = bigquery.QueryJobConfig(
            maximum_bytes_billed=self.settings.max_bytes_per_query,
            use_query_cache=True,
        )

        start = time.perf_counter()
        try:
            job = self.client.query(dry_run.sql, job_config=job_config)
            iterator = job.result(max_results=max_rows)
        except GoogleAPIError as exc:
            raise QueryExecutionError(f"BigQuery execution failed: {exc}") from exc

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        columns = [field.name for field in iterator.schema]
        rows = [
            {col: _serialize_value(row[col]) for col in columns}
            for row in iterator
        ]
        bytes_processed = int(job.total_bytes_processed or dry_run.estimated_bytes)

        logger.info(
            "BigQuery query executed",
            extra={
                "extra_data": {
                    "rows_returned": len(rows),
                    "bytes_processed": bytes_processed,
                    "execution_time_ms": elapsed_ms,
                }
            },
        )

        return QueryResult(
            sql=dry_run.sql,
            columns=columns,
            rows=rows,
            total_rows=int(iterator.total_rows or len(rows)),
            bytes_processed=bytes_processed,
            execution_time_ms=elapsed_ms,
        )

    def fetch_dataset_schema(self, sample_limit: int = 3) -> list[TableSchemaInfo]:
        """Introspect INFORMATION_SCHEMA and sample rows for the target dataset."""
        dataset = self.settings.bigquery_dataset.strip("` ")
        schema_sql = f"""
            SELECT table_name, column_name, data_type, is_nullable
            FROM `{dataset}.INFORMATION_SCHEMA.COLUMNS`
            ORDER BY table_name, ordinal_position
        """
        try:
            job = self.client.query(schema_sql)
            meta_rows = list(job.result())
        except GoogleAPIError as exc:
            raise QueryExecutionError(
                f"Failed to introspect schema for {dataset}: {exc}"
            ) from exc

        grouped: dict[str, list[dict[str, str]]] = {}
        for row in meta_rows:
            table_name = str(row["table_name"])
            grouped.setdefault(table_name, []).append(
                {
                    "name": str(row["column_name"]),
                    "type": str(row["data_type"]),
                    "nullable": str(row["is_nullable"]),
                }
            )

        tables: list[TableSchemaInfo] = []
        for table_name, columns in grouped.items():
            full_table_id = f"{dataset}.{table_name}"
            sample_rows: list[dict[str, Any]] = []
            if sample_limit > 0:
                sample_sql = f"SELECT * FROM `{full_table_id}` LIMIT {sample_limit}"
                try:
                    sample_res = self.execute_query(sample_sql, max_rows=sample_limit)
                    sample_rows = sample_res.rows
                except (QueryExecutionError, QuotaLimitExceededError):
                    sample_rows = []

            tables.append(
                TableSchemaInfo(
                    table_name=table_name,
                    full_table_id=full_table_id,
                    columns=columns,
                    sample_rows=sample_rows,
                )
            )
        return tables