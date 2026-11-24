"""SQLite query result cache and structured telemetry store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings


def build_cache_key(
    question: str,
    dataset: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Create a deterministic SHA-256 cache key for a question and context."""
    normalized_q = " ".join(question.strip().lower().split())
    payload = {
        "question": normalized_q,
        "dataset": dataset.strip().lower(),
        "history": history[-4:] if history else [],
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CacheAndTelemetryService:
    """Manages local SQLite query caching and execution telemetry."""

    def __init__(
        self,
        settings: Settings | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.db_path = db_path or self.settings.sqlite_db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS query_cache (
                    cache_key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    question TEXT NOT NULL,
                    sql TEXT,
                    bytes_processed INTEGER DEFAULT 0,
                    execution_time_ms REAL DEFAULT 0.0,
                    llm_latency_ms REAL DEFAULT 0.0,
                    total_latency_ms REAL DEFAULT 0.0,
                    attempts INTEGER DEFAULT 1,
                    repaired INTEGER DEFAULT 0,
                    cached INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 1,
                    error_type TEXT,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0
                )
                """
            )

    def get_cached_response(self, cache_key: str) -> dict[str, Any] | None:
        """Return a cached query payload if it exists and has not expired."""
        ttl = self.settings.cache_ttl_seconds
        if ttl <= 0:
            return None

        with self._connect() as conn:
            row = conn.execute(
                "SELECT response_json, created_at FROM query_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()

            if row is None:
                return None

            age_seconds = time.time() - float(row["created_at"])
            if age_seconds > ttl:
                conn.execute("DELETE FROM query_cache WHERE cache_key = ?", (cache_key,))
                return None

            return dict(json.loads(row["response_json"]))

    def set_cached_response(self, cache_key: str, payload: dict[str, Any]) -> None:
        """Store or refresh a cached query response."""
        if self.settings.cache_ttl_seconds <= 0:
            return

        serialized = json.dumps(payload, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO query_cache (cache_key, response_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    response_json = excluded.response_json,
                    created_at = excluded.created_at
                """,
                (cache_key, serialized, time.time()),
            )

    def record_telemetry(
        self,
        *,
        question: str,
        sql: str = "",
        bytes_processed: int = 0,
        execution_time_ms: float = 0.0,
        llm_latency_ms: float = 0.0,
        total_latency_ms: float = 0.0,
        attempts: int = 1,
        repaired: bool = False,
        cached: bool = False,
        success: bool = True,
        error_type: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        """Insert a structured telemetry event for observability."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO telemetry_logs (
                    created_at, question, sql, bytes_processed, execution_time_ms,
                    llm_latency_ms, total_latency_ms, attempts, repaired, cached,
                    success, error_type, prompt_tokens, completion_tokens
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_iso,
                    question,
                    sql,
                    bytes_processed,
                    execution_time_ms,
                    llm_latency_ms,
                    total_latency_ms,
                    attempts,
                    int(repaired),
                    int(cached),
                    int(success),
                    error_type,
                    prompt_tokens,
                    completion_tokens,
                ),
            )

    def get_telemetry_summary(self, recent_limit: int = 10) -> dict[str, Any]:
        """Compute aggregate observability metrics and recent query history."""
        with self._connect() as conn:
            stats = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_queries,
                    COALESCE(SUM(success), 0) AS successful_queries,
                    COALESCE(SUM(cached), 0) AS cached_queries,
                    COALESCE(SUM(repaired), 0) AS repaired_queries,
                    COALESCE(AVG(total_latency_ms), 0.0) AS avg_latency_ms,
                    COALESCE(SUM(bytes_processed), 0) AS total_bytes_processed
                FROM telemetry_logs
                """
            ).fetchone()

            recent_rows = conn.execute(
                """
                SELECT
                    created_at, question, bytes_processed, total_latency_ms,
                    attempts, repaired, cached, success, error_type
                FROM telemetry_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (recent_limit,),
            ).fetchall()

        total = int(stats["total_queries"])
        successful = int(stats["successful_queries"])
        cached = int(stats["cached_queries"])
        repaired = int(stats["repaired_queries"])

        def _pct(part: int, whole: int) -> float:
            return round((part / whole) * 100, 2) if whole > 0 else 0.0

        return {
            "total_queries": total,
            "success_rate_pct": _pct(successful, total),
            "cache_hit_rate_pct": _pct(cached, total),
            "repair_rate_pct": _pct(repaired, successful),
            "avg_latency_ms": round(float(stats["avg_latency_ms"]), 2),
            "total_bytes_processed": int(stats["total_bytes_processed"]),
            "recent_queries": [dict(row) for row in recent_rows],
        }

