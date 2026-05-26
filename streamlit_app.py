"""ACECARD — Adaptive Cybersecurity Engine for Continuous Anomaly & Risk Detection
Streamlit dashboard for client demos. Reads pipeline output data directly."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = DATA_DIR / "pipeline_results"
GENERATED_DIR = DATA_DIR / "generated"

NAVY = "#0D1B2A"
BLUE = "#1B4F72"
TEAL = "#0E6B8A"
GOLD = "#B7950B"
RED = "#C0392B"
LGRAY = "#F7F8FA"

MITRE_TACTIC_COLORS = {
    "Reconnaissance": "#3498DB",
    "Initial Access": "#E74C3C",
    "Execution": "#E67E22",
    "Persistence": "#9B59B6",
    "Privilege Escalation": "#F39C12",
    "Defense Evasion": "#1ABC9C",
    "Credential Access": "#E74C3C",
    "Discovery": "#2ECC71",
    "Lateral Movement": "#E67E22",
    "Collection": "#9B59B6",
    "Command and Control": "#C0392B",
    "Exfiltration": "#8E44AD",
}

st.set_page_config(
    page_title="ACECARD — Behavioral Intelligence",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(f"""
<style>
    .stApp {{ background-color: {LGRAY}; }}
    .metric-card {{
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        border-left: 4px solid {BLUE};
        margin-bottom: 10px;
    }}
    .metric-card.critical {{ border-left-color: {RED}; }}
    .metric-card.gold {{ border-left-color: {GOLD}; }}
    .metric-card.teal {{ border-left-color: {TEAL}; }}
    .metric-value {{ font-size: 2.2rem; font-weight: 700; color: {NAVY}; margin: 0; }}
    .metric-label {{ font-size: 0.85rem; color: #6C757D; margin: 0; text-transform: uppercase; letter-spacing: 0.5px; }}
    .header-bar {{
        background: linear-gradient(135deg, {NAVY} 0%, {BLUE} 100%);
        padding: 24px 32px;
        border-radius: 12px;
        margin-bottom: 24px;
        color: white;
    }}
    .header-bar h1 {{ color: white; margin: 0; font-size: 1.8rem; }}
    .header-bar p {{ color: #A0C8E0; margin: 4px 0 0 0; font-size: 0.95rem; }}
    .severity-critical {{ color: {RED}; font-weight: 700; }}
    .severity-high {{ color: #E67E22; font-weight: 700; }}
    .severity-medium {{ color: {GOLD}; font-weight: 600; }}
    .severity-low {{ color: {TEAL}; }}
    .severity-info {{ color: #6C757D; }}
    div[data-testid="stSidebar"] {{ background-color: {NAVY}; }}
    div[data-testid="stSidebar"] .stMarkdown {{ color: white; }}
    div[data-testid="stSidebar"] label {{ color: white !important; }}
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_alerts():
    path = RESULTS_DIR / "alerts.json"
    if not path.exists():
        return pd.DataFrame()
    with open(path) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    if "detected_at" in df.columns:
        df["detected_at"] = pd.to_datetime(df["detected_at"])
    return df


@st.cache_data
def load_kill_chains():
    path = RESULTS_DIR / "kill_chains.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


@st.cache_data
def load_drift_series():
    path = RESULTS_DIR / "drift_series.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "cutoff_date" in df.columns:
        df["cutoff_date"] = pd.to_datetime(df["cutoff_date"])
    return df


@st.cache_data
def load_log_stats():
    stats = {}
    log_types = ["auth", "network", "dns", "endpoint", "file_access", "app", "privilege"]
    for lt in log_types:
        log_dir = GENERATED_DIR / lt
        if log_dir.exists():
            csvs = list(log_dir.glob("*.csv"))
            total_rows = 0
            for csv_path in csvs[:5]:
                try:
                    total_rows += sum(1 for _ in open(csv_path)) - 1
                except Exception:
                    pass
            stats[lt] = {
                "files": len(csvs),
                "sample_rows": total_rows,
                "est_total": total_rows * len(csvs) // max(min(5, len(csvs)), 1) if csvs else 0,
            }
    return stats


alerts_df = load_alerts()
kill_chains = load_kill_chains()
drift_df = load_drift_series()
log_stats = load_log_stats()

# ── SIDEBAR ──
with st.sidebar:
    st.markdown(f"""
    <div style="text-align:center; padding: 16px 0;">
        <h2 style="color:{GOLD}; margin:0; font-family:Georgia;">ACECARD</h2>
        <p style="color:#A0C8E0; font-size:0.75rem; margin:4px 0 0 0;">
        Adaptive Cybersecurity Engine for<br>Continuous Anomaly & Risk Detection</p>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    page = st.radio(
        "Navigation",
        ["Dashboard", "Alerts", "Kill Chains", "Behavioral Drift", "Telemetry Explorer"],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown(f"""
    <div style="padding:8px; background:rgba(255,255,255,0.05); border-radius:8px; margin-top:8px;">
        <p style="color:{GOLD}; font-size:0.75rem; margin:0;">DETECTION ENGINE</p>
        <p style="color:#A0C8E0; font-size:0.7rem; margin:4px 0 0 0;">
        CUSUM Change-Point Detection<br>
        Digital Twin Behavioral Modeling<br>
        MITRE ATT&CK Mapping<br>
        Kill Chain Reconstruction</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="text-align:center; padding:16px 0 8px 0;">
        <p style="color:#6C757D; font-size:0.65rem;">
        22nd Century Technologies<br>PROPRIETARY</p>
    </div>
    """, unsafe_allow_html=True)


# ── PAGE: DASHBOARD ──
if page == "Dashboard":
    st.markdown(f"""
    <div class="header-bar">
        <h1>🛡️ ACECARD — Behavioral Intelligence Dashboard</h1>
        <p>Continuous anomaly detection across DODIN telemetry. Real-time behavioral drift analysis with MITRE ATT&CK correlation.</p>
    </div>
    """, unsafe_allow_html=True)

    n_alerts = len(alerts_df) if not alerts_df.empty else 0
    n_critical = len(alerts_df[alerts_df["severity"] == "critical"]) if not alerts_df.empty else 0
    n_chains = len(kill_chains)
    n_entities = alerts_df["entity_id"].nunique() if not alerts_df.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""<div class="metric-card critical">
            <p class="metric-label">Active Alerts</p>
            <p class="metric-value">{n_alerts}</p>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="metric-card critical">
            <p class="metric-label">Critical Alerts</p>
            <p class="metric-value">{n_critical}</p>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class="metric-card gold">
            <p class="metric-label">Kill Chains</p>
            <p class="metric-value">{n_chains}</p>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""<div class="metric-card teal">
            <p class="metric-label">Entities Affected</p>
            <p class="metric-value">{n_entities}</p>
        </div>""", unsafe_allow_html=True)

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("Severity Distribution")
        if not alerts_df.empty:
            sev_order = ["critical", "high", "medium", "low", "info"]
            sev_colors = {"critical": RED, "high": "#E67E22", "medium": GOLD, "low": TEAL, "info": "#6C757D"}
            sev_counts = alerts_df["severity"].value_counts().reindex(sev_order).dropna()
            fig = px.bar(
                x=sev_counts.index,
                y=sev_counts.values,
                color=sev_counts.index,
                color_discrete_map=sev_colors,
                labels={"x": "Severity", "y": "Count"},
            )
            fig.update_layout(
                showlegend=False,
                plot_bgcolor="white",
                height=320,
                margin=dict(l=40, r=20, t=20, b=40),
                font=dict(family="Segoe UI"),
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No alert data available. Run the pipeline first: `python run_pipeline.py`")

    with col_right:
        st.subheader("MITRE Tactics Observed")
        if not alerts_df.empty:
            all_techniques = []
            for _, row in alerts_df.iterrows():
                if isinstance(row.get("mitre_techniques"), list):
                    all_techniques.extend(row["mitre_techniques"])
            if all_techniques:
                tech_counts = pd.Series(all_techniques).value_counts().head(10)
                fig = px.bar(
                    x=tech_counts.values,
                    y=tech_counts.index,
                    orientation="h",
                    labels={"x": "Occurrences", "y": "Technique"},
                    color_discrete_sequence=[BLUE],
                )
                fig.update_layout(
                    showlegend=False,
                    plot_bgcolor="white",
                    height=320,
                    margin=dict(l=60, r=20, t=20, b=40),
                    yaxis=dict(autorange="reversed"),
                    font=dict(family="Segoe UI"),
                )
                st.plotly_chart(fig, width="stretch")

    st.subheader("Behavioral Drift Heatmap")
    if not drift_df.empty:
        pivot = drift_df.pivot_table(
            index="entity_id", columns="cutoff_date", values="drift_from_first", aggfunc="mean"
        )
        pivot = pivot.loc[pivot.max(axis=1).sort_values(ascending=False).head(20).index]
        fig = px.imshow(
            pivot.values,
            x=[str(c.date()) if hasattr(c, "date") else str(c) for c in pivot.columns],
            y=pivot.index.tolist(),
            color_continuous_scale=[[0, "#EBF5FB"], [0.3, "#1B4F72"], [0.6, "#E67E22"], [1.0, RED]],
            labels={"color": "Drift Magnitude"},
            aspect="auto",
        )
        fig.update_layout(
            height=400,
            margin=dict(l=80, r=20, t=20, b=40),
            font=dict(family="Segoe UI"),
        )
        st.plotly_chart(fig, width="stretch")

    st.subheader("Telemetry Ingestion")
    if log_stats:
        tel_df = pd.DataFrame([
            {"Source": k.replace("_", " ").title(), "Files": v["files"], "Est. Events": f"{v['est_total']:,}"}
            for k, v in log_stats.items()
        ])
        st.dataframe(tel_df, width="stretch", hide_index=True)


# ── PAGE: ALERTS ──
elif page == "Alerts":
    st.markdown(f"""
    <div class="header-bar">
        <h1>⚠️ Alert Console</h1>
        <p>All behavioral anomaly alerts with drift analysis and MITRE ATT&CK correlation.</p>
    </div>
    """, unsafe_allow_html=True)

    if alerts_df.empty:
        st.warning("No alerts found. Run the pipeline: `python run_pipeline.py`")
    else:
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            sev_filter = st.multiselect(
                "Severity",
                ["critical", "high", "medium", "low", "info"],
                default=["critical", "high"],
            )
        with fc2:
            method_filter = st.multiselect(
                "Detection Method",
                alerts_df["detection_method"].unique().tolist(),
                default=alerts_df["detection_method"].unique().tolist(),
            )
        with fc3:
            entity_filter = st.text_input("Entity ID (contains)", "")

        filtered = alerts_df.copy()
        if sev_filter:
            filtered = filtered[filtered["severity"].isin(sev_filter)]
        if method_filter:
            filtered = filtered[filtered["detection_method"].isin(method_filter)]
        if entity_filter:
            filtered = filtered[filtered["entity_id"].str.contains(entity_filter, case=False)]

        st.markdown(f"**{len(filtered)}** alerts matching filters")

        for _, alert in filtered.iterrows():
            sev = alert["severity"]
            sev_class = f"severity-{sev}"
            with st.expander(
                f"{'🔴' if sev == 'critical' else '🟠' if sev == 'high' else '🟡' if sev == 'medium' else '🔵'} "
                f"[{sev.upper()}] {alert['title']}  —  {alert['entity_id']}"
            ):
                ac1, ac2, ac3 = st.columns(3)
                ac1.metric("Drift Magnitude", f"{alert['drift_magnitude']:.4f}")
                ac2.metric("Confidence", f"{alert['confidence']:.1%}")
                ac3.metric("Detection", alert["detection_method"])

                st.markdown(f"**Description:** {alert['description']}")

                if isinstance(alert.get("concept_alignments"), list) and alert["concept_alignments"]:
                    st.markdown("**Concept Alignments:**")
                    for ca in alert["concept_alignments"]:
                        st.markdown(
                            f"- `{ca['concept']}` — similarity: {ca['similarity']:.3f}, "
                            f"severity: {ca.get('severity', 'n/a')}, "
                            f"techniques: {', '.join(ca.get('mitre_techniques', []))}"
                        )

                if isinstance(alert.get("mitre_techniques"), list) and alert["mitre_techniques"]:
                    st.markdown(f"**MITRE Techniques:** {', '.join(alert['mitre_techniques'])}")

                if alert.get("kill_chain_id"):
                    st.markdown(f"**Kill Chain:** `{alert['kill_chain_id']}`")


# ── PAGE: KILL CHAINS ──
elif page == "Kill Chains":
    st.markdown(f"""
    <div class="header-bar">
        <h1>🔗 Kill Chain Reconstruction</h1>
        <p>Correlated attack sequences across entities. Alerts linked by entity overlap and temporal proximity.</p>
    </div>
    """, unsafe_allow_html=True)

    if not kill_chains:
        st.warning("No kill chains found. Run the pipeline: `python run_pipeline.py`")
    else:
        for i, kc in enumerate(kill_chains):
            sev = kc.get("severity", "medium")
            icon = "🔴" if sev == "critical" else "🟠" if sev == "high" else "🟡"
            n_events = len(kc.get("events", []))
            entities = kc.get("entities_involved", [])
            tactics = kc.get("tactics_observed", [])
            duration_s = kc.get("duration_seconds", 0)
            duration_str = f"{duration_s / 3600:.1f} hours" if duration_s > 3600 else f"{duration_s / 60:.0f} min"

            with st.expander(
                f"{icon} Chain {i + 1}: {' → '.join(tactics)}  |  "
                f"{n_events} events  |  {len(entities)} entities  |  {duration_str}"
            ):
                kc1, kc2, kc3, kc4 = st.columns(4)
                kc1.metric("Severity", sev.upper())
                kc2.metric("Events", n_events)
                kc3.metric("Entities", len(entities))
                kc4.metric("Duration", duration_str)

                st.markdown(f"**Entities:** {', '.join(f'`{e}`' for e in entities)}")
                st.markdown(f"**Tactics Progression:** {' → '.join(tactics)}")

                if kc.get("events"):
                    fig = go.Figure()
                    for j, evt in enumerate(kc["events"]):
                        tactic = evt.get("tactic", "Unknown")
                        color = MITRE_TACTIC_COLORS.get(tactic, "#6C757D")
                        fig.add_trace(go.Scatter(
                            x=[j],
                            y=[evt.get("confidence", 0.5)],
                            mode="markers+text",
                            marker=dict(size=20, color=color),
                            text=[tactic[:12]],
                            textposition="top center",
                            name=f"{evt['entity_id']}: {tactic}",
                            hovertext=f"{evt['entity_id']}<br>{evt['description'][:80]}",
                        ))
                    fig.update_layout(
                        height=250,
                        plot_bgcolor="white",
                        showlegend=False,
                        xaxis=dict(title="Event Sequence", showgrid=False),
                        yaxis=dict(title="Confidence", range=[0, 1]),
                        margin=dict(l=40, r=20, t=40, b=40),
                        font=dict(family="Segoe UI"),
                    )
                    st.plotly_chart(fig, width="stretch")

                    st.markdown("**Event Timeline:**")
                    for evt in kc["events"]:
                        st.markdown(
                            f"- **{evt['tactic']}** — `{evt['entity_id']}` — "
                            f"confidence: {evt['confidence']:.2f} — "
                            f"{evt['description'][:100]}"
                        )


# ── PAGE: BEHAVIORAL DRIFT ──
elif page == "Behavioral Drift":
    st.markdown(f"""
    <div class="header-bar">
        <h1>📈 Behavioral Drift Analysis</h1>
        <p>CUSUM change-point detection tracking slow behavioral drift across entity populations.</p>
    </div>
    """, unsafe_allow_html=True)

    if drift_df.empty:
        st.warning("No drift data found. Run the pipeline: `python run_pipeline.py`")
    else:
        entity_types = drift_df["entity_type"].unique().tolist()
        selected_type = st.selectbox("Entity Type", entity_types)
        type_df = drift_df[drift_df["entity_type"] == selected_type]

        top_drifters = (
            type_df.groupby("entity_id")["drift_from_first"]
            .max()
            .sort_values(ascending=False)
            .head(15)
        )

        st.subheader("Top Drifting Entities")
        fig = px.bar(
            x=top_drifters.index,
            y=top_drifters.values,
            color=top_drifters.values,
            color_continuous_scale=[[0, TEAL], [0.5, GOLD], [1.0, RED]],
            labels={"x": "Entity", "y": "Max Drift"},
        )
        fig.add_hline(y=0.15, line_dash="dash", line_color=RED, annotation_text="Alert Threshold")
        fig.update_layout(
            showlegend=False,
            plot_bgcolor="white",
            height=350,
            margin=dict(l=40, r=20, t=20, b=80),
            font=dict(family="Segoe UI"),
        )
        st.plotly_chart(fig, width="stretch")

        st.subheader("Drift Trajectories")
        selected_entities = st.multiselect(
            "Select entities to compare",
            type_df["entity_id"].unique().tolist(),
            default=top_drifters.head(5).index.tolist(),
        )

        if selected_entities:
            traj_df = type_df[type_df["entity_id"].isin(selected_entities)]
            fig = px.line(
                traj_df,
                x="cutoff_date",
                y="drift_from_first",
                color="entity_id",
                labels={"cutoff_date": "Date", "drift_from_first": "Drift from Baseline"},
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.add_hline(y=0.15, line_dash="dash", line_color=RED, annotation_text="Alert Threshold")
            fig.update_layout(
                plot_bgcolor="white",
                height=400,
                margin=dict(l=40, r=20, t=20, b=40),
                font=dict(family="Segoe UI"),
                legend=dict(orientation="h", yanchor="bottom", y=-0.3),
            )
            st.plotly_chart(fig, width="stretch")

        st.subheader("Population Drift Distribution")
        latest_date = type_df["cutoff_date"].max()
        latest_drift = type_df[type_df["cutoff_date"] == latest_date]
        fig = px.histogram(
            latest_drift,
            x="drift_from_first",
            nbins=30,
            color_discrete_sequence=[BLUE],
            labels={"drift_from_first": "Drift Magnitude"},
        )
        fig.add_vline(x=0.15, line_dash="dash", line_color=RED, annotation_text="Alert Threshold")
        fig.update_layout(
            plot_bgcolor="white",
            height=300,
            margin=dict(l=40, r=20, t=20, b=40),
            font=dict(family="Segoe UI"),
        )
        st.plotly_chart(fig, width="stretch")


# ── PAGE: TELEMETRY EXPLORER ──
elif page == "Telemetry Explorer":
    st.markdown(f"""
    <div class="header-bar">
        <h1>🔍 Telemetry Explorer</h1>
        <p>Browse raw DODIN telemetry: authentication, network, DNS, endpoint, application, privilege, and file access logs.</p>
    </div>
    """, unsafe_allow_html=True)

    log_types = [d.name for d in GENERATED_DIR.iterdir() if d.is_dir()] if GENERATED_DIR.exists() else []

    if not log_types:
        st.warning("No generated data found. Run: `python -m simulator.generate --days 7`")
    else:
        tc1, tc2 = st.columns([1, 2])
        with tc1:
            selected_log = st.selectbox("Log Type", sorted(log_types))
        with tc2:
            log_dir = GENERATED_DIR / selected_log
            csv_files = sorted(log_dir.glob("*.csv"))
            date_options = [f.stem for f in csv_files]
            if date_options:
                selected_date = st.selectbox("Date", date_options, index=len(date_options) - 1)
            else:
                selected_date = None

        if selected_date:
            csv_path = log_dir / f"{selected_date}.csv"
            df = pd.read_csv(csv_path)
            st.markdown(f"**{len(df):,}** events  |  **{len(df.columns)}** fields  |  `{selected_log}/{selected_date}.csv`")

            search = st.text_input("Search (filters all columns)", "")
            if search:
                mask = df.astype(str).apply(lambda col: col.str.contains(search, case=False)).any(axis=1)
                df = df[mask]
                st.markdown(f"**{len(df):,}** matching events")

            st.dataframe(df.head(500), width="stretch", height=500)

            with st.expander("Column Statistics"):
                for col in df.columns:
                    if df[col].dtype in ["int64", "float64"]:
                        st.markdown(f"**{col}:** min={df[col].min()}, max={df[col].max()}, mean={df[col].mean():.2f}")
                    else:
                        n_unique = df[col].nunique()
                        st.markdown(f"**{col}:** {n_unique} unique values — top: {df[col].value_counts().head(3).to_dict()}")
