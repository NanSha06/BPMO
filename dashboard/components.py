"""
dashboard/components.py
========================
Business Process Mining & Optimization Platform — Phase 1
Step 5a: Reusable Dashboard Components — v2 (vivid palette)
"""

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

# ── Vivid colour palette ──────────────────────────────────────
PRIMARY     = "#6366F1"   # indigo
SUCCESS     = "#10B981"   # emerald
WARNING     = "#F59E0B"   # amber
DANGER      = "#EF4444"   # red
PURPLE      = "#8B5CF6"   # violet
CYAN        = "#06B6D4"   # cyan
ORANGE      = "#F97316"   # orange
LIME        = "#84CC16"   # lime

# Ordered sequence for multi-series charts
PALETTE = [PRIMARY, SUCCESS, WARNING, DANGER, PURPLE, CYAN, ORANGE, LIME]

PRIORITY_COLORS = {
    "Critical": DANGER,
    "High":     WARNING,
    "Medium":   PRIMARY,
    "Low":      SUCCESS,
}

BG        = "#FFFFFF"
PLOT_BG   = "#F8FAFF"
GRID_CLR  = "#E0E7FF"
CHART_H   = 420
FONT_CLR  = "#1E1B4B"

# ── Shared layout defaults ────────────────────────────────────
def _base_layout(title: str, height: int = CHART_H) -> dict:
    return dict(
        title_text       = title,
        title_font       = dict(size=15, color=FONT_CLR, family="sans-serif"),
        title_font_color = FONT_CLR,
        height           = height,
        paper_bgcolor    = BG,
        plot_bgcolor     = PLOT_BG,
        font             = dict(color=FONT_CLR, family="sans-serif"),
        margin           = dict(l=16, r=16, t=54, b=40),
        hoverlabel       = dict(bgcolor="white", font_size=13,
                                bordercolor=PRIMARY),
    )


# ─────────────────────────────────────────────────────────────
# KPI CARDS
# ─────────────────────────────────────────────────────────────

def kpi_cards(kpi_data: dict):
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("🎫 Total Tickets",
                  f"{kpi_data.get('total_cases', 0):,}")
    with c2:
        st.metric("⏱ Avg Cycle Time",
                  f"{kpi_data.get('avg_cycle_hrs', 0):.1f} hrs")
    with c3:
        breach = kpi_data.get("sla_breach_rate", 0)
        st.metric("🚨 SLA Breach Rate", f"{breach}%",
                  delta=f"{breach}% breached", delta_color="inverse")
    with c4:
        st.metric("📈 Escalation Rate",
                  f"{kpi_data.get('escalation_rate', 0)}%",
                  delta_color="inverse")
    with c5:
        st.metric("✅ Resolution Rate",
                  f"{kpi_data.get('resolution_rate', 0)}%",
                  delta_color="normal")


# ─────────────────────────────────────────────────────────────
# PROCESS FLOW — SANKEY
# ─────────────────────────────────────────────────────────────

def process_flow_chart(dfg_data: dict, title: str = "Actual Process Flow"):
    if not dfg_data or not dfg_data.get("edges"):
        st.info("No process flow data available.")
        return

    nodes      = dfg_data["nodes"]
    edges      = dfg_data["edges"]
    idx        = {n: i for i, n in enumerate(nodes)}
    start_acts = dfg_data.get("start_activities", [])
    end_acts   = dfg_data.get("end_activities", [])

    # Vivid node colours
    node_colors = []
    for n in nodes:
        if n in start_acts:
            node_colors.append(SUCCESS)
        elif n in end_acts:
            node_colors.append(DANGER)
        else:
            node_colors.append(PRIMARY)

    valid   = [(e["from"], e["to"], e["count"])
               for e in edges if e["from"] in idx and e["to"] in idx]
    sources = [idx[f] for f, _, _ in valid]
    targets = [idx[t] for _, t, _ in valid]
    values  = [c       for _, _, c in valid]

    # Link colour = source node colour at 40% opacity
    link_colors = []
    for src_idx in sources:
        base = node_colors[src_idx].lstrip("#")
        r, g, b = int(base[0:2],16), int(base[2:4],16), int(base[4:6],16)
        link_colors.append(f"rgba({r},{g},{b},0.38)")

    fig = go.Figure(go.Sankey(
        arrangement = "snap",
        node = dict(
            pad       = 22,
            thickness = 24,
            line      = dict(color="white", width=0.8),
            label     = nodes,
            color     = node_colors,
        ),
        link = dict(
            source = sources,
            target = targets,
            value  = values,
            color  = link_colors,
        ),
    ))
    layout = _base_layout(title)
    layout.update(font_size=13)
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# BOTTLENECK CHART
# ─────────────────────────────────────────────────────────────

def bottleneck_chart(bottlenecks: list,
                     title: str = "Bottleneck Activities — Avg Wait Time"):
    if not bottlenecks:
        st.info("No bottleneck data available.")
        return

    df = pd.DataFrame(bottlenecks).sort_values("avg_wait_mins", ascending=True)

    # Colour bars: top 3 = danger/warning, rest = primary
    n = len(df)
    bar_colors = ([DANGER] if n >= 1 else []) + \
                 ([WARNING] if n >= 2 else []) + \
                 ([ORANGE] if n >= 3 else []) + \
                 [PRIMARY] * max(0, n - 3)
    bar_colors = bar_colors[:n]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        y           = df["activity"],
        x           = df["avg_wait_mins"],
        name        = "Avg wait",
        orientation = "h",
        marker      = dict(color=bar_colors, line=dict(width=0)),
        text        = df["avg_wait_mins"].apply(lambda x: f"  {x:,.0f} min"),
        textposition= "outside",
        textfont    = dict(size=12, color=FONT_CLR),
    ))

    if "p90_wait_mins" in df.columns:
        fig.add_trace(go.Scatter(
            y      = df["activity"],
            x      = df["p90_wait_mins"],
            name   = "P90",
            mode   = "markers",
            marker = dict(color=PURPLE, size=11, symbol="diamond",
                          line=dict(color="white", width=1)),
        ))

    layout = _base_layout(title)
    layout.update(
        xaxis       = dict(title="Minutes", gridcolor=GRID_CLR,
                           showgrid=True, zeroline=False),
        yaxis       = dict(gridcolor=GRID_CLR, showgrid=False),
        legend      = dict(orientation="h", y=1.08, x=0),
        bargap      = 0.35,
    )
    # Give room for outside text labels
    max_val = df["avg_wait_mins"].max() if not df.empty else 100
    layout["xaxis"]["range"] = [0, max_val * 1.25]
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# VARIANT TABLE
# ─────────────────────────────────────────────────────────────

def variant_table(variants: list, title: str = "Top Process Variants"):
    if not variants:
        st.info("No variant data available.")
        return

    st.subheader(title)
    df = pd.DataFrame(variants)
    df["Path"] = df.apply(
        lambda r: ("✅ " if r["is_happy_path"] else "⚠️ ") + r["variant_str"],
        axis=1
    )
    df["Cases"]     = df["count"].apply(lambda x: f"{x:,}")
    df["Share"]     = df["pct"].apply(lambda x: f"{x:.2f}%")
    df["Avg Cycle"] = df["avg_cycle_mins"].apply(
        lambda x: f"{x/60:.1f} hrs" if x >= 60 else f"{x:.0f} min"
    )
    df["Steps"] = df["step_count"]
    out = df[["Path","Cases","Share","Avg Cycle","Steps"]].copy()
    out.index = range(1, len(out)+1)
    st.dataframe(out, use_container_width=True, height=360)


# ─────────────────────────────────────────────────────────────
# IDEAL VS ACTUAL
# ─────────────────────────────────────────────────────────────

def ideal_vs_actual_card(iva_data: dict):
    if not iva_data:
        st.info("No ideal vs actual data available.")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.success("**✅ Ideal path (happy path)**")
        st.markdown(f"**Path:** `{iva_data.get('ideal_path_str','N/A')}`")
        st.markdown(
            f"**Following ideal:** "
            f"{iva_data.get('ideal_count',0):,} "
            f"({iva_data.get('ideal_pct',0)}%)"
        )
    with col2:
        st.error("**⚠️ Deviating cases**")
        st.markdown(
            f"**Deviations:** "
            f"{iva_data.get('deviation_count',0):,} "
            f"({iva_data.get('deviation_pct',0)}%)"
        )
        for p in iva_data.get("deviation_patterns",[])[:3]:
            st.markdown(
                f"- `{p['variant_str']}` — {p['count']:,} ({p['pct']}%)"
            )


# ─────────────────────────────────────────────────────────────
# PRIORITY PIE
# ─────────────────────────────────────────────────────────────

def priority_pie(priority_volume: dict, title: str = "Tickets by Priority"):
    if not priority_volume:
        st.info("No priority data available.")
        return

    labels = list(priority_volume.keys())
    values = list(priority_volume.values())
    colors = [PRIORITY_COLORS.get(l, PRIMARY) for l in labels]

    fig = go.Figure(go.Pie(
        labels          = labels,
        values          = values,
        hole            = 0.48,
        marker          = dict(colors=colors,
                               line=dict(color="white", width=2.5)),
        textinfo        = "label+percent",
        textfont        = dict(size=13, color=FONT_CLR),
        pull            = [0.04 if l == "Critical" else 0 for l in labels],
        hovertemplate   = "<b>%{label}</b><br>%{value:,} tickets<br>%{percent}<extra></extra>",
    ))
    layout = _base_layout(title)
    layout.update(
        showlegend = True,
        legend     = dict(orientation="h", y=-0.12, font_size=12),
    )
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# CATEGORY BAR — distinct colour per bar
# ─────────────────────────────────────────────────────────────

def category_bar(category_volume: dict, title: str = "Tickets by Category"):
    if not category_volume:
        st.info("No category data available.")
        return

    df = pd.DataFrame(
        list(category_volume.items()), columns=["Category","Count"]
    ).sort_values("Count", ascending=False)

    # One vivid colour per bar
    bar_colors = [PALETTE[i % len(PALETTE)] for i in range(len(df))]

    fig = go.Figure(go.Bar(
        x              = df["Category"],
        y              = df["Count"],
        marker         = dict(color=bar_colors,
                              line=dict(color="white", width=1.5)),
        text           = df["Count"].apply(lambda x: f"{x:,}"),
        textposition   = "outside",
        textfont       = dict(size=12, color=FONT_CLR),
        hovertemplate  = "<b>%{x}</b><br>%{y:,} tickets<extra></extra>",
    ))
    layout = _base_layout(title)
    layout.update(
        xaxis = dict(title="", gridcolor=GRID_CLR, showgrid=False),
        yaxis = dict(title="Tickets", gridcolor=GRID_CLR, showgrid=True,
                     zeroline=False),
    )
    max_y = df["Count"].max() if not df.empty else 100
    layout["yaxis"]["range"] = [0, max_y * 1.2]
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# DAILY TREND CHART
# ─────────────────────────────────────────────────────────────

def daily_trend_chart(daily_trend: list, title: str = "Daily Event Volume"):
    if not daily_trend:
        st.info("No trend data available.")
        return

    df = pd.DataFrame(daily_trend)
    df["date"] = pd.to_datetime(df["date"])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x           = df["date"],
        y           = df["events"],
        mode        = "lines",
        line        = dict(color=CYAN, width=2.5, shape="spline"),
        fill        = "tozeroy",
        fillcolor   = "rgba(6,182,212,0.12)",
        hovertemplate = "%{x|%b %d}<br><b>%{y:,}</b> events<extra></extra>",
    ))
    layout = _base_layout(title)
    layout.update(
        xaxis = dict(title="Date", gridcolor=GRID_CLR, showgrid=True,
                     zeroline=False),
        yaxis = dict(title="Events", gridcolor=GRID_CLR, showgrid=True,
                     zeroline=False),
        hovermode = "x unified",
    )
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# HOURLY HEATMAP — fixed to show all 24 hours
# ─────────────────────────────────────────────────────────────

def hourly_heatmap(heatmap_data: list,
                   title: str = "Activity Heatmap — Hour vs Weekday"):
    if not heatmap_data:
        st.info("No heatmap data available.")
        return

    df = pd.DataFrame(heatmap_data)

    # Ensure hour is integer (not float) so all 24 columns appear
    df["hour"] = df["hour"].astype(int)
    df["day"]  = df["day"].astype(int)

    day_map   = {0:"Mon",1:"Tue",2:"Wed",3:"Thu",4:"Fri",5:"Sat",6:"Sun"}
    day_order = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    df["day_name"] = df["day"].map(day_map)

    pivot = df.pivot_table(
        index="day_name", columns="hour",
        values="count", aggfunc="sum", fill_value=0
    )
    # Add any missing hours as 0 columns
    for h in range(24):
        if h not in pivot.columns:
            pivot[h] = 0
    pivot = pivot[sorted(pivot.columns)]
    pivot = pivot.reindex([d for d in day_order if d in pivot.index])

    fig = go.Figure(go.Heatmap(
        z              = pivot.values,
        x              = [f"{h:02d}:00" for h in pivot.columns],
        y              = list(pivot.index),
        colorscale     = [
            [0.0,  "#EEF2FF"],
            [0.25, "#A5B4FC"],
            [0.5,  "#6366F1"],
            [0.75, "#4338CA"],
            [1.0,  "#1E1B4B"],
        ],
        hoverongaps    = False,
        hovertemplate  = "<b>%{y} %{x}</b><br>%{z:,} events<extra></extra>",
        showscale      = True,
        colorbar       = dict(
            title      = "Events",
            titleside  = "right",
            tickfont   = dict(size=11, color=FONT_CLR),
        ),
    ))
    layout = _base_layout(title, height=310)
    layout.update(
        xaxis = dict(title="Hour of day", tickangle=-45,
                     tickfont=dict(size=11)),
        yaxis = dict(title="Weekday", tickfont=dict(size=12)),
        margin= dict(l=60, r=80, t=54, b=60),
    )
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# CYCLE TIME DISTRIBUTION
# ─────────────────────────────────────────────────────────────

def cycle_time_distribution(kpi_data: dict,
                             title: str = "Cycle Time Distribution"):
    percentiles, labels, colors_list = [], [], []
    color_map = {"50": SUCCESS, "75": PRIMARY, "90": WARNING, "95": DANGER}

    for key, val in kpi_data.items():
        if key.startswith("p") and key.endswith("_cycle_hrs"):
            pct = key.replace("p","").replace("_cycle_hrs","")
            percentiles.append(val)
            labels.append(f"P{pct}")
            colors_list.append(color_map.get(pct, PRIMARY))

    if not percentiles:
        return

    fig = go.Figure(go.Bar(
        x              = labels,
        y              = percentiles,
        marker         = dict(color=colors_list,
                              line=dict(color="white", width=1.5)),
        text           = [f"{v:.1f}h" for v in percentiles],
        textposition   = "outside",
        textfont       = dict(size=13, color=FONT_CLR),
        hovertemplate  = "<b>%{x}</b><br>%{y:.1f} hours<extra></extra>",
    ))
    layout = _base_layout(title, height=310)
    layout.update(
        xaxis     = dict(title="Percentile", gridcolor=GRID_CLR, showgrid=False),
        yaxis     = dict(title="Hours", gridcolor=GRID_CLR, showgrid=True,
                         zeroline=False),
        showlegend= False,
    )
    max_v = max(percentiles) if percentiles else 1
    layout["yaxis"]["range"] = [0, max_v * 1.22]
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# DEVIATIONS TABLE
# ─────────────────────────────────────────────────────────────

def deviations_table(deviations: list,
                     title: str = "Deviating Cases — Worst by Cycle Time"):
    if not deviations:
        st.success("All cases followed the ideal path.")
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
        else (f"🔵 {p}" if p == "Medium" else f"🟢 {p}"))
    )
    out = df.rename(columns={
        "case_id":"Case ID","variant_str":"Process Path","category":"Category"
    })[["Case ID","Process Path","Priority","Category","Cycle Time"]]
    out.index = range(1, len(out)+1)
    st.dataframe(out, use_container_width=True, height=360)