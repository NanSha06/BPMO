"""
analytics/bottlenecks.py
========================
Business Process Mining & Optimization Platform — Phase 1
Step 3b: Bottleneck Detection Engine

What this file does
-------------------
Goes deeper than kpis.py on bottleneck analysis. While kpis.py gives
headline numbers, this module gives the full picture:

    • Activity-level wait time breakdown
    • Case-level bottleneck identification
    • Priority-based bottleneck comparison
      (are High priority tickets slower at the same steps?)
    • Rework loop detection
      (cases that visit the same activity more than once)
    • Handoff analysis
      (which activity transitions take the longest)

Usage
-----
    from analytics.bottlenecks import BottleneckEngine

    engine = BottleneckEngine()

    # Full bottleneck report
    report = engine.analyse(source="helpdesk")

    # Filtered
    report = engine.analyse(source="helpdesk", priority="Critical")

    # Individual analyses
    engine.activity_wait_times(source="helpdesk")
    engine.slow_transitions(source="helpdesk", top_n=10)
    engine.rework_loops(source="helpdesk")
    engine.compare_by_priority(source="helpdesk")
"""

import sys
import pandas as pd
from pathlib import Path
from sqlalchemy import create_engine, text

# ── Config ───────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config_loader import get_database_url, config

SLA_THRESHOLD_HRS = config["kpis"]["sla_threshold_hrs"]
BOTTLENECK_MINS   = config["kpis"]["bottleneck_threshold_mins"]


def _get_engine():
    return create_engine(get_database_url(), pool_pre_ping=True)


class BottleneckEngine:
    """
    Deep bottleneck analysis from the event_log table.
    All methods return plain dicts/lists for dashboard and API consumption.
    """

    def __init__(self):
        self.engine = _get_engine()

    # ──────────────────────────────────────────────────────────
    # PUBLIC: full report
    # ──────────────────────────────────────────────────────────

    def analyse(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
    ) -> dict:
        """
        Run all bottleneck analyses and return combined report.

        Returns
        -------
        dict with keys:
            activity_wait_times   — wait time stats per activity
            slow_transitions      — slowest activity-to-activity handoffs
            rework_loops          — cases visiting same activity multiple times
            priority_comparison   — wait times split by priority
            summary               — headline bottleneck findings
        """
        print("[BOTTLENECK] Running bottleneck analysis ...")
        df = self._load_events(source, priority, category)

        if df.empty:
            print("[BOTTLENECK] No data found for given filters.")
            return {}

        awt   = self.activity_wait_times(df=df)
        trans = self.slow_transitions(df=df)
        loops = self.rework_loops(df=df)
        pri   = self.compare_by_priority(source=source, category=category)
        summ  = self._build_summary(awt, trans, loops)

        print(f"[BOTTLENECK] Done. "
              f"Top bottleneck: {summ.get('top_bottleneck_activity')} "
              f"({summ.get('top_bottleneck_wait_mins')} min avg wait)")

        return {
            "activity_wait_times": awt,
            "slow_transitions":    trans,
            "rework_loops":        loops,
            "priority_comparison": pri,
            "summary":             summ,
        }

    # ──────────────────────────────────────────────────────────
    # PUBLIC: individual analyses
    # ──────────────────────────────────────────────────────────

    def activity_wait_times(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
        df:       pd.DataFrame = None,
    ) -> list:
        """
        For each activity, compute wait time statistics.

        wait_time_mins = time between the previous event and this event
        in the same case. High wait time = cases are sitting idle before
        this activity starts — the definition of a bottleneck.

        Returns list of dicts sorted by avg_wait_mins descending:
            activity, avg_wait_mins, median_wait_mins,
            p90_wait_mins, max_wait_mins, occurrences
        """
        if df is None:
            df = self._load_events(source, priority, category)

        df = df[df["wait_time_mins"].notna() & (df["wait_time_mins"] > 0)]
        if df.empty:
            return []

        agg = (
            df.groupby("activity")["wait_time_mins"]
            .agg(
                avg_wait_mins    = "mean",
                median_wait_mins = "median",
                p90_wait_mins    = lambda x: x.quantile(0.9),
                max_wait_mins    = "max",
                occurrences      = "count",
            )
            .reset_index()
        )

        for col in ["avg_wait_mins","median_wait_mins","p90_wait_mins","max_wait_mins"]:
            agg[col] = agg[col].round(2)

        agg = agg.sort_values("avg_wait_mins", ascending=False)
        return agg.to_dict(orient="records")

    def slow_transitions(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
        top_n:    int = 10,
        df:       pd.DataFrame = None,
    ) -> list:
        """
        Find the slowest activity-to-activity transitions.

        For each consecutive pair of events in a case, compute the
        time gap. Returns the top_n transitions by average gap.

        Returns list of dicts:
            from_activity, to_activity,
            avg_gap_mins, max_gap_mins, occurrences
        """
        if df is None:
            df = self._load_events(source, priority, category)
        if df.empty:
            return []

        df = df.sort_values(["case_id", "timestamp"]).copy()

        # Shift to get the previous activity and its timestamp
        df["next_activity"]  = df.groupby("case_id")["activity"].shift(-1)
        df["next_timestamp"] = df.groupby("case_id")["timestamp"].shift(-1)

        # Keep only rows that have a following event
        transitions = df[df["next_activity"].notna()].copy()
        transitions["gap_mins"] = (
            (transitions["next_timestamp"] - transitions["timestamp"])
            .dt.total_seconds() / 60
        ).round(2)

        agg = (
            transitions.groupby(["activity", "next_activity"])["gap_mins"]
            .agg(
                avg_gap_mins = "mean",
                max_gap_mins = "max",
                occurrences  = "count",
            )
            .reset_index()
            .rename(columns={
                "activity":      "from_activity",
                "next_activity": "to_activity",
            })
        )

        for col in ["avg_gap_mins", "max_gap_mins"]:
            agg[col] = agg[col].round(2)

        agg = agg.sort_values("avg_gap_mins", ascending=False).head(top_n)
        return agg.to_dict(orient="records")

    def rework_loops(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
        df:       pd.DataFrame = None,
    ) -> dict:
        """
        Detect cases that visit the same activity more than once.
        These are rework loops — a process inefficiency.

        Returns dict:
            total_rework_cases  — number of cases with at least one loop
            rework_rate         — % of all cases
            activities_with_loops — list of {activity, loop_count, case_count}
            top_rework_cases    — list of {case_id, repeated_activity, visits}
        """
        if df is None:
            df = self._load_events(source, priority, category)
        if df.empty:
            return {}

        total_cases = df["case_id"].nunique()

        # Count visits per case per activity
        visit_counts = (
            df.groupby(["case_id", "activity"])
            .size()
            .reset_index(name="visits")
        )

        # Keep only cases where an activity appears more than once
        loops = visit_counts[visit_counts["visits"] > 1].copy()

        if loops.empty:
            return {
                "total_rework_cases":    0,
                "rework_rate":           0.0,
                "activities_with_loops": [],
                "top_rework_cases":      [],
            }

        rework_cases = loops["case_id"].nunique()
        rework_rate  = round(rework_cases / total_cases * 100, 2)

        # Which activities have the most loops
        act_loops = (
            loops.groupby("activity")
            .agg(loop_count=("visits", "sum"), case_count=("case_id", "count"))
            .reset_index()
            .sort_values("case_count", ascending=False)
        )

        # Top 20 worst rework cases
        top_cases = (
            loops.sort_values("visits", ascending=False)
            .head(20)
            .rename(columns={"activity": "repeated_activity"})
            .to_dict(orient="records")
        )

        return {
            "total_rework_cases":    int(rework_cases),
            "rework_rate":           rework_rate,
            "activities_with_loops": act_loops.to_dict(orient="records"),
            "top_rework_cases":      top_cases,
        }

    def compare_by_priority(
        self,
        source:   str = None,
        category: str = None,
    ) -> list:
        """
        Compare avg wait times per activity broken down by priority.

        Answers: "Are Critical tickets faster through the same steps?"

        Returns list of dicts:
            activity, priority, avg_wait_mins, case_count
        """
        where_parts, params = [], {}
        if source:
            where_parts.append("source = :source")
            params["source"] = source
        if category and category.lower() != "all":
            where_parts.append("category = :category")
            params["category"] = category

        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        query = f"""
            SELECT activity, priority, wait_time_mins
            FROM   event_log
            {where}
            AND    wait_time_mins IS NOT NULL
            AND    wait_time_mins > 0
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)

        if df.empty:
            return []

        agg = (
            df.groupby(["activity", "priority"])["wait_time_mins"]
            .agg(avg_wait_mins="mean", case_count="count")
            .reset_index()
        )
        agg["avg_wait_mins"] = agg["avg_wait_mins"].round(2)
        agg = agg.sort_values(["activity", "avg_wait_mins"], ascending=[True, False])
        return agg.to_dict(orient="records")

    # ──────────────────────────────────────────────────────────
    # PRIVATE: data loader
    # ──────────────────────────────────────────────────────────

    def _load_events(self, source, priority, category) -> pd.DataFrame:
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

        query = f"""
            SELECT case_id, activity, timestamp,
                   priority, category, wait_time_mins
            FROM   event_log
            {where}
            ORDER  BY case_id, timestamp
        """
        with self.engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    # ──────────────────────────────────────────────────────────
    # PRIVATE: summary
    # ──────────────────────────────────────────────────────────

    def _build_summary(self, awt, trans, loops) -> dict:
        top_act   = awt[0]  if awt   else {}
        top_trans = trans[0] if trans else {}
        return {
            "top_bottleneck_activity":   top_act.get("activity"),
            "top_bottleneck_wait_mins":  top_act.get("avg_wait_mins"),
            "slowest_transition":        (
                f"{top_trans.get('from_activity')} → {top_trans.get('to_activity')}"
                if top_trans else None
            ),
            "slowest_transition_mins":   top_trans.get("avg_gap_mins"),
            "total_rework_cases":        loops.get("total_rework_cases", 0),
            "rework_rate":               loops.get("rework_rate", 0.0),
        }


# ──────────────────────────────────────────────────────────────
# QUICK TEST — python -m analytics.bottlenecks
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    engine = BottleneckEngine()

    print("\n── Activity wait times ──")
    awt = engine.activity_wait_times(source="helpdesk")
    for a in awt:
        print(f"  {a['activity']:<35} "
              f"avg: {a['avg_wait_mins']:>8.1f} min  "
              f"p90: {a['p90_wait_mins']:>8.1f} min  "
              f"n: {a['occurrences']:>8,}")

    print("\n── Slowest transitions (top 5) ──")
    trans = engine.slow_transitions(source="helpdesk", top_n=5)
    for t in trans:
        print(f"  {t['from_activity']:<30} → {t['to_activity']:<30} "
              f"avg: {t['avg_gap_mins']:>8.1f} min")

    print("\n── Rework loops ──")
    loops = engine.rework_loops(source="helpdesk")
    print(f"  Rework cases : {loops.get('total_rework_cases', 0):,}")
    print(f"  Rework rate  : {loops.get('rework_rate', 0)}%")
    for a in loops.get("activities_with_loops", []):
        print(f"  {a['activity']:<35} loops: {a['loop_count']:>6,}  "
              f"cases: {a['case_count']:>6,}")

    print("\n── Priority comparison (Critical vs Low) ──")
    pri = engine.compare_by_priority(source="helpdesk")
    df  = pd.DataFrame(pri)
    if not df.empty:
        pivot = df.pivot_table(
            index="activity", columns="priority",
            values="avg_wait_mins", aggfunc="first"
        ).round(1)
        print(pivot.to_string())