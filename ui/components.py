"""Reusable Streamlit UI components for QueryLens."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app.services.chart_builder import build_plotly_figure


def format_bytes(num_bytes: int) -> str:
    """Format byte counts into a readable KB/MB/GB string."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024**2:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024**3:
        return f"{num_bytes / (1024**2):.2f} MB"
    return f"{num_bytes / (1024**3):.2f} GB"


def render_metadata_badges(payload: dict[str, Any]) -> None:
    """Display latency, bytes scanned, cache status, and self-repair indicators."""
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Latency", f"{payload.get('total_latency_ms', 0):.0f} ms")
    col2.metric("Bytes Scanned", format_bytes(int(payload.get("bytes_processed", 0))))
    col3.metric("Rows Returned", f"{len(payload.get('rows', []))} / {payload.get('total_rows', 0)}")

    if payload.get("cached"):
        status_label = "Cache Hit"
    elif payload.get("repaired"):
        status_label = f"Self-Healed ({payload.get('attempts', 1)} tries)"
    else:
        status_label = "Live Query"
    col4.metric("Execution Mode", status_label)


def render_chart_and_data(payload: dict[str, Any], key_prefix: str) -> None:
    """Render KPI cards, Plotly chart, data table, SQL inspector, and CSV export."""
    insight = payload.get("insight", "").strip()
    if insight:
        st.markdown(insight)

    render_metadata_badges(payload)

    rows: list[dict[str, Any]] = payload.get("rows", [])
    chart_spec: dict[str, Any] = payload.get("chart") or {}
    chart_type = chart_spec.get("chart_type", "none")

    if chart_type == "kpi" and chart_spec.get("kpis"):
        kpis = chart_spec["kpis"]
        cols = st.columns(len(kpis))
        for col, item in zip(cols, kpis, strict=False):
            label = str(item.get("label", "")).replace("_", " ").title()
            val = item.get("value")
            formatted = f"{val:,.2f}" if isinstance(val, float) else str(val)
            col.metric(label, formatted)
    elif chart_type in {"line", "bar"} and rows:
        fig = build_plotly_figure(chart_spec, rows)
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True, key=f"chart_{key_prefix}")

    if rows:
        df = pd.DataFrame(rows)
        tab_data, tab_sql = st.tabs(["Data Table", "Executed SQL"])
        with tab_data:
            st.dataframe(df, use_container_width=True, hide_index=True)
            csv_bytes = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download CSV",
                data=csv_bytes,
                file_name=f"querylens_{key_prefix}.csv",
                mime="text/csv",
                key=f"csv_{key_prefix}",
            )
        with tab_sql:
            st.code(payload.get("sql", ""), language="sql")
    elif payload.get("sql"):
        with st.expander("Executed SQL", expanded=False):
            st.code(payload.get("sql", ""), language="sql")