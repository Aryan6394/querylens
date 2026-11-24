"""Custom exceptions for QueryLens guardrails and execution."""


class QueryLensError(Exception):
    """Base exception for all QueryLens application errors."""


class UnsafeSQLError(QueryLensError):
    """Raised when AST validation detects non-read-only or invalid SQL."""


class QuotaLimitExceededError(QueryLensError):
    """Raised when a BigQuery dry-run exceeds the configured byte cap."""

    def __init__(self, estimated_bytes: int, max_bytes: int) -> None:
        self.estimated_bytes = estimated_bytes
        self.max_bytes = max_bytes
        est_mb = estimated_bytes / (1024 * 1024)
        cap_mb = max_bytes / (1024 * 1024)
        super().__init__(
            f"Query blocked by quota guard: estimated scan is {est_mb:.2f} MB "
            f"(limit: {cap_mb:.2f} MB)."
        )


class QueryExecutionError(QueryLensError):
    """Raised when BigQuery rejects or fails to run a query."""


class LLMGenerationError(QueryLensError):
    """Raised when the local LLM fails to respond or returns malformed output."""