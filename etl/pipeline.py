"""
etl.py
======
Business Process Mining & Optimization Platform — Phase 1
ETL pipeline: helpdesk_tickets.csv → PostgreSQL event_log table

What this file does
-------------------
1. EXTRACT   — reads helpdesk_tickets.csv into a raw DataFrame
2. VALIDATE  — checks columns, nulls, row count, date parseability
3. TRANSFORM — converts one-row-per-ticket into one-row-per-event
               (the format PM4Py requires) using vectorised Pandas ops
4. LOAD      — writes three tables to PostgreSQL:
                 • event_log   — every event row (main table)
                 • cases       — one summary row per ticket
                 • etl_runs    — audit trail of every pipeline run

Usage
-----
  1. Make sure .env is in the project root with your DB credentials
  2. Make sure PostgreSQL is running and the database exists
  3. Run from project root:  python -m etl.pipeline

Requirements
------------
  pip install pandas sqlalchemy psycopg2-binary python-dotenv pyyaml
"""

import os
import sys
import time
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from pathlib import Path

# Load .env from project root (two levels up from etl/pipeline.py)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ============================================================
# CONFIG — all values loaded from .env (no secrets here)
# ============================================================
DB_USER     = os.getenv("DB_USER",     "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_PORT     = os.getenv("DB_PORT",     "5432")
DB_NAME     = os.getenv("DB_NAME",     "process_mining_db")

CSV_FILE    = os.getenv("CSV_FILE",    "data/raw/helpdesk_tickets.csv")
SOURCE_NAME = os.getenv("SOURCE_NAME", "helpdesk")
CHUNK_SIZE  = int(os.getenv("CHUNK_SIZE", "50000"))
# ============================================================


# ────────────────────────────────────────────────────────────
# DATABASE SETUP
# ────────────────────────────────────────────────────────────

def get_engine():
    """Create and return a SQLAlchemy engine using credentials from .env."""
    url = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(url, pool_pre_ping=True)


def create_tables(engine):
    """
    Create the three required tables if they do not already exist.
    Running this multiple times is safe — IF NOT EXISTS guards it.
    """
    ddl = """
    -- Stores every cleaned event row from every dataset
    CREATE TABLE IF NOT EXISTS event_log (
        id                  SERIAL PRIMARY KEY,
        case_id             VARCHAR(100)  NOT NULL,
        activity            VARCHAR(100)  NOT NULL,
        timestamp           TIMESTAMPTZ   NOT NULL,
        resource            VARCHAR(200),
        category            VARCHAR(100),
        subcategory         VARCHAR(200),
        priority            VARCHAR(50),
        current_status      VARCHAR(100),
        escalated           BOOLEAN,
        resolution_time_hrs FLOAT,
        wait_time_mins      FLOAT,
        cycle_time_mins     FLOAT,
        source              VARCHAR(100),
        loaded_at           TIMESTAMPTZ DEFAULT NOW()
    );

    -- Stores one summary row per ticket / process case
    CREATE TABLE IF NOT EXISTS cases (
        case_id             VARCHAR(100) PRIMARY KEY,
        source              VARCHAR(100),
        category            VARCHAR(100),
        priority            VARCHAR(50),
        escalated           BOOLEAN,
        start_time          TIMESTAMPTZ,
        end_time            TIMESTAMPTZ,
        cycle_time_mins     FLOAT,
        event_count         INTEGER,
        resolution_time_hrs FLOAT
    );

    -- Stores one row per ETL run as an audit trail
    CREATE TABLE IF NOT EXISTS etl_runs (
        id          SERIAL PRIMARY KEY,
        source      VARCHAR(100),
        file_path   VARCHAR(500),
        raw_rows    INTEGER,
        event_rows  INTEGER,
        case_count  INTEGER,
        status      VARCHAR(50),
        error_msg   TEXT,
        duration_s  FLOAT,
        run_at      TIMESTAMPTZ DEFAULT NOW()
    );

    -- Indexes for fast downstream queries
    CREATE INDEX IF NOT EXISTS idx_el_case_id   ON event_log(case_id);
    CREATE INDEX IF NOT EXISTS idx_el_activity  ON event_log(activity);
    CREATE INDEX IF NOT EXISTS idx_el_timestamp ON event_log(timestamp);
    CREATE INDEX IF NOT EXISTS idx_el_source    ON event_log(source);
    CREATE INDEX IF NOT EXISTS idx_el_priority  ON event_log(priority);
    CREATE INDEX IF NOT EXISTS idx_el_category  ON event_log(category);
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))
    print("[DB]  Tables and indexes created (or already exist).")


# ────────────────────────────────────────────────────────────
# STEP 1 — EXTRACT
# ────────────────────────────────────────────────────────────

def extract(filepath: str) -> pd.DataFrame:
    """
    Read the raw CSV file and return a DataFrame with original columns.
    Does not modify any values.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(
            f"File not found: {filepath}\n"
            f"Place helpdesk_tickets.csv in the same folder as etl.py "
            f"or update CSV_FILE with the full path."
        )

    print(f"[EXTRACT]  Reading {filepath} ...")
    df = pd.read_csv(filepath, dtype={
        "Ticket_ID":           str,     # keep as string — used as case_id
        "Category":            str,
        "Subcategory":         str,
        "Priority":            str,
        "Status":              str,
        "Assigned_Team":       str,
        "Description":         str,
        "Escalated":           bool,
        "Resolution_Time_Hrs": float,
    })
    print(f"[EXTRACT]  {len(df):,} raw rows read.")
    return df


# ────────────────────────────────────────────────────────────
# STEP 2 — VALIDATE
# ────────────────────────────────────────────────────────────

REQUIRED_COLUMNS = [
    "Ticket_ID", "Date_Created", "Category", "Subcategory",
    "Priority", "Status", "Assigned_Team",
    "Resolution_Time_Hrs", "Escalated"
]


def validate(df: pd.DataFrame) -> None:
    """
    Check the raw DataFrame for structural correctness.
    Raises ValueError on hard failures.
    Prints warnings for soft issues that the transform step handles.
    """
    print("[VALIDATE] Checking data quality ...")
    errors   = []
    warnings = []

    # 1. Required columns must all be present
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        errors.append(f"Missing required columns: {missing}")

    # 2. Minimum row count
    if len(df) < 10:
        errors.append(f"Only {len(df)} rows found. Minimum is 10.")

    # 3. Ticket_ID must have no nulls
    if "Ticket_ID" in df.columns and df["Ticket_ID"].isnull().any():
        errors.append("Ticket_ID column contains null values.")

    # 4. Date_Created must be parseable (check on a sample of 1000)
    if "Date_Created" in df.columns:
        sample_dates = pd.to_datetime(
            df["Date_Created"].head(1000), dayfirst=True, errors="coerce"
        )
        unparseable = sample_dates.isnull().sum()
        if unparseable > 50:
            errors.append(
                f"Date_Created: {unparseable}/1000 sampled values could not "
                f"be parsed as dates. Check the date format."
            )

    # 5. Date_Resolved nulls are expected (open tickets) — warn not error
    if "Date_Resolved" in df.columns:
        null_resolved = df["Date_Resolved"].isnull().sum()
        if null_resolved > 0:
            pct = null_resolved / len(df) * 100
            warnings.append(
                f"Date_Resolved has {null_resolved:,} nulls ({pct:.1f}%). "
                f"These are open/in-progress tickets. They will get a "
                f"'status: <current_status>' event instead of 'ticket resolved'."
            )

    for w in warnings:
        print(f"[VALIDATE] WARNING: {w}")

    if errors:
        raise ValueError(
            "[VALIDATE] FAILED:\n" + "\n".join(f"  • {e}" for e in errors)
        )

    print(f"[VALIDATE] Passed. {len(df):,} rows, {len(df.columns)} columns.")


# ────────────────────────────────────────────────────────────
# STEP 3 — TRANSFORM
# ────────────────────────────────────────────────────────────

def transform(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert a ticket-format DataFrame (one row per ticket) into an
    event log DataFrame (one row per event) that PM4Py can consume.

    The helpdesk dataset has ONE row per ticket. Process mining needs
    ONE row per event. A single ticket becomes 2–3 events:

        Event 1 (always):     'ticket opened'    @ Date_Created
        Event 2 (if escalated): 'ticket escalated' @ Date_Created + 1 hour
        Event 3a (if resolved): 'ticket resolved'  @ Date_Resolved
        Event 3b (if open):     'status: <status>' @ Date_Created + 2 hours

    Uses vectorised Pandas operations (no row-by-row loops) for
    performance on the full 1M-row dataset.

    Computed features added
    -----------------------
    wait_time_mins  — minutes since the previous event in the same case
    cycle_time_mins — total minutes from ticket open to last event
    """
    print("[TRANSFORM] Parsing dates ...")
    df = df.copy()
    df["Date_Created"]  = pd.to_datetime(df["Date_Created"],  dayfirst=True, errors="coerce")
    df["Date_Resolved"] = pd.to_datetime(df["Date_Resolved"], dayfirst=True, errors="coerce")

    # Drop rows where Date_Created could not be parsed — cannot place on timeline
    bad_dates = df["Date_Created"].isnull().sum()
    if bad_dates > 0:
        print(f"[TRANSFORM] WARNING: Dropping {bad_dates} rows with unparseable Date_Created.")
        df = df.dropna(subset=["Date_Created"])

    # Normalise string columns
    df["Status"]       = df["Status"].str.strip()
    df["Priority"]     = df["Priority"].str.strip()
    df["Category"]     = df["Category"].str.strip()
    df["Subcategory"]  = df["Subcategory"].str.strip()
    df["Assigned_Team"]= df["Assigned_Team"].str.strip()

    print("[TRANSFORM] Exploding tickets into events (vectorised) ...")

    # ── Shared column set and rename map ─────────────────────
    # ALL original column names must be renamed to lowercase
    # standard names BEFORE concat. Missing any one column in any
    # single event DataFrame was the cause of the KeyError.
    meta_cols = [
        "Ticket_ID", "Assigned_Team", "Category", "Subcategory",
        "Priority", "Status", "Escalated", "Resolution_Time_Hrs"
    ]

    RENAME = {
        "Ticket_ID":           "case_id",
        "Assigned_Team":       "resource",
        "Category":            "category",
        "Subcategory":         "subcategory",
        "Priority":            "priority",
        "Status":              "current_status",
        "Escalated":           "escalated",
        "Resolution_Time_Hrs": "resolution_time_hrs",
    }

    # ── Event 1: ticket opened (every ticket) ───────────────
    e_opened = df[meta_cols + ["Date_Created"]].copy()
    e_opened = e_opened.rename(columns={**RENAME, "Date_Created": "timestamp"})
    e_opened["activity"] = "ticket opened"

    # ── Event 2: ticket escalated (only escalated tickets) ──
    esc_mask = df["Escalated"] == True
    esc_df   = df[esc_mask][meta_cols + ["Date_Created"]].copy()
    e_escalated = esc_df.rename(columns=RENAME)
    # Place escalation 1 hour after ticket was opened
    e_escalated["timestamp"] = esc_df["Date_Created"].values + pd.Timedelta(hours=1)
    e_escalated["activity"]  = "ticket escalated"

    # ── Event 3a: ticket resolved (tickets with a resolution date) ──
    resolved_mask = df["Date_Resolved"].notna()
    resolved_df   = df[resolved_mask][meta_cols + ["Date_Resolved"]].copy()
    e_resolved = resolved_df.rename(columns={**RENAME, "Date_Resolved": "timestamp"})
    e_resolved["activity"] = "ticket resolved"

    # ── Event 3b: status snapshot (open/pending/on hold tickets) ──
    open_df = df[~resolved_mask][meta_cols + ["Date_Created"]].copy()
    e_open  = open_df.rename(columns=RENAME)
    # Place status snapshot 2 hours after ticket was opened
    e_open["timestamp"] = open_df["Date_Created"].values + pd.Timedelta(hours=2)
    e_open["activity"]  = "status: " + e_open["current_status"].str.lower()

    # ── Combine all event types ──────────────────────────────
    event_log = pd.concat(
        [e_opened, e_escalated, e_resolved, e_open],
        ignore_index=True
    )

    # ── Sort by case then time — required for feature engineering ──
    event_log = event_log.sort_values(
        ["case_id", "timestamp"]
    ).reset_index(drop=True)

    # ── Feature: wait_time_mins ──────────────────────────────
    # Time gap from the previous event in the same case.
    # The first event of every case will have NaN — this is correct.
    event_log["prev_timestamp"] = event_log.groupby("case_id")["timestamp"].shift(1)
    event_log["wait_time_mins"] = (
        (event_log["timestamp"] - event_log["prev_timestamp"])
        .dt.total_seconds() / 60
    ).round(2)
    event_log = event_log.drop(columns=["prev_timestamp"])

    # ── Feature: cycle_time_mins ─────────────────────────────
    # Total duration from first event to last event for each case.
    bounds = event_log.groupby("case_id")["timestamp"].agg(
        case_start="min",
        case_end="max"
    )
    bounds["cycle_time_mins"] = (
        (bounds["case_end"] - bounds["case_start"])
        .dt.total_seconds() / 60
    ).round(2)
    event_log = event_log.merge(
        bounds[["cycle_time_mins"]], on="case_id", how="left"
    )

    # ── Final column order ───────────────────────────────────
    event_log = event_log[[
        "case_id", "activity", "timestamp", "resource",
        "category", "subcategory", "priority",
        "current_status", "escalated", "resolution_time_hrs",
        "wait_time_mins", "cycle_time_mins"
    ]]

    print(f"[TRANSFORM] Done.")
    print(f"[TRANSFORM]   Input tickets  : {len(df):>10,}")
    print(f"[TRANSFORM]   Output events  : {len(event_log):>10,}")
    print(f"[TRANSFORM]   Unique cases   : {event_log['case_id'].nunique():>10,}")
    print(f"[TRANSFORM]   Activity types : {sorted(event_log['activity'].unique())}")
    return event_log


# ────────────────────────────────────────────────────────────
# STEP 4 — LOAD
# ────────────────────────────────────────────────────────────

def _build_cases_df(event_log: pd.DataFrame, source: str) -> pd.DataFrame:
    """
    Derive one summary row per case from the event log.
    Used to populate the cases table.
    """
    agg = event_log.groupby("case_id").agg(
        start_time          = ("timestamp",           "min"),
        end_time            = ("timestamp",           "max"),
        cycle_time_mins     = ("cycle_time_mins",     "first"),
        event_count         = ("activity",            "count"),
        category            = ("category",            "first"),
        priority            = ("priority",            "first"),
        escalated           = ("escalated",           "first"),
        resolution_time_hrs = ("resolution_time_hrs", "first"),
    ).reset_index()
    agg["source"] = source
    return agg


def load(event_log: pd.DataFrame, engine, source: str) -> dict:
    """
    Write event_log and cases tables to PostgreSQL in chunks.
    Uses IF NOT EXISTS / ON CONFLICT so re-running is safe.
    """
    event_log = event_log.copy()
    event_log["source"]    = source
    event_log["loaded_at"] = datetime.now(timezone.utc)

    total_rows  = len(event_log)
    case_count  = event_log["case_id"].nunique()
    chunks      = range(0, total_rows, CHUNK_SIZE)
    total_chunks= len(list(chunks))

    print(f"[LOAD]  Writing {total_rows:,} events in "
          f"{total_chunks} chunks of {CHUNK_SIZE:,} ...")

    for i, start in enumerate(range(0, total_rows, CHUNK_SIZE), 1):
        chunk = event_log.iloc[start : start + CHUNK_SIZE]
        chunk.to_sql(
            "event_log", engine,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=1000
        )
        pct = i / total_chunks * 100
        print(f"[LOAD]    Chunk {i}/{total_chunks} written ({pct:.0f}%)", end="\r")

    print()  # newline after progress

    # ── Cases table: bulk load via staging table ─────────────
    # Writing 1M rows one-by-one in a Python loop takes 30-60 min.
    # Instead: bulk-write to a staging table (seconds), then run a
    # single SQL INSERT ... ON CONFLICT into cases (seconds).
    print(f"[LOAD]  Writing {case_count:,} rows to cases table (bulk) ...")
    cases_df = _build_cases_df(event_log, source)

    # Step 1: dump all rows into a temporary staging table in one shot
    cases_df.to_sql(
        "cases_staging", engine,
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=5000
    )
    print(f"[LOAD]    Staging table written. Running bulk upsert ...")

    # Step 2: single SQL statement upserts all rows from staging → cases
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO cases
                (case_id, source, category, priority, escalated,
                 start_time, end_time, cycle_time_mins,
                 event_count, resolution_time_hrs)
            SELECT
                case_id, source, category, priority, escalated,
                start_time, end_time, cycle_time_mins,
                event_count, resolution_time_hrs
            FROM cases_staging
            ON CONFLICT (case_id) DO UPDATE SET
                end_time            = EXCLUDED.end_time,
                cycle_time_mins     = EXCLUDED.cycle_time_mins,
                event_count         = EXCLUDED.event_count;
        """))
        # Step 3: drop staging table
        conn.execute(text("DROP TABLE IF EXISTS cases_staging;"))

    print(f"[LOAD]  Done.")
    return {"event_rows": total_rows, "case_count": case_count}


def log_etl_run(engine, source, filepath, raw_rows,
                event_rows, case_count, status, error_msg, duration_s):
    """Write one audit row to etl_runs table."""
    pd.DataFrame([{
        "source":     source,
        "file_path":  filepath,
        "raw_rows":   raw_rows,
        "event_rows": event_rows,
        "case_count": case_count,
        "status":     status,
        "error_msg":  error_msg,
        "duration_s": round(duration_s, 2),
        "run_at":     datetime.now(timezone.utc),
    }]).to_sql("etl_runs", engine, if_exists="append", index=False)


# ────────────────────────────────────────────────────────────
# PIPELINE ORCHESTRATOR
# ────────────────────────────────────────────────────────────

def run():
    """
    Orchestrate the full ETL pipeline:
    Extract → Validate → Transform → Load
    """
    print("=" * 60)
    print("  Process Mining ETL Pipeline — Phase 1")
    print("  Source :", CSV_FILE)
    print("  Target :", f"{DB_HOST}/{DB_NAME} → event_log")
    print("=" * 60)

    start_time = time.time()
    engine     = get_engine()

    # Verify database connection before doing any work
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[DB]  Connection OK.")
    except Exception as e:
        print(f"\n[ERROR] Cannot connect to PostgreSQL.\n"
              f"  Check DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME\n"
              f"  in your .env file at the project root\n"
              f"  Original error: {e}")
        sys.exit(1)

    create_tables(engine)

    raw_rows   = 0
    event_rows = 0
    case_count = 0

    try:
        # Extract
        raw_df   = extract(CSV_FILE)
        raw_rows = len(raw_df)

        # Validate
        validate(raw_df)

        # Transform
        event_log  = transform(raw_df)
        event_rows = len(event_log)
        case_count = event_log["case_id"].nunique()

        # Load
        load(event_log, engine, SOURCE_NAME)

        duration = time.time() - start_time
        log_etl_run(engine, SOURCE_NAME, CSV_FILE,
                    raw_rows, event_rows, case_count,
                    "success", None, duration)

        print()
        print("=" * 60)
        print("  ETL COMPLETE")
        print(f"  Raw tickets ingested : {raw_rows:>10,}")
        print(f"  Event rows loaded    : {event_rows:>10,}")
        print(f"  Unique cases         : {case_count:>10,}")
        print(f"  Duration             : {duration:>9.1f}s")
        print("=" * 60)
        print()
        print("Verify in PostgreSQL:")
        print("  SELECT source, COUNT(*), COUNT(DISTINCT case_id)")
        print("  FROM event_log GROUP BY source;")
        print()

    except Exception as e:
        duration = time.time() - start_time
        log_etl_run(engine, SOURCE_NAME, CSV_FILE,
                    raw_rows, event_rows, case_count,
                    "failed", str(e), duration)
        print(f"\n[ERROR] Pipeline failed: {e}")
        raise


# ────────────────────────────────────────────────────────────
# ENTRY POINT
# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run()