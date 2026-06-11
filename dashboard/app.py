"""
dashboard/app.py
================
Business Process Mining & Optimization Platform — Phase 1
Step 5b: Streamlit Dashboard — Main Entry Point

What this file does
-------------------
Wires together all Phase 1 modules into a single interactive
web dashboard. The user can:

    • Filter by source, priority, and category
    • View the actual process flow as a Sankey diagram
    • See 5 headline KPI cards at the top
    • Explore top process variants and deviations
    • Identify bottleneck activities by wait time
    • View daily event volume trend
    • See activity heatmap by hour and weekday

Architecture
------------
    app.py          ← you are here (layout + wiring)
    components.py   ← all charts and tables
    analytics/kpis.py           ← KPI computation
    analytics/bottlenecks.py    ← bottleneck analysis
    process_mining/discovery.py ← DFG + process flow
    process_mining/variants.py  ← variant analysis

Run
---
    cd C:\\Users\\hp\\OneDrive\\Desktop\\BPMO
    streamlit run dashboard/app.py
"""

import sys
import streamlit as st
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────
# Lets app.py find all sibling modules from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_loader import config

from analytics.kpis          import KPIEngine
from analytics.bottlenecks   import BottleneckEngine
from process_mining.discovery import ProcessDiscovery
from process_mining.variants  import VariantAnalyser

from dashboard.components import (
    kpi_cards,
    process_flow_chart,
    bottleneck_chart,
    variant_table,
    ideal_vs_actual_card,
    priority_pie,
    category_bar,
    daily_trend_chart,
    hourly_heatmap,
    deviations_table,
    cycle_time_distribution,
)

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title = config["dashboard"]["title"],
    page_icon  = config["dashboard"]["page_icon"],
    layout     = config["dashboard"]["layout"],
    initial_sidebar_state = "expanded",
)

# ── Custom CSS ────────────────────────────────────────────────
st.markdown("""
<style>
    /* ── Force white/light backgrounds everywhere ── */
    .stApp                          { background-color: #F8FAFF !important; }
    .main .block-container          { background-color: #F8FAFF !important;
                                      padding-top: 1.8rem; }
    section[data-testid="stSidebar"]{ background-color: #EEF2FF !important;
                                      border-right: 1.5px solid #C7D2FE; }

    /* ── Headings ── */
    h1 { color: #1E1B4B !important; font-size: 2rem !important;
         font-weight: 800 !important; letter-spacing: -0.5px; }
    h2 { color: #3730A3 !important; font-size: 1.15rem !important;
         font-weight: 700 !important; margin-top: 1.6rem !important; }
    h3 { color: #4F46E5 !important; }

    /* ── KPI metric cards ── */
    [data-testid="metric-container"] {
        background      : #FFFFFF !important;
        border          : 2px solid #C7D2FE !important;
        border-radius   : 14px !important;
        padding         : 18px 22px !important;
        box-shadow      : 0 2px 8px rgba(99,102,241,0.10) !important;
    }
    [data-testid="metric-container"] label {
        color       : #6366F1 !important;
        font-weight : 700 !important;
        font-size   : 0.80rem !important;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        color       : #1E1B4B !important;
        font-size   : 1.65rem !important;
        font-weight : 800 !important;
    }
    [data-testid="metric-container"] [data-testid="stMetricDelta"] {
        font-size   : 0.78rem !important;
    }

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] * { color: #1E1B4B !important; }
    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stSlider    label {
        color: #3730A3 !important; font-weight: 700 !important;
    }

    /* ── Dividers ── */
    hr { border-color: #C7D2FE !important; margin: 1.2rem 0 !important; }

    /* ── DataFrames ── */
    .stDataFrame { border-radius: 10px !important;
                   border: 1.5px solid #E0E7FF !important; }

    /* ── Plotly chart containers ── */
    [data-testid="stPlotlyChart"] {
        border-radius : 14px !important;
        border        : 1.5px solid #E0E7FF !important;
        box-shadow    : 0 2px 8px rgba(99,102,241,0.07) !important;
        padding       : 8px !important;
        background    : #FFFFFF !important;
    }

    /* ── Info / success / error boxes ── */
    .stAlert { border-radius: 10px !important; }

    /* ── Caption / footer ── */
    .stCaption { color: #6366F1 !important; font-size: 0.78rem !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# CACHED DATA LOADERS
# st.cache_data caches results for the session.
# The cache is invalidated when filter parameters change.
# ─────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def load_kpis(source, priority, category):
    return KPIEngine().compute(
        source=source, priority=priority, category=category
    )

@st.cache_data(show_spinner=False)
def load_bottlenecks(source, priority, category):
    return BottleneckEngine().analyse(
        source=source, priority=priority, category=category
    )

@st.cache_data(show_spinner=False)
def load_process_flow(source, priority, category):
    return ProcessDiscovery().get_dfg_for_display(
        source=source, priority=priority, category=category,
        min_edge_count=500,
    )

@st.cache_data(show_spinner=False)
def load_variants(source, priority, category):
    return VariantAnalyser().analyse(
        source=source, priority=priority, category=category
    )


# ─────────────────────────────────────────────────────────────
# SIDEBAR — FILTERS
# ─────────────────────────────────────────────────────────────

def render_sidebar() -> dict:
    """Render sidebar filters and return selected values as dict."""
    with st.sidebar:
        st.image(
            "https://img.icons8.com/color/96/process.png",
            width=60
        )
        st.title("Process Mining")
        st.caption("Business Process Mining & Optimization Platform — Phase 1")
        st.divider()

        st.subheader("🔍 Filters")

        source = st.selectbox(
            "Dataset",
            options=["helpdesk"],
            index=0,
            help="Select the event log dataset to analyse."
        )

        priority = st.selectbox(
            "Priority",
            options=["All", "Critical", "High", "Medium", "Low"],
            index=0,
            help="Filter tickets by priority level."
        )

        category = st.selectbox(
            "Category",
            options=["All", "Software", "Hardware", "Network", "HR"],
            index=0,
            help="Filter tickets by category."
        )

        st.divider()
        st.subheader("⚙️ Display")

        top_n_variants = st.slider(
            "Top N variants",
            min_value=3, max_value=13, value=8,
            help="Number of process variants to show in the table."
        )

        min_edge_count = st.slider(
            "Min edge count (flow chart)",
            min_value=100, max_value=50000,
            value=5000, step=1000,
            help="Hide process flow edges with fewer occurrences than this."
        )

        st.divider()
        st.caption("Phase 1 — ETL → Discovery → KPIs → Variants → Dashboard")

    return {
        "source":         source,
        "priority":       None if priority == "All" else priority,
        "category":       None if category == "All" else category,
        "top_n_variants": top_n_variants,
        "min_edge_count": min_edge_count,
    }


# ─────────────────────────────────────────────────────────────
# MAIN LAYOUT
# ─────────────────────────────────────────────────────────────

def main():
    # ── Header ────────────────────────────────────────────────
    st.title("📊 Business Process Mining & Optimization Platform")
    st.caption(
        "Discover actual process flows, detect bottlenecks, "
        "and analyse variants from your helpdesk event log."
    )

    # ── Sidebar filters ───────────────────────────────────────
    filters = render_sidebar()
    src  = filters["source"]
    pri  = filters["priority"]
    cat  = filters["category"]
    topn = filters["top_n_variants"]

    # ── Loading spinner ───────────────────────────────────────
    with st.spinner("Loading data..."):
        kpi_data       = load_kpis(src, pri, cat)
        bottleneck_data= load_bottlenecks(src, pri, cat)
        flow_data      = load_process_flow(src, pri, cat)
        variant_data   = load_variants(src, pri, cat)

    # ── KPI cards ─────────────────────────────────────────────
    st.markdown("## 📈 Key Performance Indicators")
    kpi_cards(kpi_data)

    st.divider()

    # ── Process flow + Bottleneck (side by side) ──────────────
    st.markdown("## 🔄 Process Flow & Bottlenecks")
    col_flow, col_bn = st.columns([3, 2])

    with col_flow:
        process_flow_chart(flow_data)

    with col_bn:
        awt = bottleneck_data.get("activity_wait_times", [])
        bottleneck_chart(awt)

    st.divider()

    # ── Variant analysis ──────────────────────────────────────
    st.markdown("## 🧩 Process Variant Analysis")

    ideal_vs_actual_card(variant_data.get("ideal_vs_actual", {}))
    st.markdown("")

    top_variants = variant_data.get("top_variants", [])[:topn]
    variant_table(top_variants)

    st.divider()

    # ── Volume analysis (priority + category) ────────────────
    st.markdown("## 📦 Volume Analysis")
    col_pri, col_cat = st.columns(2)

    with col_pri:
        priority_pie(kpi_data.get("priority_volume", {}))

    with col_cat:
        category_bar(kpi_data.get("category_volume", {}))

    st.divider()

    # ── Cycle time + Daily trend ──────────────────────────────
    st.markdown("## ⏱️ Time Analysis")
    col_ct, col_trend = st.columns(2)

    with col_ct:
        cycle_time_distribution(kpi_data)

    with col_trend:
        daily_trend_chart(kpi_data.get("daily_trend", []))

    st.divider()

    # ── Hourly heatmap ────────────────────────────────────────
    st.markdown("## 🗓️ Activity Heatmap")
    hourly_heatmap(kpi_data.get("hourly_heatmap", []))

    st.divider()

    # ── Slow transitions ──────────────────────────────────────
    st.markdown("## 🐢 Slowest Activity Transitions")
    trans = bottleneck_data.get("slow_transitions", [])
    if trans:
        df_trans = __import__("pandas").DataFrame(trans)
        df_trans["Transition"] = (
            df_trans["from_activity"] + "  →  " + df_trans["to_activity"]
        )
        df_trans["Avg gap (min)"] = df_trans["avg_gap_mins"]
        df_trans["Max gap (min)"] = df_trans["max_gap_mins"]
        df_trans["Occurrences"]   = df_trans["occurrences"].apply(lambda x: f"{x:,}")
        st.dataframe(
            df_trans[["Transition","Avg gap (min)","Max gap (min)","Occurrences"]],
            use_container_width=True,
            height=300,
        )
    else:
        st.info("No transition data available.")

    st.divider()

    # ── Deviating cases ───────────────────────────────────────
    st.markdown("## ⚠️ Deviating Cases")
    deviations = variant_data.get("deviating_cases", [])
    deviations_table(deviations)

    st.divider()

    # ── Rework loops ──────────────────────────────────────────
    rework = bottleneck_data.get("rework_loops", {})
    if rework and rework.get("total_rework_cases", 0) > 0:
        st.markdown("## 🔁 Rework Loops")
        col_r1, col_r2, col_r3 = st.columns(3)
        col_r1.metric("Rework Cases",  f"{rework['total_rework_cases']:,}")
        col_r2.metric("Rework Rate",   f"{rework['rework_rate']}%")
        col_r3.metric("Clean Cases",
            f"{kpi_data['total_cases'] - rework['total_rework_cases']:,}")

        loops_df = __import__("pandas").DataFrame(
            rework.get("activities_with_loops", [])
        )
        if not loops_df.empty:
            st.dataframe(loops_df, use_container_width=True, height=200)

    # ── Footer ────────────────────────────────────────────────
    st.divider()
    st.caption(
        "Business Process Mining & Optimization Platform · Phase 1 · "
        "Built with PM4Py · Streamlit · PostgreSQL"
    )


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()