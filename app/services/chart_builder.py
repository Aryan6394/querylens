"""Automatic chart recommendation and Plotly figure builder."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import plotly.graph_objects as go

_DATE_COL_HINTS = ("date", "month", "year", "week", "day", "quarter", "time", "period")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?([T\s]\d{2}:\d{2}.*)?$")
_ID_SUFFIXES = ("_id", "id")


@dataclass(frozen=True)
class ChartSpec:
    """Serializable chart specification returned by the API and rendered by Streamlit."""

    chart_type: str  # "kpi" | "line" | "bar" | "table" | "none"
    title: str = ""
    x: str | None = None
    y: list[str] = field(default_factory=list)
    kpis: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_date_column(col_name: str, values: list[Any]) -> bool:
    lower = col_name.lower()
    if any(hint in lower for hint in _DATE_COL_HINTS):
        return True
    sample = [v for v in values if v is not None][:5]
    return bool(sample) and all(
        isinstance(v, str) and bool(_ISO_DATE_RE.match(v)) for v in sample
    )


def _is_id_column(col_name: str) -> bool:
    lower = col_name.lower()
    return lower == "id" or lower.endswith(_ID_SUFFIXES)


def recommend_chart(
    columns: list[str],
    rows: list[dict[str, Any]],
    title: str = "",
) -> ChartSpec:
    """Infer the most readable chart type from query columns and row shapes."""
    if not columns or not rows:
        return ChartSpec(chart_type="none", title=title)

    numeric_cols: list[str] = []
    date_cols: list[str] = []
    category_cols: list[str] = []

    for col in columns:
        values = [row.get(col) for row in rows]
        non_null = [v for v in values if v is not None]
        if not non_null:
            continue

        if _is_date_column(col, non_null):
            date_cols.append(col)
        elif all(_is_numeric(v) for v in non_null):
            numeric_cols.append(col)
        else:
            category_cols.append(col)

    # Prefer non-ID numeric metrics when available
    metric_cols = [c for c in numeric_cols if not _is_id_column(c)] or numeric_cols

    # Single-row summary -> KPI cards
    if len(rows) == 1 and 1 <= len(columns) <= 4:
        kpis = [{"label": col, "value": rows[0].get(col)} for col in columns]
        return ChartSpec(chart_type="kpi", title=title, kpis=kpis)

    # Time series -> Line chart
    if date_cols and metric_cols and len(rows) >= 2:
        return ChartSpec(
            chart_type="line",
            title=title,
            x=date_cols[0],
            y=metric_cols[:2],
        )

    # Categorical breakdown -> Bar chart
    if category_cols and metric_cols and 2 <= len(rows) <= 30:
        return ChartSpec(
            chart_type="bar",
            title=title,
            x=category_cols[0],
            y=metric_cols[:2],
        )

    return ChartSpec(chart_type="table", title=title)


def build_plotly_figure(
    spec: ChartSpec | dict[str, Any],
    rows: list[dict[str, Any]],
) -> go.Figure | None:
    """Convert a ChartSpec and query rows into an interactive Plotly figure."""
    chart_spec = ChartSpec(**spec) if isinstance(spec, dict) else spec
    if not rows or chart_spec.chart_type not in {"line", "bar"}:
        return None
    if not chart_spec.x or not chart_spec.y:
        return None

    x_vals = [row.get(chart_spec.x) for row in rows]
    fig = go.Figure()

    for y_col in chart_spec.y:
        y_vals = [row.get(y_col) for row in rows]
        label = y_col.replace("_", " ").title()
        if chart_spec.chart_type == "line":
            fig.add_trace(
                go.Scatter(x=x_vals, y=y_vals, mode="lines+markers", name=label)
            )
        else:
            fig.add_trace(go.Bar(x=x_vals, y=y_vals, name=label))

    fig.update_layout(
        title=chart_spec.title or None,
        xaxis_title=chart_spec.x.replace("_", " ").title(),
        yaxis_title=chart_spec.y[0].replace("_", " ").title()
        if len(chart_spec.y) == 1
        else "Value",
        barmode="group",
        template="plotly_white",
        margin={"l": 40, "r": 20, "t": 50, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    )
    return fig