# QueryLens — Natural Language Analytics Engine for Google BigQuery
![CI](https://github.com/Aryan6394/querylens/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.10+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688)
![Streamlit](https://img.shields.io/badge/Streamlit-Frontend-FF4B4B)
![BigQuery](https://img.shields.io/badge/BigQuery-Sandbox_(Free)-4285F4)
![Ollama](https://img.shields.io/badge/LLM-Local_Ollama-111111)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED)

QueryLens is an end-to-end **Natural Language to SQL (NL2SQL)** analytics engine that converts plain-English business questions into validated, quota-checked Google BigQuery SQL, executes them against public datasets, and returns interactive Plotly visualisations with executive insights.

Built entirely on a **zero-cost stack** (BigQuery Sandbox + local Ollama + local ChromaDB + SQLite), QueryLens focuses on production engineering guardrails rather than a thin LLM wrapper: AST-level read-only enforcement, dry-run scan caps, RAG-based schema grounding, self-healing error repair, and an automated Execution Accuracy evaluation suite.

---

## Key Features

### 1. Grounded NL2SQL & Schema Intelligence
* **Dynamic Metadata Introspection:** Reads live table schemas, column types, and sample rows from BigQuery `INFORMATION_SCHEMA` to reduce column hallucination.
* **Local RAG Schema & Glossary Retrieval:** Indexes table schemas, business metric definitions (*Net Revenue*, *GMV*, *AOV*, *Return Rate*, *Repeat Purchase Rate*, *Gross Margin*), and verified few-shot SQL queries in persistent ChromaDB using built-in ONNX CPU embeddings.
* **Multi-Turn Follow-Ups:** Preserves recent question-to-SQL history so users can refine queries conversationally.

### 2. Safety & Free-Tier Quota Guardrails
* **AST-Level Read-Only Enforcement (`sqlglot`):** Parses every generated query into a BigQuery Abstract Syntax Tree before execution, permitting only single `SELECT` / `WITH` statements scoped to the allowlisted dataset and failing fast on all DDL/DML (`DROP`, `DELETE`, `INSERT`, `UPDATE`, `ALTER`, `MERGE`, `TRUNCATE`).
* **BigQuery Dry-Run Quota Guard:** Runs every query with `dry_run=True` first to estimate bytes scanned and blocks queries exceeding the configurable cap (default: `1 GB`) to protect the free `1 TiB/month` BigQuery Sandbox quota.
* **Self-Healing Repair Loop:** Captures BigQuery syntax, schema, or quota errors and feeds them back to the LLM to repair and re-validate SQL automatically (up to 3 retries), while never retrying unsafe DDL/DML requests.

### 3. Automated Visualisation & Observability
* **Smart Chart Builder:** Infers result shapes to automatically render KPI metric cards, time-series line charts, grouped bar charts, or interactive data tables via Plotly.
* **Executive Insight Synthesis:** Generates concise 2–3 sentence takeaways grounded strictly in returned rows.
* **SQLite Caching & Telemetry:** Caches deterministic responses locally (`1.45 ms` cache hits with `0 B` scanned) and exposes latency, bytes processed, cache hit rate, and self-correction metrics via `/telemetry`.
* **Automated Evaluation Suite:** Grades the live pipeline against a 12-case golden dataset (`eval/golden_dataset.json`) using column-alias agnostic **Execution Accuracy (EX)** and adversarial guardrail checks.

---

## System Architecture

```text
+------------------+        +----------------------------------------------------+
|   Streamlit UI   | -----> |                  FastAPI Backend                   |
|  - Chat & Charts | <----- |                                                    |
|  - SQL Inspector |        |  1. RAG Retriever (ChromaDB Schema + Glossary)     |
|  - CSV Export    |        |  2. NL2SQL Generator (Local Ollama LLM)            |
+------------------+        |  3. SQL Safety Validator (sqlglot AST Read-Only)   |
                            |  4. Free-Tier Quota Guard (BigQuery Dry-Run)       |
                            |  5. Self-Healing Retry Loop (Max 3 Retries)        |
                            |  6. Auto-Chart Spec & Insight Generator            |
                            +-------------------------+--------------------------+
                                                      |
                        +-----------------------------+-----------------------------+
                        |                             |                             |
                        v                             v                             v
             +--------------------+       +----------------------+       +--------------------+
             |  BigQuery Sandbox  |       |   Local ChromaDB     |       |   Local SQLite     |
             | (Public Datasets)  |       | (Schemas + Examples) |       | (Cache + Telemetry)|
             +--------------------+       +----------------------+       +--------------------+
```

---

## Tech Stack (100% Free & Open Source)

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| **Backend API** | FastAPI, Pydantic v2 | Typed REST API (`/query`, `/health`, `/schema`, `/telemetry`) |
| **Frontend UI** | Streamlit, Plotly | Conversational dashboard, auto-charts, SQL inspector, CSV export |
| **Data Warehouse** | Google BigQuery Sandbox (`google-cloud-bigquery`) | Free 1 TiB/month public dataset queries, `INFORMATION_SCHEMA`, dry-runs |
| **Local LLM** | Ollama (`qwen2.5-coder:3b`) | Zero-cost local NL2SQL generation, error repair, and insight summaries |
| **SQL Guardrail** | `sqlglot` | Dialect-aware BigQuery AST validation and dataset allowlisting |
| **RAG Store** | ChromaDB | Persistent local vector store with built-in ONNX CPU embeddings |
| **Cache & Logs** | SQLite | Deterministic query caching and structured telemetry storage |
| **Testing & CI** | Pytest, Ruff, GitHub Actions | 35 automated unit/integration tests and lint checks on every push |
| **Containers** | Docker, Docker Compose | One-command containerised backend + UI setup |

---

## Quick Start

### Prerequisites
* Python 3.10+
* [Ollama](https://ollama.com/download) with a local SQL model pulled (`ollama pull qwen2.5-coder:3b` or `qwen2.5-coder:7b`)
* Free **BigQuery Sandbox** project (no credit card / no billing account) authenticated locally via `gcloud auth application-default login`

### 1. Install
```bash
git clone [https://github.com/](https://github.com/)Aryan6394/querylens.git
cd querylens
python -m venv .venv
# Windows: .venv\Scripts\activate  |  macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure `.env`
```bash
cp .env.example .env
```
Set your Sandbox project ID and Ollama model in `.env`:
```env
GCP_PROJECT_ID=your-sandbox-project-id
BIGQUERY_DATASET=bigquery-public-data.thelook_ecommerce
MAX_BYTES_PER_QUERY=1073741824
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=qwen2.5-coder:3b
```

### 3. Index Dataset Context
```bash
python -m scripts.index_schema
```

### 4. Run Backend & Frontend
### 4. Run Locally (Multi-Terminal Setup)

Open all terminals from the project root (`querylens/`) and start the services in order:

#### Prerequisite — Ollama (Local LLM)
Ensure the **Ollama** app is running in the background (or start it manually in a dedicated terminal):
```bash
ollama serve
```

#### Terminal 1 — FastAPI Backend (`http://localhost:8000`)
```bash
# Activate virtual environment (Windows: .\.venv\Scripts\Activate.ps1 | macOS/Linux: source .venv/bin/activate)
uvicorn app.main:app --reload --port 8000
```
* Wait for `Application startup complete.`
* Interactive Swagger API docs: `http://localhost:8000/docs`

#### Terminal 2 — Streamlit UI (`http://localhost:8501`)
Keep Terminal 1 running, open a second terminal, and run:
```bash
# Activate virtual environment
streamlit run ui/streamlit_app.py
```
* Opens at `http://localhost:8501` — confirm the sidebar shows a green **Backend Connected** badge.

#### Terminal 3 — Utility Terminal *(Optional)*
Keep both servers running and use a third terminal for indexing, tests, and evaluation runs:
```bash
# Re-index ChromaDB (only needed after editing glossary/examples or clearing storage/)
python -m scripts.index_schema

# Lint, unit tests, and 12-case evaluation suite
ruff check app/ ui/ eval/ scripts/ tests/
pytest -v
python -m eval.run_eval
```

#### Local Services Overview

| Terminal | Service | Port / URL | Keep Open? |
| :--- | :--- | :--- | :--- |
| **Background / App** | Ollama (`qwen2.5-coder:3b`) | `localhost:11434` | Yes |
| **Terminal 1** | FastAPI (`uvicorn`) | `http://localhost:8000/docs` | Yes |
| **Terminal 2** | Streamlit UI | `http://localhost:8501` | Yes |
| **Terminal 3** | Tests / Evals / Git | — | Optional |

Press `Ctrl + C` in Terminal 1 and Terminal 2 to stop the servers.