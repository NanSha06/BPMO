"""
api/routes.py
=============
Business Process Mining & Optimization Platform — Phase 1
Step 6a: All REST API route handlers

Endpoints
---------
GET  /api/health                  → service health check
GET  /api/kpis                    → headline KPIs
GET  /api/bottlenecks             → bottleneck analysis
GET  /api/variants                → top process variants
GET  /api/graph                   → DFG edges for process flow chart
GET  /api/cases                   → paginated case list
GET  /api/summary                 → combined single-call summary
POST /api/etl/run                 → trigger ETL pipeline
"""

import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.kpis          import KPIEngine
from analytics.bottlenecks   import BottleneckEngine
from process_mining.discovery import ProcessDiscovery
from process_mining.variants  import VariantAnalyser

router = APIRouter()

# ── Lazy-loaded singletons (created once per worker) ─────────
_kpi_engine        = None
_bottleneck_engine = None
_discovery         = None
_variant_analyser  = None


def get_kpi_engine():
    global _kpi_engine
    if _kpi_engine is None:
        _kpi_engine = KPIEngine()
    return _kpi_engine


def get_bottleneck_engine():
    global _bottleneck_engine
    if _bottleneck_engine is None:
        _bottleneck_engine = BottleneckEngine()
    return _bottleneck_engine


def get_discovery():
    global _discovery
    if _discovery is None:
        _discovery = ProcessDiscovery()
    return _discovery


def get_variant_analyser():
    global _variant_analyser
    if _variant_analyser is None:
        _variant_analyser = VariantAnalyser()
    return _variant_analyser


# ─────────────────────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────────────────────

@router.get("/health", tags=["System"])
def health_check():
    """
    Returns service status and version.
    Use this to confirm the API is running before calling other endpoints.
    """
    return {
        "status":  "ok",
        "service": "Business Process Mining API",
        "version": "1.0.0",
        "phase":   1,
    }


# ─────────────────────────────────────────────────────────────
# KPIs
# ─────────────────────────────────────────────────────────────

@router.get("/kpis", tags=["Analytics"])
def get_kpis(
    source:   Optional[str] = Query(None, description="Dataset name e.g. helpdesk"),
    priority: Optional[str] = Query(None, description="Critical · High · Medium · Low"),
    category: Optional[str] = Query(None, description="Software · Hardware · Network · HR"),
):
    """
    Compute and return all headline KPIs.

    Optional query parameters filter the underlying event log before
    computing. Omit all parameters to get KPIs across the full dataset.

    Example:
        GET /api/kpis?source=helpdesk&priority=Critical
    """
    try:
        result = get_kpi_engine().compute(
            source=source, priority=priority, category=category
        )
        return {"status": "ok", "filters": {"source": source,
                "priority": priority, "category": category},
                "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# BOTTLENECKS
# ─────────────────────────────────────────────────────────────

@router.get("/bottlenecks", tags=["Analytics"])
def get_bottlenecks(
    source:   Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """
    Return full bottleneck analysis including activity wait times,
    slowest transitions, rework loops, and priority comparison.

    Example:
        GET /api/bottlenecks?source=helpdesk
    """
    try:
        result = get_bottleneck_engine().analyse(
            source=source, priority=priority, category=category
        )
        return {"status": "ok", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bottlenecks/activity-wait-times", tags=["Analytics"])
def get_activity_wait_times(
    source:   Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """
    Return only the activity wait time ranking — lighter call
    than the full bottleneck analysis.
    """
    try:
        result = get_bottleneck_engine().activity_wait_times(
            source=source, priority=priority, category=category
        )
        return {"status": "ok", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# VARIANTS
# ─────────────────────────────────────────────────────────────

@router.get("/variants", tags=["Process Mining"])
def get_variants(
    source:   Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    top_n:    int            = Query(10, ge=1, le=50,
                               description="Number of top variants to return"),
):
    """
    Return top N process variants with frequency, cycle time,
    and happy path flag.

    Example:
        GET /api/variants?source=helpdesk&top_n=10
    """
    try:
        result = get_variant_analyser().get_top_variants(
            source=source, priority=priority,
            category=category, top_n=top_n
        )
        return {"status": "ok", "count": len(result), "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/variants/ideal-vs-actual", tags=["Process Mining"])
def get_ideal_vs_actual(
    source:   Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """
    Compare the ideal (happy path) variant against all deviating cases.

    Returns ideal path definition, case counts, deviation rate,
    and the top 5 deviation patterns.
    """
    try:
        result = get_variant_analyser().ideal_vs_actual(
            source=source, priority=priority, category=category
        )
        return {"status": "ok", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/variants/deviating-cases", tags=["Process Mining"])
def get_deviating_cases(
    source:   Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    top_n:    int            = Query(50, ge=1, le=200),
):
    """
    Return cases that deviated from the ideal path,
    sorted by cycle time descending (worst cases first).
    """
    try:
        result = get_variant_analyser().get_deviating_cases(
            source=source, priority=priority,
            category=category, top_n=top_n
        )
        return {"status": "ok", "count": len(result), "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# PROCESS GRAPH
# ─────────────────────────────────────────────────────────────

@router.get("/graph", tags=["Process Mining"])
def get_process_graph(
    source:         Optional[str] = Query(None),
    priority:       Optional[str] = Query(None),
    category:       Optional[str] = Query(None),
    min_edge_count: int            = Query(500, ge=1,
                    description="Hide edges with fewer occurrences"),
):
    """
    Return the Directly-Follows Graph (DFG) as nodes and edges.
    Used to render the process flow Sankey diagram on the dashboard.

    Example:
        GET /api/graph?source=helpdesk&min_edge_count=1000
    """
    try:
        result = get_discovery().get_dfg_for_display(
            source=source, priority=priority,
            category=category, min_edge_count=min_edge_count
        )
        return {"status": "ok", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# CASES
# ─────────────────────────────────────────────────────────────

@router.get("/cases", tags=["Data"])
def get_cases(
    source:   Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    page:     int            = Query(1,   ge=1),
    page_size:int            = Query(100, ge=1, le=1000),
):
    """
    Return a paginated list of cases from the cases table.

    Example:
        GET /api/cases?source=helpdesk&priority=Critical&page=1&page_size=50
    """
    try:
        import os
        from sqlalchemy import create_engine, text
        import pandas as pd
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from config_loader import get_database_url

        engine = create_engine(get_database_url(), pool_pre_ping=True)

        conditions, params = [], {}
        if source:
            conditions.append("source = :source")
            params["source"] = source
        if priority and priority.lower() != "all":
            conditions.append("priority = :priority")
            params["priority"] = priority
        if category and category.lower() != "all":
            conditions.append("category = :category")
            params["category"] = category

        where  = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size
        params.update({"limit": page_size, "offset": offset})

        count_q = f"SELECT COUNT(*) FROM cases {where}"
        data_q  = f"""
            SELECT case_id, source, category, priority, escalated,
                   start_time, end_time, cycle_time_mins,
                   event_count, resolution_time_hrs
            FROM cases {where}
            ORDER BY cycle_time_mins DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """

        with engine.connect() as conn:
            total = conn.execute(text(count_q), params).scalar()
            df    = pd.read_sql(text(data_q), conn, params=params)

        return {
            "status":    "ok",
            "page":      page,
            "page_size": page_size,
            "total":     total,
            "pages":     -(-total // page_size),  # ceiling division
            "data":      df.to_dict(orient="records"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# SUMMARY — single call for dashboard initial load
# ─────────────────────────────────────────────────────────────

@router.get("/summary", tags=["Analytics"])
def get_summary(
    source:   Optional[str] = Query("helpdesk"),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """
    Combined endpoint that returns KPIs + top variants + bottlenecks
    in a single API call. Use this for dashboard initial load to
    avoid 3 separate round trips.

    Example:
        GET /api/summary?source=helpdesk
    """
    try:
        kpis        = get_kpi_engine().compute(source, priority, category)
        variants    = get_variant_analyser().get_top_variants(
                          source, priority, category, top_n=5)
        bottlenecks = get_bottleneck_engine().activity_wait_times(
                          source, priority, category)

        return {
            "status": "ok",
            "data": {
                "kpis":        kpis,
                "top_variants": variants,
                "bottlenecks": bottlenecks[:5],
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# ETL TRIGGER
# ─────────────────────────────────────────────────────────────

class ETLRequest(BaseModel):
    filepath:    str
    source_name: str


@router.post("/etl/run", tags=["ETL"])
def trigger_etl(body: ETLRequest):
    """
    Trigger an ETL pipeline run programmatically.

    Body:
        filepath    — path to the raw CSV or XES file
        source_name — label to tag the rows with in the database

    Example:
        POST /api/etl/run
        {"filepath": "data/raw/helpdesk_tickets.csv",
         "source_name": "helpdesk"}
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from etl.pipeline import ETLPipeline
        result = ETLPipeline().run(
            filepath=body.filepath,
            source_name=body.source_name
        )
        return {"status": "ok", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))