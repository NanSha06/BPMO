"""
process_mining/variants.py
==========================
Business Process Mining & Optimization Platform — Phase 1
Step 4: Process Variant Analysis

What this file does
-------------------
A process variant is the unique ordered sequence of activities
a case goes through. For example:

    Variant A: ticket opened → ticket resolved             (35%)
    Variant B: ticket opened → ticket escalated → resolved (35%)
    Variant C: ticket opened → escalated → status: on hold  (3%)

This module provides:

    1. Variant frequency table  — how often each path occurs
    2. Ideal vs actual comparison — flags deviations from happy path
    3. Per-variant KPIs  — cycle time, resolution rate per variant
    4. Priority breakdown — which priorities take which paths
    5. Category breakdown — which categories deviate most
    6. Deviation detection — cases that took unusual paths

The ideal process (happy path) is defined as the most frequent
variant that ends in 'ticket resolved'.

Usage
-----
    from process_mining.variants import VariantAnalyser

    va = VariantAnalyser()

    # Full variant report
    report = va.analyse(source="helpdesk")

    # Top N variants only
    variants = va.get_top_variants(source="helpdesk", top_n=10)

    # Compare ideal vs actual
    comparison = va.ideal_vs_actual(source="helpdesk")

    # Deviating cases
    deviations = va.get_deviating_cases(source="helpdesk", top_n=50)
"""

import sys
import pandas as pd
from pathlib import Path
from sqlalchemy import create_engine, text

import pm4py

# ── Config ───────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config_loader import get_database_url, config

TOP_N_VARIANTS  = config["variants"]["top_n"]
MIN_VARIANT_CNT = config["variants"]["min_variant_count"]
HAPPY_PATH_END  = "ticket resolved"      # activity that defines a successful case


def _get_engine():
    return create_engine(get_database_url(), pool_pre_ping=True)


class VariantAnalyser:
    """
    Analyses process variants from the event_log table.
    All methods return plain dicts/lists for dashboard and API use.
    """

    def __init__(self):
        self.engine = _get_engine()

    # ──────────────────────────────────────────────────────────
    # PUBLIC: main entry point
    # ──────────────────────────────────────────────────────────

    def analyse(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
        top_n:    int = None,
    ) -> dict:
        """
        Run all variant analyses and return a combined report.

        Returns
        -------
        dict with keys:
            top_variants        — frequency table of top N variants
            ideal_vs_actual     — happy path comparison
            priority_breakdown  — variant distribution by priority
            category_breakdown  — variant distribution by category
            deviating_cases     — cases that did not follow the happy path
            summary             — headline findings
        """
        print("[VARIANTS] Starting variant analysis ...")
        top_n = top_n or TOP_N_VARIANTS

        df       = self._load_events(source, priority, category)
        case_seq = self._build_case_sequences(df)

        if case_seq.empty:
            print("[VARIANTS] No data found.")
            return {}

        top_variants    = self._variant_frequency(case_seq, top_n)
        ideal           = self._detect_ideal_path(top_variants)
        iva             = self._ideal_vs_actual(case_seq, ideal, top_variants)
        pri_breakdown   = self._breakdown_by_col(case_seq, "priority",  top_n)
        cat_breakdown   = self._breakdown_by_col(case_seq, "category",  top_n)
        deviations      = self._deviating_cases(case_seq, ideal)
        summary         = self._build_summary(
            case_seq, top_variants, ideal, deviations
        )

        print(
            f"[VARIANTS] Done. "
            f"{summary['total_variants']} unique variants | "
            f"Happy path: {summary['happy_path_pct']}% of cases"
        )

        return {
            "top_variants":       top_variants,
            "ideal_vs_actual":    iva,
            "priority_breakdown": pri_breakdown,
            "category_breakdown": cat_breakdown,
            "deviating_cases":    deviations[:50],  # cap at 50 for API response
            "summary":            summary,
        }

    # ──────────────────────────────────────────────────────────
    # PUBLIC: individual analyses
    # ──────────────────────────────────────────────────────────

    def get_top_variants(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
        top_n:    int = None,
    ) -> list:
        """
        Return the top N most frequent variants with stats.

        Returns list of dicts:
            rank, variant (list), count, pct,
            avg_cycle_mins, is_happy_path
        """
        top_n    = top_n or TOP_N_VARIANTS
        df       = self._load_events(source, priority, category)
        case_seq = self._build_case_sequences(df)
        return self._variant_frequency(case_seq, top_n)

    def ideal_vs_actual(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
    ) -> dict:
        """
        Compare the ideal (happy path) variant against all others.

        Returns dict with:
            ideal_path          — list of activity names
            ideal_count         — how many cases followed it
            ideal_pct           — % of total cases
            deviation_count     — cases that deviated
            deviation_pct       — % of cases that deviated
            deviation_reasons   — most common deviation patterns
        """
        df       = self._load_events(source, priority, category)
        case_seq = self._build_case_sequences(df)
        top_variants = self._variant_frequency(case_seq, TOP_N_VARIANTS)
        ideal    = self._detect_ideal_path(top_variants)
        return self._ideal_vs_actual(case_seq, ideal, top_variants)

    def get_deviating_cases(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
        top_n:    int = 50,
    ) -> list:
        """
        Return cases that did not follow the ideal (happy path) variant.

        Returns list of dicts:
            case_id, variant (list), cycle_time_mins, priority, category
        """
        df       = self._load_events(source, priority, category)
        case_seq = self._build_case_sequences(df)
        top_variants = self._variant_frequency(case_seq, TOP_N_VARIANTS)
        ideal    = self._detect_ideal_path(top_variants)
        return self._deviating_cases(case_seq, ideal)[:top_n]

    # ──────────────────────────────────────────────────────────
    # PRIVATE: data loading
    # ──────────────────────────────────────────────────────────

    def _load_events(
        self,
        source:   str = None,
        priority: str = None,
        category: str = None,
    ) -> pd.DataFrame:
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
                   priority, category, cycle_time_mins
            FROM   event_log
            {where}
            ORDER  BY case_id, timestamp
        """
        with self.engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    # ──────────────────────────────────────────────────────────
    # PRIVATE: core variant logic
    # ──────────────────────────────────────────────────────────

    def _build_case_sequences(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert event-level rows into one row per case with:
            case_id, variant (tuple), priority, category, cycle_time_mins

        This is the foundation for all variant analyses.
        """
        if df.empty:
            return pd.DataFrame()

        df = df.sort_values(["case_id", "timestamp"])

        # Build ordered activity sequence per case
        sequences = (
            df.groupby("case_id")["activity"]
            .apply(tuple)
            .reset_index()
            .rename(columns={"activity": "variant"})
        )

        # Attach metadata — take first occurrence per case
        meta = df.drop_duplicates("case_id")[
            ["case_id", "priority", "category", "cycle_time_mins"]
        ]
        case_seq = sequences.merge(meta, on="case_id", how="left")
        return case_seq

    def _variant_frequency(
        self, case_seq: pd.DataFrame, top_n: int
    ) -> list:
        """
        Compute frequency table for all variants.

        Returns list of dicts sorted by count descending:
            rank, variant (list of str), count, pct,
            avg_cycle_mins, is_happy_path
        """
        if case_seq.empty:
            return []

        total = len(case_seq)

        agg = (
            case_seq.groupby("variant")
            .agg(
                count          = ("case_id",        "count"),
                avg_cycle_mins = ("cycle_time_mins", "mean"),
            )
            .reset_index()
        )
        agg["pct"]           = (agg["count"] / total * 100).round(2)
        agg["avg_cycle_mins"]= agg["avg_cycle_mins"].round(2)

        # Filter out very rare variants
        agg = agg[agg["count"] >= MIN_VARIANT_CNT]
        agg = agg.sort_values("count", ascending=False).head(top_n)

        result = []
        for rank, (_, row) in enumerate(agg.iterrows(), start=1):
            variant_list = list(row["variant"])
            result.append({
                "rank":           rank,
                "variant":        variant_list,
                "variant_str":    " → ".join(variant_list),
                "count":          int(row["count"]),
                "pct":            float(row["pct"]),
                "avg_cycle_mins": float(row["avg_cycle_mins"]),
                "is_happy_path":  variant_list[-1] == HAPPY_PATH_END,
                "step_count":     len(variant_list),
            })
        return result

    def _detect_ideal_path(self, top_variants: list) -> tuple:
        """
        The ideal path is the most frequent variant that ends
        in 'ticket resolved'. Falls back to most frequent overall.
        """
        # Prefer variants that end in the happy path activity
        resolved = [
            v for v in top_variants
            if v["variant"] and v["variant"][-1] == HAPPY_PATH_END
        ]
        if resolved:
            return tuple(resolved[0]["variant"])

        # Fallback — most frequent variant regardless of end activity
        if top_variants:
            return tuple(top_variants[0]["variant"])

        return ()

    def _ideal_vs_actual(
        self,
        case_seq:     pd.DataFrame,
        ideal:        tuple,
        top_variants: list,
    ) -> dict:
        """
        Compare how many cases followed the ideal path vs deviated.
        Also identifies the most common deviation patterns.
        """
        if case_seq.empty or not ideal:
            return {}

        total         = len(case_seq)
        ideal_cases   = int((case_seq["variant"] == ideal).sum())
        ideal_pct     = round(ideal_cases / total * 100, 2)
        deviation_cnt = total - ideal_cases
        deviation_pct = round(deviation_cnt / total * 100, 2)

        # Common deviation patterns = top variants that are NOT the ideal path
        deviation_patterns = [
            {
                "variant":        v["variant"],
                "variant_str":    v["variant_str"],
                "count":          v["count"],
                "pct":            v["pct"],
                "avg_cycle_mins": v["avg_cycle_mins"],
            }
            for v in top_variants
            if tuple(v["variant"]) != ideal
        ][:5]  # top 5 deviations

        return {
            "ideal_path":         list(ideal),
            "ideal_path_str":     " → ".join(ideal),
            "ideal_count":        ideal_cases,
            "ideal_pct":          ideal_pct,
            "deviation_count":    deviation_cnt,
            "deviation_pct":      deviation_pct,
            "deviation_patterns": deviation_patterns,
        }

    def _breakdown_by_col(
        self,
        case_seq: pd.DataFrame,
        col:      str,
        top_n:    int,
    ) -> list:
        """
        Show variant distribution for each value of a column
        (priority or category).

        For each column value, returns the top 3 variants and
        their share of that group's cases.

        Returns list of dicts:
            {col_value}, variant, variant_str, count, pct_of_group
        """
        if col not in case_seq.columns or case_seq.empty:
            return []

        results = []
        for group_val, group_df in case_seq.groupby(col):
            group_total = len(group_df)
            top = (
                group_df.groupby("variant")["case_id"]
                .count()
                .reset_index(name="count")
                .sort_values("count", ascending=False)
                .head(3)
            )
            for _, row in top.iterrows():
                variant_list = list(row["variant"])
                results.append({
                    col:            str(group_val),
                    "variant":      variant_list,
                    "variant_str":  " → ".join(variant_list),
                    "count":        int(row["count"]),
                    "pct_of_group": round(row["count"] / group_total * 100, 2),
                })

        return sorted(results, key=lambda x: -x["count"])

    def _deviating_cases(
        self,
        case_seq: pd.DataFrame,
        ideal:    tuple,
    ) -> list:
        """
        Return all cases that did NOT follow the ideal path,
        sorted by cycle time descending (worst offenders first).

        Returns list of dicts:
            case_id, variant (list), variant_str,
            cycle_time_mins, priority, category
        """
        if case_seq.empty or not ideal:
            return []

        deviations = case_seq[case_seq["variant"] != ideal].copy()
        deviations  = deviations.sort_values("cycle_time_mins", ascending=False)

        result = []
        for _, row in deviations.iterrows():
            variant_list = list(row["variant"])
            result.append({
                "case_id":        str(row["case_id"]),
                "variant":        variant_list,
                "variant_str":    " → ".join(variant_list),
                "cycle_time_mins":round(float(row["cycle_time_mins"]), 2)
                                  if pd.notna(row["cycle_time_mins"]) else None,
                "priority":       str(row["priority"]),
                "category":       str(row["category"]),
            })
        return result

    def _build_summary(
        self,
        case_seq:     pd.DataFrame,
        top_variants: list,
        ideal:        tuple,
        deviations:   list,
    ) -> dict:
        total          = len(case_seq)
        total_variants = case_seq["variant"].nunique()
        ideal_count    = int((case_seq["variant"] == ideal).sum())
        happy_path_pct = round(ideal_count / total * 100, 2) if total else 0

        # Most complex variant (most steps)
        most_complex = max(top_variants, key=lambda x: x["step_count"]) \
            if top_variants else {}

        # Variant that takes longest on average
        slowest = max(top_variants, key=lambda x: x["avg_cycle_mins"]) \
            if top_variants else {}

        return {
            "total_cases":           total,
            "total_variants":        int(total_variants),
            "happy_path":            list(ideal),
            "happy_path_str":        " → ".join(ideal),
            "happy_path_count":      ideal_count,
            "happy_path_pct":        happy_path_pct,
            "deviation_count":       len(deviations),
            "deviation_pct":         round((total - ideal_count) / total * 100, 2)
                                     if total else 0,
            "most_complex_variant":  most_complex.get("variant_str"),
            "most_complex_steps":    most_complex.get("step_count"),
            "slowest_variant":       slowest.get("variant_str"),
            "slowest_avg_cycle_mins":slowest.get("avg_cycle_mins"),
        }


# ──────────────────────────────────────────────────────────────
# QUICK TEST — python -m process_mining.variants
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    va = VariantAnalyser()

    print("\n── Top 10 variants ──\n")
    variants = va.get_top_variants(source="helpdesk", top_n=10)
    for v in variants:
        flag = "✓ happy" if v["is_happy_path"] else "✗ deviation"
        print(f"  #{v['rank']:>2}  {v['pct']:>6.2f}%  "
              f"{v['count']:>9,}  steps:{v['step_count']}  "
              f"{flag:<12}  {v['variant_str']}")

    print("\n── Ideal vs Actual ──\n")
    iva = va.ideal_vs_actual(source="helpdesk")
    print(f"  Ideal path   : {iva['ideal_path_str']}")
    print(f"  Ideal cases  : {iva['ideal_count']:,} ({iva['ideal_pct']}%)")
    print(f"  Deviations   : {iva['deviation_count']:,} ({iva['deviation_pct']}%)")
    print(f"\n  Top deviation patterns:")
    for d in iva.get("deviation_patterns", []):
        print(f"    {d['pct']:>6.2f}%  {d['count']:>8,}  {d['variant_str']}")

    print("\n── Priority breakdown ──\n")
    pri = va.analyse(source="helpdesk")["priority_breakdown"]
    current_pri = None
    for row in pri[:12]:
        if row["priority"] != current_pri:
            current_pri = row["priority"]
            print(f"  [{current_pri}]")
        print(f"    {row['pct_of_group']:>6.2f}%  "
              f"{row['count']:>8,}  {row['variant_str']}")

    print("\n── Summary ──\n")
    summary = va.analyse(source="helpdesk")["summary"]
    for k, v in summary.items():
        print(f"  {k:<30} {v}")