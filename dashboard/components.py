"""
dashboard/components.py
========================
Business Process Mining & Optimization Platform — Phase 1
Step 5a: Reusable Dashboard Components

What this file does
-------------------
Every chart, card, and table used in the dashboard lives here.
app.py imports these functions and calls them — it never builds
charts directly. This keeps app.py clean and makes every visual
independently testable.

Components
----------
    kpi_cards()           — 5 headline metric cards across the top
    process_flow_chart()  — Sankey diagram of actual process flow
    bottleneck_chart()    — horizontal bar chart of wait times
    variant_table()       — styled frequency table of top variants
    ideal_vs_actual()     — side-by-side comparison card
    priority_pie()        — pie chart of volume by priority
    category_bar()        — bar chart of volume by category
    daily_trend_chart()   — line chart of daily event volume
    hourly_heatmap()      — activity heatmap by hour and weekday
    deviations_table()    — table of cases that deviated from ideal path
"""

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

# ── Colour palette (consistent across all charts) ────────────
COLORS = {
    "primary":    "#4F46E5",   # indigo
    "success":    "#10B981",   # green
    "warning":    "#F59E0B",   # amber
    "danger":     "#EF4444",   # red
    "neutral":    "#6B7280",   # gray
    "background": "#F9FAFB",
}

PRIORITY_COLORS = {
    "Critical": "#EF4444",
    "High":     "#F59E0B",
    "Medium":   "#4F46E5",
    "Low":      "#10B981",
}

CHART_HEIGHT = 420


# ─────────────────────────────────────────────────────────────
# KPI CARDS
# ─────────────────────────────────────────────────────────────

def kpi_cards(kpi_data: dict):
    """
    Render 5 headline KPI metric cards across the top of the dashboard.
    Uses st.metric for native Streamlit delta display.
    """
    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.metric(
            label="Total Tickets",
            value=f"{kpi_data.get('total_cases', 0):,}",
        )
    with c2:
        avg_cycle = kpi_data.get("avg_cycle_hrs", 0)
        st.metric(
            label="Avg Cycle Time",
            value=f"{avg_cycle:.1f} hrs",
        )
    with c3:
        breach = kpi_data.get("sla_breach_rate", 0)
        st.metric(
            label="SLA Breach Rate",
            value=f"{breach}%",
            delta=f"{breach}% breached",
            delta_color="inverse",
        )
    with c4:
        esc = kpi_data.get("escalation_rate", 0)
        st.metric(
            label="Escalation Rate",
            value=f"{esc}%",
            delta_color="inverse",
        )
    with c5:
        res = kpi_data.get("resolution_rate", 0)
        st.metric(
            label="Resolution Rate",
            value=f"{res}%",
            delta_color="normal",
        )


# ─────────────────────────────────────────────────────────────
# PROCESS FLOW — SANKEY DIAGRAM
# ─────────────────────────────────────────────────────────────

def process_flow_chart(dfg_data: dict, title: str = "Actual Process Flow"):
    """
    Render a Sankey diagram from DFG edge data.

    Parameters
    ----------
    dfg_data : dict from ProcessDiscovery.get_dfg_for_display()
        Keys: nodes (list), edges (list of {from, to, count})
    """
    if not dfg_data or not dfg_data.get("edges"):
        st.info("No process flow data available for the current filters.")
        return

    nodes  = dfg_data["nodes"]
    edges  = dfg_data["edges"]
    idx    = {name: i for i, name in enumerate(nodes)}

    # Build Sankey
    sources = [idx[e["from"]] for e in edges if e["from"] in idx and e["to"] in idx]
    targets = [idx[e["to"]]   for e in edges if e["from"] in idx and e["to"] in idx]
    values  = [e["count"]     for e in edges if e["from"] in idx and e["to"] in idx]

    # Colour start/end nodes differently
    start_acts = dfg_data.get("start_activities", [])
    end_acts   = dfg_data.get("end_activities", [])
    node_colors = []
    for n in nodes:
        if n in start_acts:
            node_colors.append(COLORS["success"])
        elif n in end_acts:
            node_colors.append(COLORS["danger"])
        else:
            node_colors.append(COLORS["primary"])

    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(
            pad=20,
            thickness=20,
            line=dict(color="white", width=0.5),
            label=nodes,
            color=node_colors,
        ),
        link=dict(
            source=sources,
            target=targets,
            value=values,
            color="rgba(79,70,229,0.2)",
        ),
    ))

    fig.update_layout(
        title_text=title,
        title_font_size=16,
        height=CHART_HEIGHT,
        font_size=13,
        paper_bgcolor="white",
        margin=dict(l=10, r=10, t=50, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# BOTTLENECK CHART
# ─────────────────────────────────────────────────────────────

def bottleneck_chart(bottlenecks: list, title: str = "Bottleneck Activities — Avg Wait Time"):
    """
    Horizontal bar chart of activities ranked by average wait time.
    Red bars = above SLA concern threshold.

    Parameters
    ----------
    bottlenecks : list of dicts from BottleneckEngine.activity_wait_times()
        Keys: activity, avg_wait_mins, p90_wait_mins, occurrences
    """
    if not bottlenecks:
        st.info("No bottleneck data available.")
        return

    df = pd.DataFrame(bottlenecks)
    df = df.sort_values("avg_wait_mins", ascending=True)

    fig = go.Figure()

    # Avg wait bar
    fig.add_trace(go.Bar(
        y=df["activity"],
        x=df["avg_wait_mins"],
        name="Avg wait (min)",
        orientation="h",
        marker_color=COLORS["primary"],
        text=df["avg_wait_mins"].apply(lambda x: f"{x:.0f} min"),
        textposition="outside",
    ))

    # P90 wait marker
    if "p90_wait_mins" in df.columns:
        fig.add_trace(go.Scatter(
            y=df["activity"],
            x=df["p90_wait_mins"],
            name="P90 wait (min)",
            mode="markers",
            marker=dict(color=COLORS["danger"], size=10, symbol="diamond"),
        ))

    fig.update_layout(
        title_text=title,
        title_font_size=16,
        height=CHART_HEIGHT,
        xaxis_title="Minutes",
        barmode="overlay",
        legend=dict(orientation="h", y=1.1),
        paper_bgcolor="white",
        plot_bgcolor=COLORS["background"],
        margin=dict(l=10, r=80, t=60, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# VARIANT TABLE
# ─────────────────────────────────────────────────────────────

def variant_table(variants: list, title: str = "Top Process Variants"):
    """
    Styled table of top variants with frequency and cycle time.

    Parameters
    ----------
    variants : list of dicts from VariantAnalyser.get_top_variants()
        Keys: rank, variant_str, count, pct, avg_cycle_mins, is_happy_path
    """
    if not variants:
        st.info("No variant data available.")
        return

    st.subheader(title)

    df = pd.DataFrame(variants)
    df["Path"] = df.apply(
        lambda r: ("✅ " if r["is_happy_path"] else "⚠️ ") + r["variant_str"],
        axis=1
    )
    df["Cases"]        = df["count"].apply(lambda x: f"{x:,}")
    df["Share"]        = df["pct"].apply(lambda x: f"{x:.2f}%")
    df["Avg Cycle"]    = df["avg_cycle_mins"].apply(
        lambda x: f"{x/60:.1f} hrs" if x >= 60 else f"{x:.0f} min"
    )
    df["Steps"]        = df["step_count"]

    display_df = df[["Path", "Cases", "Share", "Avg Cycle", "Steps"]].copy()
    display_df.index = range(1, len(display_df) + 1)

    st.dataframe(display_df, use_container_width=True, height=380)


# ─────────────────────────────────────────────────────────────
# IDEAL VS ACTUAL
# ─────────────────────────────────────────────────────────────

def ideal_vs_actual_card(iva_data: dict):
    """
    Side-by-side comparison of ideal path vs actual deviations.

    Parameters
    ----------
    iva_data : dict from VariantAnalyser.ideal_vs_actual()
    """
    if not iva_data:
        st.info("No ideal vs actual data available.")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.success("**✅ Ideal path (happy path)**")
        st.markdown(f"**Path:** `{iva_data.get('ideal_path_str', 'N/A')}`")
        st.markdown(
            f"**Cases following ideal:** "
            f"{iva_data.get('ideal_count', 0):,} "
            f"({iva_data.get('ideal_pct', 0)}%)"
        )

    with col2:
        st.error("**⚠️ Deviating cases**")
        st.markdown(
            f"**Cases deviating:** "
            f"{iva_data.get('deviation_count', 0):,} "
            f"({iva_data.get('deviation_pct', 0)}%)"
        )
        patterns = iva_data.get("deviation_patterns", [])
        if patterns:
            st.markdown("**Top deviation patterns:**")
            for p in patterns[:3]:
                st.markdown(
                    f"- `{p['variant_str']}` — "
                    f"{p['count']:,} cases ({p['pct']}%)"
                )


# ─────────────────────────────────────────────────────────────
# PRIORITY PIE CHART
# ─────────────────────────────────────────────────────────────

def priority_pie(priority_volume: dict, title: str = "Tickets by Priority"):
    """
    Donut chart of ticket volume by priority level.

    Parameters
    ----------
    priority_volume : dict from KPIEngine — {priority: count}
    """
    if not priority_volume:
        st.info("No priority data available.")
        return

    labels = list(priority_volume.keys())
    values = list(priority_volume.values())
    colors = [PRIORITY_COLORS.get(l, COLORS["neutral"]) for l in labels]

    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.45,
        marker_colors=colors,
        textinfo="label+percent",
        textfont_size=13,
    ))
    fig.update_layout(
        title_text=title,
        title_font_size=16,
        height=CHART_HEIGHT,
        showlegend=True,
        legend=dict(orientation="h", y=-0.1),
        paper_bgcolor="white",
        margin=dict(l=10, r=10, t=50, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# CATEGORY BAR CHART
# ─────────────────────────────────────────────────────────────

def category_bar(category_volume: dict, title: str = "Tickets by Category"):
    """
    Vertical bar chart of ticket volume by category.

    Parameters
    ----------
    category_volume : dict from KPIEngine — {category: count}
    """
    if not category_volume:
        st.info("No category data available.")
        return

    df = pd.DataFrame(
        list(category_volume.items()),
        columns=["Category", "Count"]
    ).sort_values("Count", ascending=False)

    fig = px.bar(
        df, x="Category", y="Count",
        color="Count",
        color_continuous_scale=["#C7D2FE", "#4F46E5"],
        text="Count",
    )
    fig.update_traces(texttemplate="%{text:,}", textposition="outside")
    fig.update_layout(
        title_text=title,
        title_font_size=16,
        height=CHART_HEIGHT,
        xaxis_title="",
        yaxis_title="Tickets",
        coloraxis_showscale=False,
        paper_bgcolor="white",
        plot_bgcolor=COLORS["background"],
        margin=dict(l=10, r=10, t=50, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# DAILY TREND CHART
# ─────────────────────────────────────────────────────────────

def daily_trend_chart(daily_trend: list, title: str = "Daily Event Volume"):
    """
    Line chart showing number of events per day over time.
    Useful for spotting spikes and seasonal patterns.

    Parameters
    ----------
    daily_trend : list of dicts from KPIEngine — [{date, events}]
    """
    if not daily_trend:
        st.info("No trend data available.")
        return

    df = pd.DataFrame(daily_trend)
    df["date"] = pd.to_datetime(df["date"])

    fig = px.line(
        df, x="date", y="events",
        line_shape="spline",
        color_discrete_sequence=[COLORS["primary"]],
    )
    fig.update_traces(
        fill="tozeroy",
        fillcolor="rgba(79,70,229,0.08)",
        line_width=2,
    )
    fig.update_layout(
        title_text=title,
        title_font_size=16,
        height=CHART_HEIGHT,
        xaxis_title="Date",
        yaxis_title="Events",
        paper_bgcolor="white",
        plot_bgcolor=COLORS["background"],
        margin=dict(l=10, r=10, t=50, b=40),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# HOURLY HEATMAP
# ─────────────────────────────────────────────────────────────

def hourly_heatmap(heatmap_data: list, title: str = "Activity Heatmap — Hour vs Weekday"):
    """
    Heatmap of event count by hour-of-day (x) and weekday (y).
    Reveals when the process is most active and when delays occur.

    Parameters
    ----------
    heatmap_data : list of dicts from KPIEngine — [{day, hour, count}]
    """
    if not heatmap_data:
        st.info("No heatmap data available.")
        return

    df = pd.DataFrame(heatmap_data)
    day_names = {0:"Mon", 1:"Tue", 2:"Wed", 3:"Thu", 4:"Fri", 5:"Sat", 6:"Sun"}
    df["day_name"] = df["day"].map(day_names)

    pivot = df.pivot_table(
        index="day_name", columns="hour",
        values="count", fill_value=0
    )
    # Reorder rows Mon→Sun
    day_order = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    pivot = pivot.reindex([d for d in day_order if d in pivot.index])

    fig = px.imshow(
        pivot,
        color_continuous_scale=["#EEF2FF", "#4F46E5"],
        aspect="auto",
        labels=dict(x="Hour of day", y="Weekday", color="Events"),
    )
    fig.update_layout(
        title_text=title,
        title_font_size=16,
        height=320,
        paper_bgcolor="white",
        margin=dict(l=10, r=10, t=50, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# DEVIATIONS TABLE
# ─────────────────────────────────────────────────────────────

def deviations_table(deviations: list, title: str = "Deviating Cases (Worst by Cycle Time)"):
    """
    Table of cases that deviated from the ideal path,
    sorted by cycle time descending.

    Parameters
    ----------
    deviations : list of dicts from VariantAnalyser.get_deviating_cases()
        Keys: case_id, variant_str, cycle_time_mins, priority, category
    """
    if not deviations:
        st.success("No deviating cases found — all cases followed the ideal path.")
        return

    st.subheader(title)

    df = pd.DataFrame(deviations[:50])
    df["Cycle Time"] = df["cycle_time_mins"].apply(
        lambda x: f"{x/60:.1f} hrs" if pd.notna(x) and x >= 60
        else (f"{x:.0f} min" if pd.notna(x) else "N/A")
    )
    df["Priority"] = df["priority"].apply(
        lambda p: f"🔴 {p}" if p == "Critical"
        else (f"🟠 {p}" if p == "High"
        else (f"🔵 {p}" if p == "Medium"
        else f"🟢 {p}"))
    )

    display_df = df.rename(columns={
        "case_id":     "Case ID",
        "variant_str": "Process Path",
        "category":    "Category",
    })[["Case ID", "Process Path", "Priority", "Category", "Cycle Time"]]

    display_df.index = range(1, len(display_df) + 1)
    st.dataframe(display_df, use_container_width=True, height=380)


# ─────────────────────────────────────────────────────────────
# CYCLE TIME DISTRIBUTION
# ─────────────────────────────────────────────────────────────

def cycle_time_distribution(kpi_data: dict, title: str = "Cycle Time Distribution"):
    """
    Bar chart showing P50 / P75 / P90 / P95 cycle time percentiles.
    Helps communicate the spread of process durations.

    Parameters
    ----------
    kpi_data : dict from KPIEngine.compute()
    """
    percentiles = []
    labels      = []
    for key, val in kpi_data.items():
        if key.startswith("p") and key.endswith("_cycle_hrs"):
            pct = key.replace("p", "").replace("_cycle_hrs", "")
            percentiles.append(val)
            labels.append(f"P{pct}")

    if not percentiles:
        return

    fig = go.Figure(go.Bar(
        x=labels,
        y=percentiles,
        marker_color=[COLORS["success"], COLORS["primary"],
                      COLORS["warning"], COLORS["danger"]],
        text=[f"{v:.1f}h" for v in percentiles],
        textposition="outside",
    ))
    fig.update_layout(
        title_text=title,
        title_font_size=16,
        height=320,
        yaxis_title="Hours",
        paper_bgcolor="white",
        plot_bgcolor=COLORS["background"],
        showlegend=False,
        margin=dict(l=10, r=10, t=50, b=30),
    )
    st.plotly_chart(fig, use_container_width=True)