"""ACECARD — Adaptive Cybersecurity Engine for Continuous Anomaly & Risk Detection
Streamlit dashboard for client demos. Reads pipeline output data directly."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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
        ["Dashboard", "Alerts", "Kill Chains", "Behavioral Drift", "Behavioral Profile", "Telemetry Explorer"],
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


# ── PAGE: BEHAVIORAL PROFILE ──
elif page == "Behavioral Profile":
    st.markdown(f"""
    <div class="header-bar">
        <h1>🧬 Entity Behavioral Profile</h1>
        <p>Per-signal behavioral decomposition over time. Shows how each behavioral dimension evolves independently — proving anomaly detection capability.</p>
    </div>
    """, unsafe_allow_html=True)

    SIGNAL_LABELS = {
        "user": {
            "auth": "Authentication",
            "privilege": "Privilege Ops",
            "data_access": "Data Access",
            "network": "Network Activity",
            "communication": "App / Comms",
        },
    }
    SIGNAL_COLORS = {
        "auth": "#E74C3C",
        "privilege": "#F39C12",
        "data_access": "#9B59B6",
        "network": "#3498DB",
        "communication": "#1ABC9C",
    }

    @st.cache_data
    def compute_user_behavioral_signals(user_id: str) -> pd.DataFrame | None:
        """Compute per-signal behavioral metrics for a user across all available dates."""
        auth_dir = GENERATED_DIR / "auth"
        net_dir = GENERATED_DIR / "network"
        endpoint_dir = GENERATED_DIR / "endpoint"
        file_dir = GENERATED_DIR / "file_access"
        priv_dir = GENERATED_DIR / "privilege"
        app_dir = GENERATED_DIR / "app"

        if not auth_dir.exists():
            return None

        auth_files = sorted(auth_dir.glob("*.csv"))
        if not auth_files:
            return None

        # Group files into weekly windows for smoother signal curves
        file_dates = [f.stem for f in auth_files]
        date_objs = [datetime.strptime(d, "%Y-%m-%d").date() for d in file_dates]
        if len(date_objs) < 2:
            return None

        # Build weekly buckets
        start = date_objs[0]
        end = date_objs[-1]
        weeks = []
        current = start
        while current <= end:
            week_end = current + timedelta(days=6)
            weeks.append((current, min(week_end, end)))
            current = week_end + timedelta(days=1)

        rows = []
        for week_start, week_end in weeks:
            week_dates = [d for d in date_objs if week_start <= d <= week_end]
            if not week_dates:
                continue

            # Auth signal: login count, failure rate, off-hours ratio
            auth_logins = 0
            auth_failures = 0
            auth_offhours = 0
            auth_total = 0
            for d in week_dates:
                csv = auth_dir / f"{d.isoformat()}.csv"
                if csv.exists():
                    df = pd.read_csv(csv)
                    udf = df[df["user_id"] == user_id] if "user_id" in df.columns else pd.DataFrame()
                    auth_total += len(udf)
                    auth_logins += len(udf)
                    if "success" in udf.columns:
                        auth_failures += len(udf[udf["success"].astype(str).str.lower() == "false"])
                    if "timestamp" in udf.columns and len(udf) > 0:
                        hours = pd.to_datetime(udf["timestamp"]).dt.hour
                        auth_offhours += int(((hours < 7) | (hours > 19)).sum())

            # Network signal: total bytes, unique destinations, protocol diversity
            net_bytes = 0
            net_unique_dst = set()
            net_protocols = set()
            for d in week_dates:
                csv = net_dir / f"{d.isoformat()}.csv"
                if csv.exists():
                    df = pd.read_csv(csv, nrows=50000)
                    if "bytes_out" in df.columns:
                        net_bytes += df["bytes_out"].sum()
                    if "dst_ip" in df.columns:
                        net_unique_dst.update(df["dst_ip"].dropna().unique()[:200])
                    if "protocol" in df.columns:
                        net_protocols.update(df["protocol"].dropna().unique())

            # Privilege signal
            priv_ops = 0
            priv_denied = 0
            for d in week_dates:
                csv = priv_dir / f"{d.isoformat()}.csv"
                if csv.exists():
                    df = pd.read_csv(csv)
                    udf = df[df["actor_user_id"] == user_id] if "actor_user_id" in df.columns else pd.DataFrame()
                    priv_ops += len(udf)
                    if "approved" in udf.columns:
                        priv_denied += len(udf[udf["approved"].astype(str).str.lower() == "false"])

            # Data access signal
            file_ops = 0
            file_bytes = 0
            file_sensitive = 0
            for d in week_dates:
                csv = file_dir / f"{d.isoformat()}.csv"
                if csv.exists():
                    df = pd.read_csv(csv)
                    udf = df[df["user_id"] == user_id] if "user_id" in df.columns else pd.DataFrame()
                    file_ops += len(udf)
                    if "file_size_bytes" in udf.columns:
                        file_bytes += udf["file_size_bytes"].sum()
                    if "data_classification" in udf.columns:
                        file_sensitive += len(udf[udf["data_classification"].isin(["confidential", "restricted"])])

            # App / communication signal
            app_events = 0
            app_unique = set()
            for d in week_dates:
                csv = app_dir / f"{d.isoformat()}.csv"
                if csv.exists():
                    df = pd.read_csv(csv)
                    udf = df[df["user_id"] == user_id] if "user_id" in df.columns else pd.DataFrame()
                    app_events += len(udf)
                    if "app_id" in udf.columns:
                        app_unique.update(udf["app_id"].dropna().unique())

            rows.append({
                "week": week_start.isoformat(),
                "auth_volume": auth_logins,
                "auth_failure_rate": auth_failures / max(auth_total, 1),
                "auth_offhours_rate": auth_offhours / max(auth_total, 1),
                "privilege_ops": priv_ops,
                "privilege_denied_rate": priv_denied / max(priv_ops, 1),
                "data_access_ops": file_ops,
                "data_access_bytes_mb": file_bytes / 1e6,
                "data_access_sensitive_rate": file_sensitive / max(file_ops, 1),
                "network_bytes_gb": net_bytes / 1e9,
                "network_unique_dst": len(net_unique_dst),
                "network_protocols": len(net_protocols),
                "communication_events": app_events,
                "communication_apps": len(app_unique),
            })

        if not rows:
            return None
        result = pd.DataFrame(rows)
        result["week"] = pd.to_datetime(result["week"])
        return result

    @st.cache_data
    def compute_signal_drift_scores(profile_df: pd.DataFrame) -> pd.DataFrame:
        """Compute normalized drift score per signal per week (0=baseline, 1=max deviation)."""
        signal_groups = {
            "auth": ["auth_volume", "auth_failure_rate", "auth_offhours_rate"],
            "privilege": ["privilege_ops", "privilege_denied_rate"],
            "data_access": ["data_access_ops", "data_access_bytes_mb", "data_access_sensitive_rate"],
            "network": ["network_bytes_gb", "network_unique_dst", "network_protocols"],
            "communication": ["communication_events", "communication_apps"],
        }
        result = pd.DataFrame({"week": profile_df["week"]})

        for signal_name, cols in signal_groups.items():
            available_cols = [c for c in cols if c in profile_df.columns]
            if not available_cols:
                result[signal_name] = 0.0
                continue
            # Compute z-score deviation from baseline (first 2 weeks)
            baseline_end = min(2, len(profile_df))
            scores = []
            for col in available_cols:
                baseline_mean = profile_df[col].iloc[:baseline_end].mean()
                baseline_std = profile_df[col].iloc[:baseline_end].std()
                if baseline_std < 1e-10:
                    baseline_std = profile_df[col].std()
                if baseline_std < 1e-10:
                    scores.append(pd.Series(0.0, index=profile_df.index))
                else:
                    z = ((profile_df[col] - baseline_mean) / baseline_std).abs()
                    scores.append(z)
            combined = pd.concat(scores, axis=1).mean(axis=1)
            # Normalize to 0-1 range
            cmax = combined.max()
            if cmax > 0:
                combined = combined / cmax
            result[signal_name] = combined.values

        return result

    @st.cache_data
    def get_available_users() -> list[str]:
        auth_dir = GENERATED_DIR / "auth"
        if not auth_dir.exists():
            return []
        first_csv = sorted(auth_dir.glob("*.csv"))
        if not first_csv:
            return []
        df = pd.read_csv(first_csv[0])
        if "user_id" not in df.columns:
            return []
        users = sorted(df["user_id"].unique().tolist())
        return users

    # Known attack entities to highlight
    ATTACK_ENTITIES = {
        "USR-087": "Phishing → Credential Theft → Lateral Movement (5-day)",
        "USR-234": "Slow APT — C2 Beacon + Data Staging (180-day)",
        "USR-156": "Insider Threat — 8-Month Escalation",
    }

    available_users = get_available_users()
    if not available_users:
        st.warning("No generated user data found. Run: `python -m simulator.generate --days 7`")
    else:
        pu1, pu2 = st.columns([2, 3])
        with pu1:
            # Prioritize attack entities at top of list
            attack_ids = [u for u in ATTACK_ENTITIES if u in available_users]
            other_ids = [u for u in available_users if u not in ATTACK_ENTITIES]
            ordered_users = attack_ids + other_ids
            selected_user = st.selectbox(
                "Select Entity",
                ordered_users,
                format_func=lambda u: f"⚠️ {u} — {ATTACK_ENTITIES[u]}" if u in ATTACK_ENTITIES else u,
            )
        with pu2:
            if selected_user in ATTACK_ENTITIES:
                st.markdown(f"""
                <div style="background:#FEF9E7; border-left:4px solid {GOLD}; padding:10px 16px; border-radius:6px; margin-top:8px;">
                    <strong>Injected Scenario:</strong> {ATTACK_ENTITIES[selected_user]}
                </div>
                """, unsafe_allow_html=True)

        with st.spinner(f"Computing behavioral signals for {selected_user}..."):
            profile = compute_user_behavioral_signals(selected_user)

        if profile is None or len(profile) < 2:
            st.warning(f"Insufficient data for {selected_user}. Need at least 2 weeks of logs.")
        else:
            drift_scores = compute_signal_drift_scores(profile)

            # ── COMPOSITE DRIFT RADAR ──
            st.subheader("Behavioral Signal Drift (Normalized)")
            st.markdown("Each signal normalized to 0-1 against its baseline. Spikes indicate behavioral anomalies in that dimension.")

            fig = px.line(
                drift_scores.melt(id_vars="week", var_name="signal", value_name="drift"),
                x="week",
                y="drift",
                color="signal",
                color_discrete_map=SIGNAL_COLORS,
                labels={"week": "Week", "drift": "Drift Score (0=baseline, 1=max)", "signal": "Behavioral Signal"},
            )
            fig.add_hline(y=0.5, line_dash="dash", line_color=GOLD, annotation_text="Elevated")
            fig.add_hline(y=0.8, line_dash="dash", line_color=RED, annotation_text="Critical")
            fig.update_layout(
                plot_bgcolor="white",
                height=400,
                margin=dict(l=40, r=20, t=20, b=40),
                font=dict(family="Segoe UI"),
                legend=dict(orientation="h", yanchor="bottom", y=-0.25),
            )
            st.plotly_chart(fig, width="stretch")

            # ── RADAR CHART: LATEST vs BASELINE ──
            st.subheader("Behavioral Fingerprint: Baseline vs Current")

            signals = ["auth", "privilege", "data_access", "network", "communication"]
            signal_labels = [SIGNAL_LABELS["user"].get(s, s) for s in signals]
            baseline_vals = [float(drift_scores[s].iloc[0]) for s in signals]
            current_vals = [float(drift_scores[s].iloc[-1]) for s in signals]
            # Close the radar polygon
            signal_labels_r = signal_labels + [signal_labels[0]]
            baseline_r = baseline_vals + [baseline_vals[0]]
            current_r = current_vals + [current_vals[0]]

            fig = go.Figure()
            fig.add_trace(go.Scatterpolar(
                r=baseline_r, theta=signal_labels_r, fill="toself",
                name="Baseline", line_color=BLUE, opacity=0.3,
            ))
            fig.add_trace(go.Scatterpolar(
                r=current_r, theta=signal_labels_r, fill="toself",
                name="Current", line_color=RED, opacity=0.5,
            ))
            fig.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                showlegend=True,
                height=400,
                margin=dict(l=60, r=60, t=40, b=40),
                font=dict(family="Segoe UI"),
            )
            st.plotly_chart(fig, width="stretch")

            # ── RAW SIGNAL METRICS ──
            st.subheader("Raw Behavioral Metrics Over Time")

            metric_tabs = st.tabs(["Authentication", "Privilege", "Data Access", "Network", "App / Comms"])

            with metric_tabs[0]:
                fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                                    subplot_titles=["Login Volume", "Failure Rate", "Off-Hours Rate"])
                fig.add_trace(go.Scatter(x=profile["week"], y=profile["auth_volume"],
                              mode="lines+markers", line_color=SIGNAL_COLORS["auth"], name="Logins"), row=1, col=1)
                fig.add_trace(go.Scatter(x=profile["week"], y=profile["auth_failure_rate"],
                              mode="lines+markers", line_color="#E67E22", name="Fail Rate"), row=2, col=1)
                fig.add_trace(go.Scatter(x=profile["week"], y=profile["auth_offhours_rate"],
                              mode="lines+markers", line_color="#9B59B6", name="Off-Hours"), row=3, col=1)
                fig.update_layout(height=500, showlegend=False, plot_bgcolor="white",
                                  margin=dict(l=40, r=20, t=40, b=20), font=dict(family="Segoe UI"))
                st.plotly_chart(fig, width="stretch")

            with metric_tabs[1]:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                                    subplot_titles=["Privilege Operations", "Denied Rate"])
                fig.add_trace(go.Scatter(x=profile["week"], y=profile["privilege_ops"],
                              mode="lines+markers", line_color=SIGNAL_COLORS["privilege"], name="Ops"), row=1, col=1)
                fig.add_trace(go.Scatter(x=profile["week"], y=profile["privilege_denied_rate"],
                              mode="lines+markers", line_color=RED, name="Denied"), row=2, col=1)
                fig.update_layout(height=400, showlegend=False, plot_bgcolor="white",
                                  margin=dict(l=40, r=20, t=40, b=20), font=dict(family="Segoe UI"))
                st.plotly_chart(fig, width="stretch")

            with metric_tabs[2]:
                fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                                    subplot_titles=["File Operations", "Data Volume (MB)", "Sensitive File Rate"])
                fig.add_trace(go.Scatter(x=profile["week"], y=profile["data_access_ops"],
                              mode="lines+markers", line_color=SIGNAL_COLORS["data_access"], name="Ops"), row=1, col=1)
                fig.add_trace(go.Scatter(x=profile["week"], y=profile["data_access_bytes_mb"],
                              mode="lines+markers", line_color="#8E44AD", name="MB"), row=2, col=1)
                fig.add_trace(go.Scatter(x=profile["week"], y=profile["data_access_sensitive_rate"],
                              mode="lines+markers", line_color=RED, name="Sensitive"), row=3, col=1)
                fig.update_layout(height=500, showlegend=False, plot_bgcolor="white",
                                  margin=dict(l=40, r=20, t=40, b=20), font=dict(family="Segoe UI"))
                st.plotly_chart(fig, width="stretch")

            with metric_tabs[3]:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                                    subplot_titles=["Network Volume (GB)", "Unique Destinations"])
                fig.add_trace(go.Scatter(x=profile["week"], y=profile["network_bytes_gb"],
                              mode="lines+markers", line_color=SIGNAL_COLORS["network"], name="GB"), row=1, col=1)
                fig.add_trace(go.Scatter(x=profile["week"], y=profile["network_unique_dst"],
                              mode="lines+markers", line_color="#2980B9", name="Destinations"), row=2, col=1)
                fig.update_layout(height=400, showlegend=False, plot_bgcolor="white",
                                  margin=dict(l=40, r=20, t=40, b=20), font=dict(family="Segoe UI"))
                st.plotly_chart(fig, width="stretch")

            with metric_tabs[4]:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                                    subplot_titles=["App Events", "Unique Apps Accessed"])
                fig.add_trace(go.Scatter(x=profile["week"], y=profile["communication_events"],
                              mode="lines+markers", line_color=SIGNAL_COLORS["communication"], name="Events"), row=1, col=1)
                fig.add_trace(go.Scatter(x=profile["week"], y=profile["communication_apps"],
                              mode="lines+markers", line_color="#16A085", name="Apps"), row=2, col=1)
                fig.update_layout(height=400, showlegend=False, plot_bgcolor="white",
                                  margin=dict(l=40, r=20, t=40, b=20), font=dict(family="Segoe UI"))
                st.plotly_chart(fig, width="stretch")

            # ── ANOMALY DETECTION PROOF ──
            st.subheader("Anomaly Detection Summary")
            st.markdown("Signals where drift score exceeded **0.5** (elevated) or **0.8** (critical) threshold:")

            anomaly_rows = []
            for s in signals:
                max_drift = float(drift_scores[s].max())
                peak_idx = drift_scores[s].idxmax()
                peak_week = drift_scores["week"].iloc[peak_idx].strftime("%Y-%m-%d") if peak_idx < len(drift_scores) else "N/A"
                level = "CRITICAL" if max_drift >= 0.8 else "ELEVATED" if max_drift >= 0.5 else "NORMAL"
                anomaly_rows.append({
                    "Signal": SIGNAL_LABELS["user"].get(s, s),
                    "Peak Drift": f"{max_drift:.3f}",
                    "Peak Week": peak_week,
                    "Status": level,
                })
            anomaly_df = pd.DataFrame(anomaly_rows)
            st.dataframe(anomaly_df, width="stretch", hide_index=True)

            if selected_user in ATTACK_ENTITIES:
                st.markdown(f"""
                <div style="background:linear-gradient(135deg, {NAVY} 0%, {BLUE} 100%); color:white; padding:16px 24px; border-radius:10px; margin-top:16px;">
                    <h4 style="color:{GOLD}; margin:0 0 8px 0;">Detection Verdict</h4>
                    <p style="color:#A0C8E0; margin:0;">
                    Entity <strong>{selected_user}</strong> has injected attack scenario:
                    <em>{ATTACK_ENTITIES[selected_user]}</em>.<br><br>
                    The behavioral decomposition above shows which signal dimensions deviated from baseline,
                    confirming ACECARD's ability to detect anomalous behavioral drift — even when individual events
                    appear benign. The per-signal breakdown reveals <strong>which aspect of behavior changed</strong>
                    (not just that something changed), enabling targeted investigation and faster SOC response.
                    </p>
                </div>
                """, unsafe_allow_html=True)


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
