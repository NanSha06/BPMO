"""
api/main.py
===========
Business Process Mining & Optimization Platform — Phase 1
Step 6b: FastAPI Application Entry Point

Run
---
    cd C:\\Users\\hp\\OneDrive\\Desktop\\BPMO
    uvicorn api.main:app --reload --port 8000

Interactive docs
----------------
    Swagger UI  →  http://localhost:8000/docs
    ReDoc       →  http://localhost:8000/redoc

All endpoints are prefixed with /api:
    http://localhost:8000/api/health
    http://localhost:8000/api/kpis?source=helpdesk
    http://localhost:8000/api/variants?source=helpdesk&top_n=10
    http://localhost:8000/api/graph?source=helpdesk&min_edge_count=1000
    http://localhost:8000/api/bottlenecks?source=helpdesk
    http://localhost:8000/api/cases?source=helpdesk&page=1
    http://localhost:8000/api/summary?source=helpdesk
"""

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config_loader import config
from api.routes import router

# ── App instance ─────────────────────────────────────────────
app = FastAPI(
    title       = config["api"]["title"],
    version     = config["api"]["version"],
    description = """
## Business Process Mining & Optimization Platform — Phase 1 API

Provides REST access to all process mining analytics:

- **KPIs** — cycle time, SLA breach rate, escalation rate, throughput
- **Process graph** — DFG nodes and edges for Sankey visualisation
- **Variants** — top process paths, ideal vs actual, deviating cases
- **Bottlenecks** — activity wait times, slow transitions, rework loops
- **Cases** — paginated case list with cycle time and metadata
- **ETL** — trigger pipeline runs programmatically

All endpoints accept optional `source`, `priority`, and `category`
query parameters to filter results.
    """,
    docs_url    = config["api"]["docs_url"],
    redoc_url   = config["api"]["redoc_url"],
)

# ── CORS ─────────────────────────────────────────────────────
# Allows the Streamlit dashboard (port 8501) and React frontend
# (port 3000 in Phase 2) to call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins     = config["api"]["cors_origins"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Mount all routes under /api prefix ───────────────────────
app.include_router(router, prefix="/api")


# ── Startup event ────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    print("=" * 55)
    print("  Business Process Mining API — Phase 1")
    print("  Swagger UI : http://localhost:8000/docs")
    print("  ReDoc      : http://localhost:8000/redoc")
    print("  Health     : http://localhost:8000/api/health")
    print("=" * 55)


# ── Root redirect ─────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def root():
    return {
        "message": "Business Process Mining API is running.",
        "docs":    "http://localhost:8000/docs",
        "health":  "http://localhost:8000/api/health",
    }