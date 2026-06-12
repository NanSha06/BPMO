"""
analytics/cache_manager.py
==========================
PostgreSQL-backed cache for pre-computed dashboard results.

Stores results as JSONB in the dashboard_cache table.
Every expensive computation (KPIs, variants, graph, bottlenecks)
checks this cache first before running the full query.

Rules
-----
- get_cached() returns None if key not found — callers must handle this
- set_cached() upserts — safe to call multiple times with same key
- Cache key is a deterministic hash of (prefix, source, priority, category)
- No TTL on the DB side — cache is invalidated only by running warmup.py again
  or by calling invalidate_cache()
- All data serialised as JSON with default=str to handle datetime/Decimal types
"""

import json
import hashlib
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config_loader import get_database_url


def _get_engine():
    return create_engine(get_database_url(), pool_pre_ping=True)


def _make_key(prefix: str, source, priority, category) -> str:
    """
    Build a deterministic cache key from the four filter dimensions.
    None values are normalised to the string "all" before hashing
    so None and "all" map to the same key.
    """
    s = str(source   or "all").lower().strip()
    p = str(priority or "all").lower().strip()
    c = str(category or "all").lower().strip()
    raw = f"{prefix}:{s}:{p}:{c}"
    short_hash = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"{prefix}:{s}:{p}:{c}:{short_hash}"


def ensure_cache_table():
    """
    Create the dashboard_cache table if it does not already exist.
    Safe to call multiple times — uses IF NOT EXISTS.
    Called automatically by get_cached and set_cached.
    """
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dashboard_cache (
                cache_key   VARCHAR(300) PRIMARY KEY,
                data        JSONB        NOT NULL,
                computed_at TIMESTAMPTZ  DEFAULT NOW()
            );
        """))


def get_cached(
    prefix:   str,
    source:   str = None,
    priority: str = None,
    category: str = None,
):
    """
    Retrieve a cached result from PostgreSQL.

    Returns the deserialised Python object if found, or None if not found.
    The caller is responsible for computing the value when None is returned.

    Parameters
    ----------
    prefix   : identifier for the type of result e.g. "kpis", "variants",
               "graph", "bottlenecks"
    source   : dataset filter e.g. "helpdesk"
    priority : priority filter e.g. "High" — pass None for all priorities
    category : category filter e.g. "Software" — pass None for all categories

    Example
    -------
        result = get_cached("kpis", source="helpdesk", priority="High")
        if result is None:
            result = KPIEngine().compute(source="helpdesk", priority="High")
            set_cached("kpis", result, source="helpdesk", priority="High")
    """
    ensure_cache_table()
    key    = _make_key(prefix, source, priority, category)
    engine = _get_engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT data FROM dashboard_cache WHERE cache_key = :k"),
                {"k": key}
            ).fetchone()
        return json.loads(row[0]) if row else None
    except Exception:
        # If cache read fails for any reason, return None so
        # the caller falls back to computing the result normally
        return None


def set_cached(
    prefix:   str,
    data,
    source:   str = None,
    priority: str = None,
    category: str = None,
):
    """
    Store a computed result in the PostgreSQL cache.

    Upserts — if the key already exists the value is overwritten.
    Serialises using default=str so datetime and Decimal values
    do not raise TypeError.

    Parameters
    ----------
    prefix   : same identifier used in get_cached
    data     : any JSON-serialisable Python object (dict, list)
    source   : dataset filter
    priority : priority filter
    category : category filter
    """
    ensure_cache_table()
    key    = _make_key(prefix, source, priority, category)
    engine = _get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO dashboard_cache (cache_key, data, computed_at)
                VALUES (:k, CAST(:d AS jsonb), :t)
                ON CONFLICT (cache_key) DO UPDATE
                    SET data        = EXCLUDED.data,
                        computed_at = EXCLUDED.computed_at
            """), {
                "k": key,
                "d": json.dumps(data, default=str),
                "t": datetime.now(timezone.utc),
            })
    except Exception as e:
        # If cache write fails, log and continue — the app still works
        # without the cache, just slower
        print(f"[CACHE] WARNING: could not write cache key '{key}': {e}")


def invalidate_cache(prefix: str = None):
    """
    Delete cached entries from dashboard_cache.

    If prefix is given, only entries for that prefix are deleted.
    If prefix is None, ALL cached entries are deleted.

    Call this after re-running ETL to force fresh computation.

    Example
    -------
        invalidate_cache()           # clear everything
        invalidate_cache("kpis")     # clear only KPI cache
    """
    ensure_cache_table()
    engine = _get_engine()
    with engine.begin() as conn:
        if prefix:
            conn.execute(
                text("DELETE FROM dashboard_cache WHERE cache_key LIKE :p"),
                {"p": f"{prefix}:%"}
            )
            print(f"[CACHE] Invalidated all '{prefix}' cache entries.")
        else:
            conn.execute(text("DELETE FROM dashboard_cache"))
            print("[CACHE] All cache entries invalidated.")


def list_cache_keys():
    """
    Return all cache keys and their computed_at timestamps.
    Useful for debugging — call from a Python shell.

    Example
    -------
        from analytics.cache_manager import list_cache_keys
        for row in list_cache_keys():
            print(row)
    """
    ensure_cache_table()
    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT cache_key, computed_at FROM dashboard_cache ORDER BY computed_at DESC")
        ).fetchall()
    return [{"key": r[0], "computed_at": str(r[1])} for r in rows]
