"""
analytics/kpis.py
=================
Business Process Mining & Optimization Platform — Phase 1
Step 3a: KPI Computation Engine

What this file does
-------------------
Queries the event_log and cases tables from PostgreSQL and computes
all headline KPIs that appear on the dashboard:

    • Total cases and events
    • Average / median / P90 cycle time
    • SLA breach rate          (cases exceeding threshold in config.yaml)
    • Escalation rate          (cases with escalated = True)
    • Resolution rate          (cases that reached 'ticket resolved')
    • Throughput               (cases closed per day)
    • Volume by priority       (Low / Medium / High / Critical)
    • Volume by category       (Software / Hardware / Network etc.)
    • Daily trend              (events per day over time)

All methods accept optional filters (source, priority, category)
so the dashboard can recompute KPIs when the user changes filters.

Usage
-----
    from analytics.kpis import KPIEngine

    kpis = KPIEngine()

    # Full dataset
    result = kpis.compute()

    # Filtered
    result = kpis.compute(source="helpdesk", priority="High")

    # Access individual KPIs
    result["avg_cycle_hrs"]
    result["sla_breach_rate"]
    result["escalation_rate"]
    result["bottlenecks"]       # list of dicts
    result["priority_volume"]   # dict
    result["daily_trend"]       # list of {date, count}
"""

import sys
import pandas as pd
from pathlib import Path
from sqlalchemy import create_engine, text

# ── Config ───────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config_loader import get_database_url, config

SLA_THRESHOLD_HRS   = config["kpis"]["sla_threshold_hrs"]
PERCENTILES         = config["kpis"]["cycle_time_percentiles"]
BOTTLENECK_MINS     = config["kpis"]["bottleneck_threshold_mins"]


def _get_engine():
    return create_engine(get_database_url(), pool_pre_ping=True)


class KPIEngine:
    """
    Computes all platform KPIs from PostgreSQL event_log and cases tables.
    Returns plain dicts and lists — ready for Streamlit and FastAPI.
    """

    def __init__(self):
        self.engine = _get_engine()

    # ──────────────────────────────────────────────────────────
    # PUBLIC: main entry point
    # ──────────────────────────────────────────────────────────

    def compute(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
    ) -> dict:
        """
        Compute all KPIs and return as a single dict.

        Parameters
        ----------
        source   : filter by dataset name e.g. "helpdesk"
        priority : filter by ticket priority e.g. "High"
        category : filter by ticket category e.g. "Software"

        Returns
        -------
        dict containing all KPI values — see module docstring for keys
        """
        print("[KPI] Computing KPIs ...")

        event_df = self._load_events(source, priority, category)
        case_df  = self._load_cases(source, priority, category)

        if event_df.empty or case_df.empty:
            print("[KPI] WARNING: No data found for given filters.")
            return self._empty_result()

        result = {
            **self._volume_kpis(event_df, case_df),
            **self._cycle_time_kpis(case_df),
            **self._sla_kpis(case_df),
            **self._resolution_kpis(event_df, case_df),
            "bottlenecks":      self._bottleneck_kpis(event_df),
            "priority_volume":  self._volume_by_col(case_df, "priority"),
            "category_volume":  self._volume_by_col(case_df, "category"),
            "daily_trend":      self._daily_trend(event_df),
            "hourly_heatmap":   self._hourly_heatmap(event_df),
        }

        print(f"[KPI] Done. "
              f"{result['total_cases']:,} cases | "
              f"avg cycle {result['avg_cycle_hrs']:.1f}h | "
              f"SLA breach {result['sla_breach_rate']}%")
        return result

    # ──────────────────────────────────────────────────────────
    # PRIVATE: data loaders
    # ──────────────────────────────────────────────────────────

    def _build_filter(self, source, priority, category):
        """Build WHERE clause and params dict for optional filters."""
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
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return where, params

    def _load_events(self, source, priority, category) -> pd.DataFrame:
        where, params = self._build_filter(source, priority, category)
        query = f"""
            SELECT case_id, activity, timestamp,
                   priority, category, escalated,
                   wait_time_mins, cycle_time_mins
            FROM   event_log
            {where}
            ORDER BY case_id, timestamp
        """
        with self.engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    def _load_cases(self, source, priority, category) -> pd.DataFrame:
        where, params = self._build_filter(source, priority, category)
        query = f"""
            SELECT case_id, source, category, priority,
                   escalated, start_time, end_time,
                   cycle_time_mins, event_count, resolution_time_hrs
            FROM   cases
            {where}
        """
        with self.engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)
        df["start_time"] = pd.to_datetime(df["start_time"], utc=True)
        df["end_time"]   = pd.to_datetime(df["end_time"],   utc=True)
        return df

    # ──────────────────────────────────────────────────────────
    # PRIVATE: KPI calculators
    # ──────────────────────────────────────────────────────────

    def _volume_kpis(self, event_df, case_df) -> dict:
        """Total counts."""
        return {
            "total_cases":       int(case_df["case_id"].nunique()),
            "total_events":      int(len(event_df)),
            "avg_events_per_case": round(
                len(event_df) / case_df["case_id"].nunique(), 2
            ),
        }

    def _cycle_time_kpis(self, case_df) -> dict:
        """
        Cycle time = total duration from ticket opened to last event.
        Reported in hours for readability.
        """
        ct_hrs = case_df["cycle_time_mins"] / 60
        result = {
            "avg_cycle_hrs":    round(float(ct_hrs.mean()),            2),
            "median_cycle_hrs": round(float(ct_hrs.median()),          2),
            "min_cycle_hrs":    round(float(ct_hrs.min()),             2),
            "max_cycle_hrs":    round(float(ct_hrs.max()),             2),
        }
        # Add each configured percentile
        for p in PERCENTILES:
            key = f"p{p}_cycle_hrs"
            result[key] = round(float(ct_hrs.quantile(p / 100)), 2)
        return result

    def _sla_kpis(self, case_df) -> dict:
        """
        SLA breach = resolution_time_hrs > SLA_THRESHOLD_HRS from config.yaml.
        Default threshold is 48 hours.
        """
        total        = len(case_df)
        breached     = int((case_df["resolution_time_hrs"] > SLA_THRESHOLD_HRS).sum())
        breach_rate  = round(breached / total * 100, 2) if total else 0.0

        return {
            "sla_threshold_hrs": SLA_THRESHOLD_HRS,
            "sla_breached":      breached,
            "sla_compliant":     total - breached,
            "sla_breach_rate":   breach_rate,
        }

    def _resolution_kpis(self, event_df, case_df) -> dict:
        """
        Resolution rate = % of cases that reached 'ticket resolved'.
        Escalation rate = % of cases where escalated = True.
        Throughput      = avg cases closed per day.
        """
        total_cases = case_df["case_id"].nunique()

        resolved_cases = event_df[
            event_df["activity"] == "ticket resolved"
        ]["case_id"].nunique()

        resolution_rate = round(resolved_cases / total_cases * 100, 2) \
            if total_cases else 0.0

        escalation_rate = round(
            case_df["escalated"].sum() / total_cases * 100, 2
        ) if total_cases else 0.0

        # Throughput: cases resolved per day
        resolved_df = event_df[event_df["activity"] == "ticket resolved"].copy()
        if not resolved_df.empty:
            resolved_df["date"] = resolved_df["timestamp"].dt.date
            days = resolved_df["date"].nunique()
            throughput = round(len(resolved_df) / days, 1) if days else 0.0
        else:
            throughput = 0.0

        return {
            "resolved_cases":   int(resolved_cases),
            "resolution_rate":  resolution_rate,
            "escalation_rate":  escalation_rate,
            "throughput_per_day": throughput,
        }

    def _bottleneck_kpis(self, event_df) -> list:
        """
        Bottleneck activities = activities with highest average wait time.
        wait_time_mins is the gap from the previous event in the same case.
        Only activities exceeding BOTTLENECK_THRESHOLD_MINS are returned.

        Returns list of dicts sorted by avg_wait_mins descending.
        """
        df = event_df[event_df["wait_time_mins"].notna()].copy()
        if df.empty:
            return []

        agg = (
            df.groupby("activity")["wait_time_mins"]
            .agg(avg_wait_mins="mean", max_wait_mins="max", occurrences="count")
            .reset_index()
        )
        agg["avg_wait_mins"] = agg["avg_wait_mins"].round(2)
        agg["max_wait_mins"] = agg["max_wait_mins"].round(2)

        # Filter to only meaningful bottlenecks
        agg = agg[agg["avg_wait_mins"] >= BOTTLENECK_MINS]
        agg = agg.sort_values("avg_wait_mins", ascending=False)

        return agg.to_dict(orient="records")

    def _volume_by_col(self, case_df, col: str) -> dict:
        """Count of cases grouped by a categorical column (priority/category)."""
        if col not in case_df.columns:
            return {}
        counts = case_df[col].value_counts()
        return {str(k): int(v) for k, v in counts.items()}

    def _daily_trend(self, event_df) -> list:
        """
        Events per calendar day — used for the trend line chart.
        Returns list of {"date": "YYYY-MM-DD", "events": N}
        sorted by date ascending.
        """
        df = event_df.copy()
        df["date"] = df["timestamp"].dt.date.astype(str)
        daily = (
            df.groupby("date")
            .size()
            .reset_index(name="events")
            .sort_values("date")
        )
        return daily.to_dict(orient="records")

    def _hourly_heatmap(self, event_df) -> list:
        """
        Event count by hour-of-day and day-of-week.
        Used for the activity heatmap on the dashboard.
        Returns list of {"hour": H, "day": D, "count": N}
        where day 0=Monday, day 6=Sunday.
        """
        df = event_df.copy()
        df["hour"] = df["timestamp"].dt.hour
        df["day"]  = df["timestamp"].dt.dayofweek
        heatmap = (
            df.groupby(["day", "hour"])
            .size()
            .reset_index(name="count")
        )
        return heatmap.to_dict(orient="records")

    def _empty_result(self) -> dict:
        """Return zero-value KPIs when no data matches the filters."""
        return {
            "total_cases": 0, "total_events": 0, "avg_events_per_case": 0,
            "avg_cycle_hrs": 0, "median_cycle_hrs": 0,
            "min_cycle_hrs": 0, "max_cycle_hrs": 0,
            "sla_threshold_hrs": SLA_THRESHOLD_HRS,
            "sla_breached": 0, "sla_compliant": 0, "sla_breach_rate": 0,
            "resolved_cases": 0, "resolution_rate": 0,
            "escalation_rate": 0, "throughput_per_day": 0,
            "bottlenecks": [], "priority_volume": {},
            "category_volume": {}, "daily_trend": [], "hourly_heatmap": [],
        }


# ──────────────────────────────────────────────────────────────
# QUICK TEST — python -m analytics.kpis
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    kpis = KPIEngine()

    print("\n── Full dataset KPIs ──\n")
    result = kpis.compute(source="helpdesk")

    # Print all scalar KPIs
    for k, v in result.items():
        if not isinstance(v, (list, dict)):
            print(f"  {k:<28} {v}")

    print("\n── Bottleneck activities ──")
    for b in result["bottlenecks"]:
        print(f"  {b['activity']:<35} avg wait: {b['avg_wait_mins']:>8.1f} min  "
              f"occurrences: {b['occurrences']:>8,}")

    print("\n── Volume by priority ──")
    for p, c in result["priority_volume"].items():
        print(f"  {p:<12} {c:>8,}")

    print("\n── Volume by category ──")
    for cat, c in result["category_volume"].items():
        print(f"  {cat:<20} {c:>8,}")

    print("\n── Daily trend (first 5 days) ──")
    for row in result["daily_trend"][:5]:
        print(f"  {row['date']}  {row['events']:>8,} events")

    print("\n── High priority KPIs ──")
    high = kpis.compute(source="helpdesk", priority="High")
    print(f"  total_cases      {high['total_cases']:>8,}")
    print(f"  sla_breach_rate  {high['sla_breach_rate']:>7}%")
    print(f"  escalation_rate  {high['escalation_rate']:>7}%")