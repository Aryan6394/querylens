"""Prompt builder for self-healing SQL repair after validation or execution errors."""

from __future__ import annotations

REPAIR_SYSTEM_PROMPT = """You are a senior Google BigQuery SQL debugger.
Fix the failed SQL query based on the error message and schema context.

Strict rules:
1. Return ONLY the corrected BigQuery SQL query (no markdown prose or explanation).
2. Ensure all table and column names exist in the provided schema.
3. Keep the query strictly read-only (SELECT or WITH ... SELECT).
4. If the error mentions a quota or byte limit, select fewer columns or add tighter date filters.
"""


def build_repair_messages(
    question: str,
    failed_sql: str,
    error_message: str,
    context_text: str,
    dataset: str,
) -> list[dict[str, str]]:
    """Build chat messages asking the LLM to repair a failed BigQuery query."""
    user_content = (
        f"Target BigQuery dataset: `{dataset}`\n\n"
        f"{context_text}\n\n"
        f"Original user question: {question}\n\n"
        f"Failed SQL:\n```sql\n{failed_sql}\n```\n\n"
        f"Error returned:\n{error_message}\n\n"
        "Return only the corrected BigQuery SQL query:"
    )
    return [
        {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]