# QueryLens

![CI](https://github.com/Aryan6394/querylens/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.39%2B-FF4B4B?logo=streamlit&logoColor=white)
![BigQuery](https://img.shields.io/badge/Google%20BigQuery-Sandbox-4285F4?logo=googlebigquery&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Local%20Ollama-000000)
![Licence](https://img.shields.io/badge/Licence-MIT-green)

**QueryLens** is an end-to-end Natural Language to SQL (NL2SQL) analytics engine for **Google BigQuery** public datasets—built 100% on free, open-source tooling. Ask business questions in plain English to get RAG-grounded BigQuery SQL, dual AST + dry-run quota guardrails, self-healing error repair, interactive Plotly visualisations, CSV exports, and grounded executive insights.

![QueryLens Dashboard](docs/demo.jpg)

---

## Key Features

* **RAG-Grounded BigQuery SQL Generation:** Indexes live `INFORMATION_SCHEMA` table metadata (`n_schemas=7`), a curated business metric glossary (AOV, Net Revenue, Repeat Purchase Rate), and verified few-shot SQL pairs in persistent **ChromaDB** using local ONNX embeddings.
* **Dual Execution Guardrails (100% Block Rate):**
  * **Fail-Fast AST Safety (`sqlglot`):** Parses every generated query into a BigQuery Abstract Syntax Tree, strictly allowing read-only `SELECT` / `WITH ... SELECT` statements scoped to the configured dataset. Destructive DDL/DML (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `EXPORT`) fails fast immediately with zero retries (`HTTP 400`).
  * **Dry-Run Quota Cap:** Runs a free BigQuery dry-run before execution and rejects any query exceeding `MAX_BYTES_PER_QUERY` (default `1 GB`, `HTTP 422`) to protect BigQuery Sandbox quota.
* **Self-Healing SQL Repair Loop:** Automatically feeds BigQuery syntax and column-resolution errors back into a dedicated repair prompt for up to 3 retries (`50.0%` live recovery rate).
* **Dynamic Multi-Model Selector & In-App Model Installer:** Auto-discovers locally installed Ollama models (`GET /models`) so users can switch per query between faster (`1.5B` / `3B`) and more accurate (`7B+`) models directly from the Streamlit sidebar. Includes a **`+`** button next to the dropdown to pull new Ollama models via `POST /models/pull` and shows a guided prompt when only one model is installed.
* **Model-Scoped SQLite Caching & Telemetry:** Caches query responses using deterministic SHA-256 keys scoped by `(question, dataset, model, history)`, cutting repeat query latency from several seconds to **~1.5 ms** at **0 B** BigQuery scan while logging latency, token usage, cache hit rate, and bytes processed.
* **Auto-Charting & Executive Insights:** Automatically selects KPI cards, time-series line charts, bar charts, or data tables via Plotly, alongside an Executed SQL inspector, one-click CSV download, and plain-English insight summaries.

---

## Architecture

```text
User Question (Streamlit UI + Model Selector / '+' Installer)
                         │
                         ▼
               FastAPI Backend (:8000)
          ┌──────────────┴──────────────┐
          ▼                             ▼
  SQLite Cache & Telemetry       ChromaDB RAG Retriever
  (Model-scoped SHA-256 key)     (Schemas + Glossary + Few-Shot SQL)
          │                             │
          │ cache miss                  ▼
          │                 Local Ollama LLM (Selected Model)
          │                             │
          │                             ▼
          │                 sqlglot AST Validator (Fail-Fast)
          │                   └─ Blocks DDL/DML & external datasets
          │                             │
          │                             ▼
          │                 BigQuery Dry-Run Cost Guard (<= 1 GB)
          │                   └─ Auto-repair loop (up to 3 retries)
          │                             │
          │                             ▼
          │                 BigQuery Execution + Insight Summary
          │                             │
          └──────────────┬──────────────┘
                         ▼
          Plotly Auto-Chart + Data Table + SQL Inspector + CSV Export
```

---

## Target Dataset

By default, QueryLens connects to **`bigquery-public-data.thelook_ecommerce`**, a multi-table e-commerce warehouse (`orders`, `order_items`, `products`, `users`, `inventory_items`, `distribution_centers`, `events`).

**Sample Questions:**
* *"What are the top 5 product categories by net revenue?"*
* *"Show monthly order volume and average order value (AOV) for the last 12 months."*
* *"Which traffic source has the highest customer repeat purchase rate?"*
* *"Compare return rates across brands with at least 100 non-cancelled items."*

**Dataset-Agnostic Design:** Point `BIGQUERY_DATASET` in `.env` to any BigQuery public dataset (e.g., `bigquery-public-data.austin_bikeshare`) and re-run `python -m scripts.index_schema` to switch domains.

---

## Tech Stack (100% Free & Open Source)

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| **Backend API** | FastAPI, Pydantic v2 | Typed REST API (`/query`, `/models`, `/models/pull`, `/health`, `/schema`, `/telemetry`) |
| **Frontend UI** | Streamlit, Plotly | Conversational dashboard, model switcher, auto-charts, SQL inspector, CSV export |
| **Data Warehouse** | Google BigQuery Sandbox | Free 1 TiB/month public dataset queries, `INFORMATION_SCHEMA`, dry-runs |
| **Local LLM** | Ollama (`qwen2.5-coder:3b` + multi-model) | Zero-cost local NL2SQL generation, error repair, and insight summaries |
| **SQL Guardrail** | `sqlglot` | Dialect-aware BigQuery AST validation and dataset allowlisting |
| **RAG Store** | ChromaDB | Persistent local vector store with built-in ONNX CPU embeddings |
| **Cache & Logs** | SQLite | Model-scoped query caching and structured telemetry storage |
| **Testing & CI** | Pytest, Ruff, GitHub Actions | Automated unit/integration test suite and lint checks on every push |
| **Containers** | Docker, Docker Compose | Reproducible containerised backend + UI setup |

---

## API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Service status, active dataset, default LLM model, and byte quota cap |
| `POST` | `/query` | Runs NL2SQL pipeline (accepts optional per-request `model` override and `use_cache`) |
| `GET` | `/models` | Lists locally installed Ollama models (`/api/tags`) and recommended speed/accuracy presets |
| `POST` | `/models/pull` | Pulls a new Ollama model locally (`/api/pull`) and returns the refreshed model list |
| `GET` | `/schema` | Returns indexed table schema previews from local ChromaDB |
| `GET` | `/telemetry` | Aggregate success rate, cache hit rate, repair rate, average latency, and recent queries |

Interactive Swagger documentation is available at `http://localhost:8000/docs`.

---

## Quick Start

### Prerequisites
* **Python 3.11+**
* **[Ollama](https://ollama.com/download)** installed locally with at least one SQL model pulled (`ollama pull qwen2.5-coder:3b`)
* A free **Google BigQuery Sandbox** project (no credit card / billing account required) authenticated locally via:
  ```bash
  gcloud auth application-default login
  ```

### 1. Clone & Install
```bash
git clone [https://github.com/Aryan6394/querylens.git](https://github.com/Aryan6394/querylens.git)
cd querylens
python -m venv .venv
# Windows (PowerShell): .\.venv\Scripts\Activate.ps1
# macOS / Linux:        source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure `.env`
```bash
cp .env.example .env
```
Update `.env` with your BigQuery Sandbox project ID and default Ollama model:
```env
GCP_PROJECT_ID=your-sandbox-project-id
BIGQUERY_DATASET=bigquery-public-data.thelook_ecommerce
MAX_BYTES_PER_QUERY=1073741824

OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=qwen2.5-coder:3b
LLM_TIMEOUT_SECONDS=60

CHROMA_PERSIST_DIR=storage/chroma_db
SQLITE_DB_PATH=storage/querylens.db

MAX_REPAIR_RETRIES=3
CACHE_TTL_SECONDS=3600
LOG_LEVEL=INFO
```

### 3. Index Dataset Schema & Glossary
```bash
python -m scripts.index_schema
```

### 4. Run & Demonstrate Locally (Multi-Terminal Setup)

Open all terminals from the project root (`querylens/`) and start the services in order:

#### Step 1 — Start Ollama (Required if Not Already Running)
Verify that your local Ollama server is running and has your model available:
```bash
ollama list
```
* **If it returns a connection error** (e.g., `could not connect to ollama app`), open the **Ollama** desktop app from the Start menu / Applications folder, **or** start it manually in a dedicated terminal:
  ```bash
  ollama serve
  ```
* **If `qwen2.5-coder:3b` is missing**, pull it once:
  ```bash
  ollama pull qwen2.5-coder:3b
  ```

#### Step 2 — Terminal 1: FastAPI Backend (`http://localhost:8000`)
```bash
# Activate virtual environment first
# Windows (PowerShell): .\.venv\Scripts\Activate.ps1
# macOS / Linux:        source .venv/bin/activate

uvicorn app.main:app --reload --port 8000
```
* Wait for `Application startup complete.`
* Interactive Swagger docs: `http://localhost:8000/docs`

#### Step 3 — Terminal 2: Streamlit Dashboard (`http://localhost:8501`)
Keep Terminal 1 running, open a second terminal, and run:
```bash
# Activate virtual environment first
streamlit run ui/streamlit_app.py
```
* Opens at `http://localhost:8501` — confirm the sidebar shows a green **Backend Connected** badge.

#### Step 4 — Live Demo Walkthrough
1. **Run an analytics query:** Click *"What are the top 5 product categories by net revenue?"* in the sidebar to demonstrate RAG-grounded SQL generation, Plotly auto-charting, executive insight synthesis, and the **Executed SQL** tab.
2. **Demonstrate SQLite caching:** Re-run the same question with the same model to show `~1.5 ms` cache hits with `0 B` BigQuery scan.
3. **Demonstrate AST safety guardrails:** Enter *"Drop the orders table"* to show immediate fail-fast blocking via `sqlglot` (`HTTP 400`) without touching BigQuery.
4. **Demonstrate multi-model selection:** Switch models from the sidebar dropdown (e.g., `3B` for speed vs. `7B` for higher accuracy) and re-run a query to verify model-scoped caching, or click **`+`** next to the dropdown to download an additional Ollama model directly from the UI.

#### Step 5 — Terminal 3: Utility Terminal *(Optional)*
Keep both servers running and use a third terminal for re-indexing, linting, tests, and evaluation runs:
```bash
# Re-index ChromaDB (only needed after editing glossary/examples or clearing storage/)
python -m scripts.index_schema

# Lint, unit tests, and 12-case golden evaluation suite
ruff check app/ ui/ eval/ scripts/ tests/
pytest -v
python -m eval.run_eval
```

#### Local Services Overview

| Terminal | Service | Port / URL | Keep Open? |
| :--- | :--- | :--- | :--- |
| **Background / Dedicated** | Ollama (`ollama serve`) | `localhost:11434` | Yes |
| **Terminal 1** | FastAPI (`uvicorn`) | `http://localhost:8000/docs` | Yes |
| **Terminal 2** | Streamlit UI | `http://localhost:8501` | Yes |
| **Terminal 3** | Tests / Evals / Git | — | Optional |

> **Shutdown tip (Windows):** Close the `localhost:8501` browser tab first before pressing `Ctrl + C` in Terminal 1 and Terminal 2 so Streamlit's WebSocket closes immediately.

### 5. Run with Docker Compose *(Optional)*
```bash
docker compose up --build
```
* Frontend UI: `http://localhost:8501`
* Backend API Docs: `http://localhost:8000/docs`

---

## Evaluation & Benchmarks

Measured locally on CPU using `qwen2.5-coder:3b` against the 12-case golden dataset (`eval/golden_dataset.json`, covering Easy, Medium, Hard multi-table CTEs, and adversarial DDL/DML prompts):

| Metric | Target | Measured (`qwen2.5-coder:3b`, CPU) |
| :--- | :--- | :--- |
| **Execution Accuracy (EX)** | >= 85% | **80.0%** *(3/3 on Hard multi-table queries)* |
| **Valid SQL Rate (First Attempt)** | >= 90% | **80.0%** |
| **Self-Correction Recovery Rate** | >= 70% | **50.0%** |
| **Guardrail Block Rate** | 100% | **100.0%** |
| **Median End-to-End Latency** | < 4.0s | **7.32s** *(1.45 ms on SQLite cache hits)* |

### Iterative Engineering Improvements Caught by Evals
* **Guardrail Hardening (`50% -> 100%`):** Initial eval runs revealed that retrying `UnsafeSQLError` allowed the LLM to rewrite blocked `DROP TABLE` prompts into valid `SELECT` queries. Moving `UnsafeSQLError` to an immediate fail-fast path eliminated retries on destructive requests.
* **RAG Recall & Model Tuning (`40% -> 80% EX`):** Switching from a general chat model (`gemma3:4b`) to a SQL-tuned local model (`qwen2.5-coder:3b`), expanding ChromaDB schema retrieval coverage (`n_schemas=7`), and supporting column-projection matching in `eval/metrics.py` doubled Execution Accuracy while lowering latency.

---

## Project Structure

```text
querylens/
├── .github/workflows/ci.yml      # GitHub Actions: Ruff lint + Pytest on every push/PR
├── app/
│   ├── api/
│   │   ├── routes.py             # /query, /models, /models/pull, /health, /schema, /telemetry
│   │   └── schemas.py            # Pydantic v2 request/response contracts
│   ├── core/
│   │   ├── config.py             # Pydantic Settings loading .env
│   │   ├── exceptions.py         # UnsafeSQLError, QuotaLimitExceededError, etc.
│   │   └── logging.py            # Structured JSON logging
│   ├── prompts/
│   │   ├── nl2sql_prompt.py      # BigQuery SQL generation prompts
│   │   ├── repair_prompt.py      # Self-healing error-trace repair prompts
│   │   └── insight_prompt.py     # Executive insight summarisation prompts
│   ├── services/
│   │   ├── bigquery_client.py    # INFORMATION_SCHEMA loader, dry-run cost guard, runner
│   │   ├── sql_validator.py      # sqlglot AST read-only & dataset allowlist validator
│   │   ├── rag_retriever.py      # ChromaDB schema + glossary + few-shot SQL retriever
│   │   ├── llm_client.py         # Ollama client (chat override, /api/tags, /api/pull)
│   │   ├── nl2sql_agent.py       # End-to-end orchestration & 3-retry repair loop
│   │   ├── chart_builder.py      # Automatic Plotly chart & KPI card selector
│   │   └── cache_service.py      # Model-scoped SQLite cache & telemetry store
│   └── main.py                   # FastAPI application factory & lifespan hooks
├── data/
│   ├── business_glossary.json    # Business metric definitions
│   └── few_shot_examples.json    # Verified NL-to-BigQuery-SQL pairs
├── docs/
│   └── demo.jpg                  # Dashboard screenshot
├── eval/
│   ├── golden_dataset.json       # 12 curated business + adversarial test cases
│   ├── metrics.py                # Execution Accuracy & column-projection matcher
│   └── run_eval.py               # Automated benchmark runner
├── scripts/
│   └── index_schema.py           # CLI indexer for BigQuery schema & glossary
├── tests/                        # Unit & FastAPI integration test suite
├── ui/
│   ├── components.py             # KPI metrics, Plotly renderer, SQL inspector, CSV export
│   └── streamlit_app.py          # Chat UI, model dropdown, '+' model installer, telemetry
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Engineering Trade-Offs & Roadmap

* **Why `sqlglot` AST parsing instead of regex?** Regex filters are easily bypassed by CTEs, comments, or nested clauses. Parsing into a BigQuery AST guarantees only read-only query nodes referencing the allowed dataset execute.
* **Why BigQuery dry-runs before execution?** BigQuery bills by bytes scanned. Dry-runs are free and return exact scan estimates before execution starts.
* **Why model-scoped cache keys?** Including the selected model name in the SHA-256 cache key guarantees that switching from a fast `3B` model to a more accurate `7B` model regenerates SQL instead of returning stale results from the smaller model.

### Roadmap
* [ ] **Hybrid Model Routing:** Use a larger SQL-specialised model for query generation and a lightweight model for executive insight summarisation to cut latency without losing SQL accuracy.
* [ ] **Ambiguity Clarification Prompts:** Ask a brief follow-up question when a user's business metric or time range is underspecified.
* [ ] **Custom Business Glossary Upload:** Allow uploading domain-specific metric definitions directly through the Streamlit UI.
* [ ] **Cloud Run Deployment Workflow:** Automated container deployment via GitHub Actions.

---

## Licence

MIT Licence — see [LICENSE](LICENSE) for details.