# 📊 Business Process Mining & Optimization Platform

> An AI-powered analytics platform that discovers actual process flows, detects bottlenecks, predicts delays, and generates optimization recommendations from enterprise event logs.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=flat-square&logo=python)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-13%2B-336791?style=flat-square&logo=postgresql)
![PM4Py](https://img.shields.io/badge/PM4Py-2.7%2B-orange?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35-FF4B4B?style=flat-square&logo=streamlit)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

---

## 📌 Table of Contents

- [Overview](#overview)
- [Business Problem](#business-problem)
- [Solution](#solution)
- [Live Demo](#live-demo)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Core Modules](#core-modules)
- [Tech Stack](#tech-stack)
- [Dataset](#dataset)
- [Getting Started](#getting-started)
- [ETL Pipeline](#etl-pipeline)
- [Dashboard](#dashboard)
- [API](#api)
- [Roadmap](#roadmap)
- [Future Enhancements](#future-enhancements)

---

## Overview

Traditional organizations define ideal workflows on paper, but actual execution frequently differs due to delays, rework loops, bottlenecks, and manual interventions. This platform bridges that gap.

The **Business Process Mining & Optimization Platform** ingests raw event logs from enterprise systems, reconstructs the actual process flow using the PM4Py library, computes KPIs, identifies deviations from the ideal path, and surfaces bottlenecks — all through an interactive Streamlit dashboard and a FastAPI backend.

**Built in three phases:**

| Phase | Focus | Status |
|---|---|---|
| Phase 1 | ETL · Process Discovery · KPIs · Variants · Dashboard · API | ✅ Complete |
| Phase 2 | ML Predictions · AI Recommendations · React Frontend | 🔄 In Progress |
| Phase 3 | GenAI Copilot · RAG Assistant · Real-time Monitoring | 🗓 Planned |

---

## Business Problem

Organizations face recurring operational challenges that are difficult to diagnose without data:

- **Delayed approvals** — cases sitting idle between process steps
- **Inefficient workflows** — redundant steps adding no value
- **SLA violations** — tickets breaching resolution time thresholds
- **Process bottlenecks** — specific activities causing systemic slowdowns
- **High operational costs** — rework loops consuming team capacity
- **Lack of visibility** — business leaders relying on assumptions, not data

Standard BI tools show aggregated metrics but cannot reveal *how* the process actually executes case by case.

---

## Solution

This platform applies **process mining** — an IEEE-standard analytical discipline — to reconstruct and analyse the true process from event log data.

**What it delivers:**

- Discovers the actual process flow (not the assumed one) as a visual Sankey diagram
- Computes cycle time, wait time, SLA breach rate, escalation rate, throughput
- Identifies the top process variants and how often each occurs
- Compares the ideal (happy) path against all deviating cases
- Ranks bottleneck activities by average wait time
- Detects rework loops — cases that visit the same step more than once
- *(Phase 2)* Predicts which cases are at risk of SLA breach before it happens
- *(Phase 3)* Answers natural language questions: "Why are tickets being escalated?"

---

## Live Demo

```bash
# Clone and run locally — see Getting Started below
streamlit run dashboard/app.py
```

> Screenshots below show Phase 1 dashboard on the helpdesk dataset (1M tickets).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Data Sources                            │
│   CSV / Excel · XES files · ERP · CRM · HRMS · Helpdesk    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  ETL Pipeline (etl/)                        │
│   Extract → Validate → Transform → Load → PostgreSQL        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│              Process Mining Engine                          │
│   process_mining/discovery.py  ·  process_mining/variants  │
│   PM4Py DFG · Heuristic Miner · Variant Analysis           │
└────────────────────────┬───────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│                  Analytics Layer                            │
│   analytics/kpis.py  ·  analytics/bottlenecks.py           │
│   Cycle Time · SLA · Escalation · Throughput · Rework      │
└──────────────┬─────────────────────────┬───────────────────┘
               │                         │
               ▼                         ▼
┌──────────────────────┐    ┌────────────────────────────────┐
│  Streamlit Dashboard │    │       FastAPI Backend          │
│  dashboard/app.py    │    │       api/main.py              │
│  Sankey · KPI Cards  │    │  /api/kpis · /api/variants     │
│  Heatmap · Variants  │    │  /api/graph · /api/cases       │
└──────────────────────┘    └────────────────────────────────┘
```

---

## Project Structure

```
BPMO/
│
├── .env                          # DB credentials (never committed)
├── .streamlit/
│   └── config.toml               # Streamlit light theme config
├── config.yaml                   # All platform configuration
├── config_loader.py              # Single import point for config + env
├── requirements.txt
├── README.md
│
├── data/
│   └── raw/                      # Raw dataset files
│       └── helpdesk_tickets.csv
│
├── database/
│   └── schema.sql                # PostgreSQL table definitions
│
├── etl/                          # Phase 1 — Step 1
│   ├── extractor.py              # Read CSV / XES / Excel / JSON
│   ├── validator.py              # Column checks · null checks · row count
│   ├── transformer.py            # Clean · enrich · compute features
│   ├── loader.py                 # Write to PostgreSQL in chunks
│   └── pipeline.py               # Orchestrator: Extract→Validate→Transform→Load
│
├── process_mining/               # Phase 1 — Steps 2 & 4
│   ├── discovery.py              # DFG · Heuristic Miner · PM4Py
│   └── variants.py               # Variant frequency · ideal vs actual
│
├── analytics/                    # Phase 1 — Step 3
│   ├── kpis.py                   # Cycle time · SLA · escalation · throughput
│   └── bottlenecks.py            # Wait times · slow transitions · rework
│
├── dashboard/                    # Phase 1 — Step 5
│   ├── app.py                    # Streamlit entry point
│   └── components.py             # Reusable Plotly chart components
│
├── api/                          # Phase 1 — Step 6
│   ├── main.py                   # FastAPI application
│   └── routes.py                 # All REST endpoints
│
└── tests/
    └── __init__.py
```

---

## Core Modules

### 1. ETL Pipeline (`etl/`)

Converts raw ticket data into a standardised event log stored in PostgreSQL.

The helpdesk CSV has one row per ticket. Process mining requires one row per event. The transformer **explodes** each ticket into 2–3 events:

```
Ticket #1001  →  ticket opened    (@ Date_Created)
              →  ticket escalated (@ Date_Created + 1hr)   [if escalated]
              →  ticket resolved  (@ Date_Resolved)         [if resolved]
              →  status: open     (@ Date_Created + 2hrs)   [if still open]
```

**Output tables:**

| Table | Rows | Description |
|---|---|---|
| `event_log` | ~2.5M | One row per event with case_id, activity, timestamp, wait_time_mins, cycle_time_mins |
| `cases` | 1M | One summary row per ticket — start/end time, cycle time, escalation flag |
| `etl_runs` | N | Audit trail of every pipeline execution |

### 2. Process Discovery Engine (`process_mining/discovery.py`)

Reads the event log from PostgreSQL and runs two PM4Py algorithms:

- **DFG (Directly-Follows Graph)** — counts every activity → activity transition. Becomes the Sankey diagram on the dashboard.
- **Heuristic Miner** — filters noise from the DFG, showing only dominant process paths.

### 3. KPI Engine (`analytics/kpis.py`)

Computes all headline metrics with optional filters by source, priority, and category:

| KPI | Formula |
|---|---|
| Avg cycle time | Mean of (last_event_timestamp − first_event_timestamp) per case |
| SLA breach rate | % of cases where resolution_time_hrs > threshold (default: 48h) |
| Escalation rate | % of cases where escalated = True |
| Resolution rate | % of cases that reached 'ticket resolved' activity |
| Throughput | Resolved cases per day |

### 4. Bottleneck Detection (`analytics/bottlenecks.py`)

Four analyses in one module:

- **Activity wait times** — avg/P90/max gap before each activity starts
- **Slow transitions** — ranked table of activity → activity handoff durations
- **Rework loops** — cases that visit the same activity more than once
- **Priority comparison** — are Critical tickets faster than Low priority ones?

### 5. Variant Analysis (`process_mining/variants.py`)

Identifies every unique process path and its frequency:

- **Top variants** — ranked frequency table with cycle time per variant
- **Ideal vs actual** — detects the happy path and measures deviation rate
- **Priority/category breakdown** — which paths do Critical tickets take?
- **Deviating cases** — individual cases that didn't follow the ideal path

### 6. Streamlit Dashboard (`dashboard/`)

Nine interactive sections, all filtered by source / priority / category:

```
📈 KPI Cards          →  5 headline metrics
🔄 Process Flow       →  Sankey diagram of actual flow
🐌 Bottlenecks        →  Horizontal bar chart of wait times
🧩 Variant Analysis   →  Ideal vs actual + variant table
📦 Volume Analysis    →  Priority donut + category bar
⏱ Time Analysis      →  Cycle time P50/P75/P90/P95 + daily trend
🗓 Heatmap            →  Events by hour-of-day and weekday
🐢 Slow Transitions   →  Table of slowest handoffs
⚠️ Deviating Cases   →  Cases that took unusual paths
```

---

## Tech Stack

### Phase 1 (current)

| Layer | Technology |
|---|---|
| Language | Python 3.9+ |
| Data processing | Pandas · NumPy |
| Process mining | PM4Py · NetworkX |
| Database | PostgreSQL 13+ |
| ORM / connection | SQLAlchemy · psycopg2 |
| Dashboard | Streamlit 1.35 |
| Visualisation | Plotly |
| API | FastAPI · Uvicorn |
| Config | python-dotenv · PyYAML |

### Phase 2 (planned)

| Layer | Technology |
|---|---|
| ML models | Scikit-learn · XGBoost · LightGBM |
| LLM | Gemini 2.5 Flash · NVIDIA Llama 3.3 70B NIM |
| Frontend | React.js |

### Phase 3 (planned)

| Layer | Technology |
|---|---|
| Vector DB | ChromaDB |
| RAG framework | LangChain |
| Document parsing | PyPDF · python-docx |
| Streaming | Kafka / Webhooks |

---

## Dataset

Phase 1 uses a synthetic helpdesk ticket dataset (1,000,000 tickets) with the following schema:

| Column | Type | Description |
|---|---|---|
| Ticket_ID | string | Unique ticket identifier |
| Date_Created | datetime | When the ticket was opened |
| Date_Resolved | datetime | When the ticket was closed (null if open) |
| Category | string | Software · Hardware · Network · HR · Security · Access |
| Subcategory | string | Specific issue type |
| Priority | string | Critical · High · Medium · Low |
| Status | string | Open · In Progress · On Hold · Pending · Resolved |
| Assigned_Team | string | Team responsible for the ticket |
| Escalated | boolean | Whether the ticket was escalated |
| Resolution_Time_Hrs | float | Hours from open to close |

**Other supported datasets:**

- [BPI Challenge 2012](https://data.4tu.nl) — Loan application process (262K events)
- [BPI Challenge 2017](https://data.4tu.nl) — Credit application (1.2M events)
- [BPI Challenge 2019](https://data.4tu.nl) — Purchase order handling (1.5M events)
- [Sepsis Cases](https://data.4tu.nl) — Hospital patient pathways (15K events)

---

## Getting Started

### Prerequisites

- Python 3.9+
- PostgreSQL 13+ running locally
- Git

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/business-process-mining.git
cd business-process-mining
```

### 2. Install dependencies (Phase 1 only)

```bash
pip install pandas==2.2.2 numpy==1.26.4 sqlalchemy==2.0.30 psycopg2-binary==2.9.9 \
            python-dotenv==1.0.1 pyyaml==6.0.1 openpyxl==3.1.2 pm4py==2.7.11 \
            networkx==3.3 fastapi==0.111.0 uvicorn==0.30.1 pydantic==2.7.1 \
            python-multipart==0.0.9 streamlit==1.35.0 plotly==5.22.0
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your PostgreSQL credentials
```

```env
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=process_mining_db
```

### 4. Create the database

```bash
psql -U postgres -c "CREATE DATABASE process_mining_db;"
psql -U postgres -d process_mining_db -f database/schema.sql
```

### 5. Place your dataset

```bash
# Copy your helpdesk CSV to:
data/raw/helpdesk_tickets.csv
```

### 6. Run the ETL pipeline

```bash
python -m etl.pipeline
```

Expected output:
```
[ETL] Extracted 1,000,000 raw rows
[ETL] Validation passed
[ETL] Output events: 2,499,911
[ETL] Loaded 2,499,911 rows, 1,000,000 cases
```

### 7. Test individual modules

```bash
python -m process_mining.discovery    # verify process discovery
python -m analytics.kpis              # verify KPI computation
python -m analytics.bottlenecks       # verify bottleneck detection
python -m process_mining.variants     # verify variant analysis
```

### 8. Launch the dashboard

```bash
streamlit run dashboard/app.py
# Opens at http://localhost:8501
```

### 9. Start the API server

```bash
uvicorn api.main:app --reload --port 8000
# Swagger UI at http://localhost:8000/docs
```

---

## ETL Pipeline

The pipeline runs in four sequential steps:

```
Extract  →  reads raw file (CSV / XES / Excel / JSON)
   ↓
Validate →  checks required columns, nulls, row count, date format
   ↓
Transform → renames columns, parses timestamps, explodes tickets
            into events, computes wait_time_mins + cycle_time_mins
   ↓
Load     →  bulk-writes to PostgreSQL in 50,000-row chunks
            using a staging table for the cases upsert (fast)
```

Re-running the pipeline on the same file is safe — existing data is not duplicated. The `etl_runs` table records every execution with row counts, case counts, duration, and status for auditability.

---

## Dashboard

The dashboard reads entirely from PostgreSQL — it never touches a raw file. Every section recomputes instantly when the sidebar filters change. Results are cached per filter combination using `@st.cache_data`.

**Sidebar filters:**
- Dataset (source)
- Priority: All · Critical · High · Medium · Low
- Category: All · Software · Hardware · Network · HR
- Top N variants (slider)
- Min edge count for process flow chart (slider)

---

## API

Once the FastAPI server is running, all data is available as REST endpoints:

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/kpis` | All KPIs with optional filters |
| GET | `/api/variants` | Top process variants |
| GET | `/api/graph` | DFG edges for process flow chart |
| GET | `/api/cases` | Paginated case list |
| GET | `/api/bottlenecks` | Bottleneck activity ranking |
| POST | `/api/etl/run` | Trigger ETL pipeline run |

Interactive documentation at `http://localhost:8000/docs`

---

## Roadmap

### ✅ Phase 1 — Core Platform
- [x] ETL pipeline (CSV · XES · PostgreSQL)
- [x] Process discovery engine (DFG · Heuristic Miner)
- [x] KPI engine (cycle time · SLA · escalation · throughput)
- [x] Bottleneck detection (wait times · transitions · rework)
- [x] Variant analysis (ideal vs actual · priority breakdown)
- [x] Streamlit dashboard (9 interactive sections)
- [x] FastAPI backend (REST endpoints)

### 🔄 Phase 2 — ML & AI Recommendations
- [ ] Delay prediction model (XGBoost)
- [ ] SLA breach prediction (LightGBM)
- [ ] AI recommendation engine (Gemini 2.5 Flash)
- [ ] LLM root cause analysis
- [ ] Executive summary generation
- [ ] React.js frontend

### 🗓 Phase 3 — GenAI & Enterprise
- [ ] Process Copilot (conversational Q&A)
- [ ] RAG knowledge assistant (SOPs · policies · ChromaDB)
- [ ] Real-time monitoring (webhooks · Kafka)
- [ ] Multi-agent process optimizer
- [ ] Digital twin simulation

---

## Future Enhancements

- **Real-time process monitoring** — live KPI alerts when SLA thresholds are crossed
- **Digital twin simulation** — what-if scenario modelling before implementing changes
- **Multi-agent optimization** — autonomous agents that identify and propose process improvements
- **Enterprise connectors** — direct integration with SAP, Salesforce, ServiceNow, Jira
- **Multi-tenant SaaS** — support multiple organisations with isolated data and dashboards

---

## Topics

`process-mining` `business-intelligence` `etl-pipeline` `data-analytics`
`pm4py` `streamlit` `fastapi` `postgresql` `python` `plotly`
`machine-learning` `generative-ai` `llm` `rag` `chromadb`
`bottleneck-detection` `kpi-dashboard` `variant-analysis` `event-log`
`enterprise-software`

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built as a portfolio project demonstrating expertise in Business Analysis, Process Mining, Data Analytics, Machine Learning, GenAI, and Enterprise Software Development.*