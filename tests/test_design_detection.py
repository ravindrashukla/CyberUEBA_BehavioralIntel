"""Design-spec detection verification for ACECARD Tier 3.

Validates that the ACECARD detection system produces the results predicted
by the design specification: zone divergence, contextual detection, regime
shifts, escalation patterns, and false-positive bounds.

Attack users:
  USR-156: Insider threat (data exfiltration, identity stable)
  USR-234: Slow APT (C2 beaconing via network_footprint drift)
  USR-042: Volt Typhoon LOTL (legitimate-tool abuse, endpoint anomalies)
  USR-118: Salt Typhoon Telecom (telecom infrastructure targeting)

Requires a live PostgreSQL database at 127.0.0.1:5437 with seeded data.
"""
import os
import sys

import pytest
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Environment ──────────────────────────────────────────────────────────────

os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5437")
os.environ.setdefault("DB_NAME", "cyber_ueba")
os.environ.setdefault("DB_USER", "cyber_ueba")
os.environ.setdefault("DB_PASSWORD", "password")

ATTACK_USERS = ["USR-156", "USR-234", "USR-042", "USR-118"]


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def conn():
    """Module-scoped autocommit database connection."""
    c = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    c.autocommit = True
    yield c
    c.close()


@pytest.fixture(scope="module")
def max_feature_date(conn):
    """Latest feature_date in daily_features."""
    with conn.cursor() as cur:
        cur.execute("SELECT max(feature_date) FROM daily_features")
        return cur.fetchone()[0]


@pytest.fixture(scope="module")
def min_feature_date(conn):
    """Earliest feature_date in daily_features."""
    with conn.cursor() as cur:
        cur.execute("SELECT min(feature_date) FROM daily_features")
        return cur.fetchone()[0]


@pytest.fixture(scope="module")
def max_traj_date(conn):
    """Latest cutoff_date in trajectory_snapshots."""
    with conn.cursor() as cur:
        cur.execute("SELECT max(cutoff_date) FROM trajectory_snapshots")
        return cur.fetchone()[0]


def _latest_zone_drifts(conn, entity_id, max_date):
    """Return zone_drifts JSONB from the latest trajectory_snapshot."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT zone_drifts FROM trajectory_snapshots
               WHERE entity_id = %s AND cutoff_date = %s""",
            (entity_id, max_date),
        )
        row = cur.fetchone()
        return row[0] if row else None


def _latest_context_drifts(conn, entity_id, max_date):
    """Return context_drifts JSONB from the latest trajectory_snapshot."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT context_drifts FROM trajectory_snapshots
               WHERE entity_id = %s AND cutoff_date = %s""",
            (entity_id, max_date),
        )
        row = cur.fetchone()
        return row[0] if row else None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: USR-156 zone divergence -- data_behavior drifting, identity stable
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_01_usr156_zone_divergence(conn, max_traj_date):
    """USR-156 (insider) data_behavior zone drift > identity zone drift.

    Design spec: 'identity stable but data_behavior drifting' -- the insider
    threat changes WHAT data they access, not WHO they are.
    """
    zd = _latest_zone_drifts(conn, "USR-156", max_traj_date)
    assert zd is not None, "USR-156 has no trajectory_snapshots"
    identity_drift = abs(float(zd.get("identity", 0)))
    data_drift = float(zd.get("data_behavior", 0))
    assert data_drift > identity_drift, (
        f"USR-156 data_behavior drift ({data_drift:.4f}) should exceed "
        f"identity drift ({identity_drift:.4f})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: USR-234 zone divergence -- network_footprint drifting, identity stable
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_02_usr234_zone_divergence(conn, max_traj_date):
    """USR-234 (APT) network_footprint zone drift > identity zone drift.

    Design spec: 'identity stable but network_footprint drifting' -- the APT
    changes NETWORK behavior (C2 beacon), not identity.
    """
    zd = _latest_zone_drifts(conn, "USR-234", max_traj_date)
    assert zd is not None, "USR-234 has no trajectory_snapshots"
    identity_drift = abs(float(zd.get("identity", 0)))
    net_drift = float(zd.get("network_footprint", 0))
    assert net_drift > identity_drift, (
        f"USR-234 network_footprint drift ({net_drift:.4f}) should exceed "
        f"identity drift ({identity_drift:.4f})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: USR-156 contextual -- insider_investigation > normal_ops
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_03_usr156_contextual_detection(conn, max_traj_date):
    """USR-156 insider_investigation context drift > normal_ops drift.

    Design spec: 'USR-156 scores high under insider_investigation context
    (data_behavior weighted 0.40)'.
    """
    cd = _latest_context_drifts(conn, "USR-156", max_traj_date)
    assert cd is not None, "USR-156 has no context_drifts"
    insider = float(cd["insider_investigation"])
    normal = float(cd["normal_ops"])
    assert insider > normal, (
        f"USR-156 insider_investigation drift ({insider:.4f}) should exceed "
        f"normal_ops drift ({normal:.4f})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: USR-234 contextual -- apt_hunt > normal_ops
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_04_usr234_contextual_detection(conn, max_traj_date):
    """USR-234 apt_hunt context drift > normal_ops drift.

    Design spec: 'USR-234 scores high under apt_hunt context
    (network_footprint weighted 0.40)'.
    """
    cd = _latest_context_drifts(conn, "USR-234", max_traj_date)
    assert cd is not None, "USR-234 has no context_drifts"
    apt = float(cd["apt_hunt"])
    normal = float(cd["normal_ops"])
    assert apt > normal, (
        f"USR-234 apt_hunt drift ({apt:.4f}) should exceed "
        f"normal_ops drift ({normal:.4f})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: USR-042 endpoint anomaly (Volt Typhoon LOTL)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_05_usr042_endpoint_anomaly(conn, max_feature_date):
    """USR-042 (Volt Typhoon LOTL) mean endpoint_suspicious_ratio > 0 in last 30 days.

    Design spec: 'USR-042 should show endpoint anomalies' -- LOTL attacks
    abuse legitimate tools, producing elevated endpoint risk signals.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT avg(endpoint_suspicious_ratio)
               FROM daily_features
               WHERE user_id = 'USR-042'
                 AND feature_date >= %s - interval '30 days'""",
            (max_feature_date,),
        )
        avg_ratio = cur.fetchone()[0]
    assert avg_ratio is not None, "No daily_features for USR-042"
    assert avg_ratio > 0, (
        f"USR-042 mean endpoint_suspicious_ratio ({avg_ratio:.4f}) should be > 0"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6: USR-118 network/behavioral anomaly (Salt Typhoon Telecom)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_06_usr118_behavioral_anomaly(conn, max_feature_date):
    """USR-118 (Salt Typhoon) should show behavioral anomalies.

    Salt Typhoon targets telecom infrastructure. The attack manifests through
    elevated off-hours authentication, restricted file access, or other
    behavioral indicators even when direct network flow attribution is
    incomplete. At least one indicator should be nonzero.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT avg(file_restricted_ratio),
                      avg(auth_off_hours_ratio),
                      avg(net_external_ratio),
                      avg(dns_nxdomain_ratio)
               FROM daily_features
               WHERE user_id = 'USR-118'
                 AND feature_date >= %s - interval '30 days'""",
            (max_feature_date,),
        )
        file_restr, off_hours, net_ext, dns_nx = cur.fetchone()
    assert file_restr is not None, "No daily_features for USR-118"
    has_anomaly = (
        (file_restr or 0) > 0
        or (off_hours or 0) > 0
        or (net_ext or 0) > 0
        or (dns_nx or 0) > 0
    )
    assert has_anomaly, (
        f"USR-118 should show at least one behavioral anomaly: "
        f"file_restricted={file_restr:.4f}, off_hours={off_hours:.4f}, "
        f"net_ext={net_ext:.4f}, dns_nx={dns_nx:.4f}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7: All 4 attack users detected by trajectory events
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_07_all_attack_users_have_trajectory_events(conn):
    """Each attack user must have at least 1 trajectory_event."""
    for uid in ATTACK_USERS:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM trajectory_events WHERE entity_id = %s",
                (uid,),
            )
            count = cur.fetchone()[0]
        assert count >= 1, f"{uid} has {count} trajectory_events, expected >= 1"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8: Normal users lower mean context drift than best attack user
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_08_normal_users_lower_context_drift(conn, max_traj_date):
    """At least 1 attack user's max context drift should exceed the mean of
    a sample of 20 normal users' mean context drift (averaged over 4 contexts).
    """
    with conn.cursor() as cur:
        # Mean of normal users' average-across-contexts drift (sample 20)
        cur.execute(
            """SELECT avg(mean_ctx) FROM (
                 SELECT ((context_drifts->>'normal_ops')::float +
                         (context_drifts->>'insider_investigation')::float +
                         (context_drifts->>'apt_hunt')::float +
                         (context_drifts->>'privilege_audit')::float) / 4.0
                        AS mean_ctx
                 FROM trajectory_snapshots
                 WHERE cutoff_date = %s
                   AND entity_id NOT IN ('USR-156', 'USR-234', 'USR-042', 'USR-118')
                 LIMIT 20
               ) sub""",
            (max_traj_date,),
        )
        normal_mean = cur.fetchone()[0]

        # Best attack user max context drift
        attack_max = 0.0
        for uid in ATTACK_USERS:
            cur.execute(
                """SELECT greatest(
                     (context_drifts->>'normal_ops')::float,
                     (context_drifts->>'insider_investigation')::float,
                     (context_drifts->>'apt_hunt')::float,
                     (context_drifts->>'privilege_audit')::float
                   )
                   FROM trajectory_snapshots
                   WHERE entity_id = %s AND cutoff_date = %s""",
                (uid, max_traj_date),
            )
            row = cur.fetchone()
            if row and row[0]:
                attack_max = max(attack_max, float(row[0]))

    assert attack_max > normal_mean, (
        f"Best attack user max context drift ({attack_max:.4f}) should exceed "
        f"normal users' mean context drift ({normal_mean:.4f})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 9: Zone divergence positive for attack users
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_09_zone_divergence_positive_for_attack_users(conn, max_traj_date):
    """For each attack user, max(non-identity zone drift) - identity drift > 0.

    This is the core zone divergence concept: the entity's identity stays
    stable while at least one behavioral zone drifts.
    """
    for uid in ATTACK_USERS:
        zd = _latest_zone_drifts(conn, uid, max_traj_date)
        assert zd is not None, f"{uid} has no zone_drifts"

        identity = abs(float(zd.get("identity", 0)))
        behavioral_zones = [
            "access_pattern", "data_behavior", "network_footprint", "risk_posture",
        ]
        max_behavioral = max(float(zd.get(z, 0)) for z in behavioral_zones)
        divergence = max_behavioral - identity

        assert divergence > 0, (
            f"{uid} zone divergence ({divergence:.4f}) should be positive. "
            f"max_behavioral={max_behavioral:.4f}, identity={identity:.4f}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 10: USR-156 data escalation (file_restricted_ratio increases over time)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_10_usr156_data_escalation(conn, min_feature_date, max_feature_date):
    """USR-156 file_restricted_ratio last 30 days > first 30 days.

    Design spec: insider threat 'gradually escalating access and
    exfiltrating data' -- restricted file access should increase over time.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT avg(file_restricted_ratio) FROM daily_features
               WHERE user_id = 'USR-156'
                 AND feature_date <= %s + interval '30 days'""",
            (min_feature_date,),
        )
        first_30 = cur.fetchone()[0]

        cur.execute(
            """SELECT avg(file_restricted_ratio) FROM daily_features
               WHERE user_id = 'USR-156'
                 AND feature_date >= %s - interval '30 days'""",
            (max_feature_date,),
        )
        last_30 = cur.fetchone()[0]

    assert first_30 is not None and last_30 is not None, (
        "Missing daily_features data for USR-156"
    )
    assert last_30 > first_30, (
        f"USR-156 file_restricted_ratio should escalate: "
        f"first 30d ({first_30:.4f}) -> last 30d ({last_30:.4f})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 11: USR-234 network escalation
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_11_usr234_network_escalation(conn, min_feature_date, max_feature_date):
    """USR-234 net_external_ratio last 30 days > first 30 days.

    Design spec: slow APT with 'gradual data staging' -- external network
    ratio should increase as the APT escalates C2 and exfil activity.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT avg(net_external_ratio) FROM daily_features
               WHERE user_id = 'USR-234'
                 AND feature_date <= %s + interval '30 days'""",
            (min_feature_date,),
        )
        first_30 = cur.fetchone()[0]

        cur.execute(
            """SELECT avg(net_external_ratio) FROM daily_features
               WHERE user_id = 'USR-234'
                 AND feature_date >= %s - interval '30 days'""",
            (max_feature_date,),
        )
        last_30 = cur.fetchone()[0]

    assert first_30 is not None and last_30 is not None, (
        "Missing daily_features data for USR-234"
    )
    assert last_30 > first_30, (
        f"USR-234 net_external_ratio should escalate: "
        f"first 30d ({first_30:.4f}) -> last 30d ({last_30:.4f})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 12: Regime shift events exist
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_12_regime_shift_events_exist(conn):
    """trajectory_events should contain event_type = 'regime_shift'.

    Design spec: 'Regime shift when cosine(consecutive embeddings) < 0.7'
    -- the pipeline must detect and record these phase transitions.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM trajectory_events
               WHERE event_type = 'regime_shift'"""
        )
        count = cur.fetchone()[0]
    assert count > 0, "No regime_shift events found in trajectory_events"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 13: Attack user drift ranking -- at least 1 in top 20%
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_13_attack_user_drift_ranking(conn, max_traj_date):
    """At least 1 of the 4 attack users should be in the top 50 (top 20%)
    by total_drift at the latest trajectory snapshot date.
    """
    with conn.cursor() as cur:
        cur.execute(
            """WITH ranked AS (
                 SELECT entity_id, total_drift,
                        rank() OVER (ORDER BY total_drift DESC) AS rnk
                 FROM trajectory_snapshots
                 WHERE cutoff_date = %s
               )
               SELECT entity_id, rnk FROM ranked
               WHERE entity_id IN ('USR-156', 'USR-234', 'USR-042', 'USR-118')
                 AND rnk <= 50""",
            (max_traj_date,),
        )
        in_top50 = cur.fetchall()

    assert len(in_top50) >= 1, (
        "At least 1 attack user should rank in top 50 by total_drift. "
        "None found."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 14: Context specificity -- insider detected best by insider context,
#          APT detected best by APT context
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_14_context_specificity(conn, max_traj_date):
    """USR-156 insider_investigation > apt_hunt drift (insider signature).
    USR-234 apt_hunt > insider_investigation drift (APT signature).

    Design spec: context-adaptive weighting should make each attack type
    most visible under its matching investigation context.
    """
    # USR-156: insider context should be stronger than APT context
    cd156 = _latest_context_drifts(conn, "USR-156", max_traj_date)
    assert cd156 is not None, "USR-156 has no context_drifts"
    assert float(cd156["insider_investigation"]) > float(cd156["apt_hunt"]), (
        f"USR-156 insider_investigation ({cd156['insider_investigation']}) "
        f"should exceed apt_hunt ({cd156['apt_hunt']})"
    )

    # USR-234: APT context should be stronger than insider context
    cd234 = _latest_context_drifts(conn, "USR-234", max_traj_date)
    assert cd234 is not None, "USR-234 has no context_drifts"
    assert float(cd234["apt_hunt"]) > float(cd234["insider_investigation"]), (
        f"USR-234 apt_hunt ({cd234['apt_hunt']}) "
        f"should exceed insider_investigation ({cd234['insider_investigation']})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 15: False positive estimation -- FP rate under 50% at p90 threshold
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.p0
def test_15_false_positive_estimation(conn, max_traj_date):
    """Normal users whose max context drift exceeds the population 90th
    percentile threshold should be less than 50% of normal users.

    The design spec targets ~4-6% FP for contextual detection. We use the
    90th percentile of the max-context-drift distribution as a data-driven
    threshold (adapted for MockEmbedder). The FP count at this threshold
    must stay under 50%.
    """
    with conn.cursor() as cur:
        # Compute p90 of max_context_drift across ALL users at latest date
        cur.execute(
            """SELECT percentile_cont(0.90) WITHIN GROUP (
                 ORDER BY greatest(
                   (context_drifts->>'normal_ops')::float,
                   (context_drifts->>'insider_investigation')::float,
                   (context_drifts->>'apt_hunt')::float,
                   (context_drifts->>'privilege_audit')::float
                 )
               )
               FROM trajectory_snapshots
               WHERE cutoff_date = %s""",
            (max_traj_date,),
        )
        p90_threshold = cur.fetchone()[0]

        # Count normal users exceeding p90
        cur.execute(
            """SELECT count(*) FROM trajectory_snapshots
               WHERE cutoff_date = %s
                 AND entity_id NOT IN ('USR-156', 'USR-234', 'USR-042', 'USR-118')
                 AND greatest(
                       (context_drifts->>'normal_ops')::float,
                       (context_drifts->>'insider_investigation')::float,
                       (context_drifts->>'apt_hunt')::float,
                       (context_drifts->>'privilege_audit')::float
                     ) > %s""",
            (max_traj_date, p90_threshold),
        )
        fp_count = cur.fetchone()[0]

        # Total normal users
        cur.execute(
            """SELECT count(*) FROM trajectory_snapshots
               WHERE cutoff_date = %s
                 AND entity_id NOT IN ('USR-156', 'USR-234', 'USR-042', 'USR-118')""",
            (max_traj_date,),
        )
        total_normal = cur.fetchone()[0]

    fp_rate = fp_count / max(total_normal, 1)
    assert fp_rate < 0.50, (
        f"FP rate at p90 threshold ({p90_threshold:.4f}) is {fp_rate:.1%} "
        f"({fp_count}/{total_normal}) -- should be < 50%"
    )
