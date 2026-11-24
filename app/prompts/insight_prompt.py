"""Prompt builder for generating concise executive insights from query results."""

from __future__ import annotations

import json
from typing import Any

INSIGHT_SYSTEM_PROMPT = """You are a sharp business data analyst.
Summarise the BigQuery result in 2-3 concise, grounded sentences.

Rules:
1. State the direct answer with exact figures from the rows provided.
2. Highlight the top/bottom performer, trend, or notable outlier if visible.
3. Never invent numbers or extrapolate beyond the provided rows.
4. Keep the tone crisp and direct without filler phrases.
"""


def build_insight_messages(
    question: str,
    sql: str,
    rows: list[dict[str, Any]],
    total_rows: int,
) -> list[dict[str, str]]:
    """Build chat messages to synthesise a plain-English summary of query results."""
    preview_rows = rows[:20]
    rows_json = json.dumps(preview_rows, indent=2, default=str)

    user_content = (
        f"User question: {question}\n\n"
        f"Executed SQL:\n```sql\n{sql}\n```\n\n"
        f"Returned {len(rows)} of {total_rows} total rows. Sample data:\n{rows_json}\n\n"
        "Write a concise 2-3 sentence analytical insight:"
    )
    return [
        {"role": "system", "content": INSIGHT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]