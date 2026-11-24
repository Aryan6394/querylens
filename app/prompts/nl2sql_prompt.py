"""Prompt builders for BigQuery Natural Language to SQL generation."""

from __future__ import annotations

SYSTEM_PROMPT = """You are an expert Google BigQuery SQL analyst.
Convert the user's business question into a single, accurate, read-only BigQuery SQL query.

Strict rules:
1. Return ONLY the raw BigQuery SQL query (no explanation, no prose).
2. Use ONLY tables and columns from the provided schema context.
3. Always fully qualify table names in backticks, e.g. `project.dataset.table`.
4. Never use SELECT *; select only the required columns to minimise bytes scanned.
5. Only generate read-only SELECT or WITH ... SELECT queries.
6. Use SAFE_DIVIDE for ratios/percentages and ROUND for currency or percentage outputs.
7. Include a reasonable LIMIT (e.g., LIMIT 100) unless the query already aggregates to few rows.
8.Only exclude 'Cancelled' or 'Returned' statuses for revenue, profit, AOV, or repeat-purchase
   metrics (or when explicitly asked)—never drop statuses on general counts or status breakdowns.
"""


def build_nl2sql_messages(
    question: str,
    context_text: str,
    dataset: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build chat messages for initial SQL generation."""
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history:
        for turn in history[-4:]:
            prev_q = turn.get("question", "").strip()
            prev_sql = turn.get("sql", "").strip()
            if prev_q and prev_sql:
                messages.append({"role": "user", "content": prev_q})
                messages.append({"role": "assistant", "content": prev_sql})

    user_content = (
        f"Target BigQuery dataset: `{dataset}`\n\n"
        f"{context_text}\n\n"
        f"User question: {question}\n\n"
        "Respond with only the BigQuery SQL query:"
    )
    messages.append({"role": "user", "content": user_content})
    return messages