"""Streamlit conversational analytics dashboard for QueryLens."""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

from ui.components import format_bytes, render_chart_and_data

API_BASE_URL = os.getenv("QUERYLENS_API_URL", "http://localhost:8000").rstrip("/")

SAMPLE_QUESTIONS = [
    "What are the top 5 product categories by net revenue?",
    "Show monthly order volume and average order value (AOV) for the last 12 months.",
    "Which traffic source has the highest customer repeat purchase rate?",
    "Compare return rates across brands with at least 100 non-cancelled items.",
]


def fetch_backend_json(endpoint: str) -> dict[str, Any] | None:
    """GET helper for health and telemetry endpoints."""
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{API_BASE_URL}{endpoint}")
            resp.raise_for_status()
            return dict(resp.json())
    except httpx.HTTPError:
        return None


def post_query(
    question: str,
    history: list[dict[str, str]],
    use_cache: bool,
    generate_insight: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    """Send a natural language query to the FastAPI /query endpoint."""
    payload = {
        "question": question,
        "history": history,
        "use_cache": use_cache,
        "generate_insight": generate_insight,
    }
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{API_BASE_URL}/query", json=payload)
        if resp.status_code == 200:
            return dict(resp.json()), None
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        return None, f"API Error ({resp.status_code}): {detail}"
    except httpx.ConnectError:
        return None, (
            f"Cannot connect to QueryLens API at {API_BASE_URL}. "
            "Start it with `uvicorn app.main:app --reload --port 8000`."
        )
    except (httpx.HTTPError, ValueError) as exc:
        return None, f"Request failed: {exc}"


def render_sidebar() -> tuple[bool, bool]:
    """Render backend status, settings, sample questions, and telemetry."""
    with st.sidebar:
        st.title("QueryLens")
        st.caption("Natural Language Analytics for BigQuery Sandbox")

        health = fetch_backend_json("/health")
        if health:
            st.success("Backend Connected")
            st.markdown(f"**Dataset:** `{health.get('dataset', '')}`")
            st.markdown(f"**LLM:** `{health.get('model', '')}`")
            cap = format_bytes(int(health.get("max_bytes_per_query", 0)))
            st.markdown(f"**Quota Cap:** `{cap} / query`")
        else:
            st.error("Backend Offline")
            st.caption(f"Expected FastAPI at `{API_BASE_URL}`")

        st.divider()
        use_cache = st.toggle("Enable Query Cache", value=True)
        generate_insight = st.toggle("Generate Executive Insight", value=True)

        if st.button("Clear Conversation", use_container_width=True):
            st.session_state.messages = []
            st.session_state.sql_history = []
            st.rerun()

        st.divider()
        st.subheader("Sample Questions")
        for idx, sample in enumerate(SAMPLE_QUESTIONS):
            if st.button(sample, key=f"sample_{idx}", use_container_width=True):
                st.session_state.pending_question = sample

        telemetry = fetch_backend_json("/telemetry")
        if telemetry and telemetry.get("total_queries", 0) > 0:
            st.divider()
            st.subheader("Live Telemetry")
            st.metric("Total Queries", telemetry["total_queries"])
            st.metric("Success Rate", f"{telemetry['success_rate_pct']}%")
            st.metric("Cache Hit Rate", f"{telemetry['cache_hit_rate_pct']}%")
            st.metric("Avg Latency", f"{telemetry['avg_latency_ms']:.0f} ms")

    return use_cache, generate_insight


def main() -> None:
    st.set_page_config(
        page_title="QueryLens — BigQuery NL2SQL",
        page_icon=":bar_chart:",
        layout="wide",
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "sql_history" not in st.session_state:
        st.session_state.sql_history = []
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None

    use_cache, generate_insight = render_sidebar()

    st.header("QueryLens Analytics Chat")
    st.caption(
        "Ask questions in plain English. Every query is AST-validated read-only "
        "and dry-run checked against your free-tier BigQuery quota."
    )

    for idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            elif msg.get("error"):
                st.error(msg["error"])
            else:
                render_chart_and_data(msg["payload"], key_prefix=f"hist_{idx}")

    prompt = st.chat_input(
        "Ask a question about the dataset (e.g., Top 5 categories by revenue)..."
    )
    if st.session_state.pending_question:
        prompt = st.session_state.pending_question
        st.session_state.pending_question = None

    if prompt:
        clean_prompt = prompt.strip()
        if clean_prompt:
            st.session_state.messages.append({"role": "user", "content": clean_prompt})

            with st.chat_message("user"):
                st.markdown(clean_prompt)

            with st.chat_message("assistant"):
                with st.spinner("Generating, validating, and running BigQuery SQL..."):
                    payload, error = post_query(
                        question=clean_prompt,
                        history=st.session_state.sql_history,
                        use_cache=use_cache,
                        generate_insight=generate_insight,
                    )

                if error:
                    st.error(error)
                    st.session_state.messages.append({"role": "assistant", "error": error})
                elif payload is not None:
                    render_chart_and_data(
                        payload,
                        key_prefix=f"live_{len(st.session_state.messages)}",
                    )
                    st.session_state.messages.append(
                        {"role": "assistant", "payload": payload}
                    )
                    st.session_state.sql_history.append(
                        {"question": clean_prompt, "sql": payload.get("sql", "")}
                    )

            st.rerun()


if __name__ == "__main__":
    main()