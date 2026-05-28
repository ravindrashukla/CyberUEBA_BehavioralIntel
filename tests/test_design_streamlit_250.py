"""Design-Verification Tests: 250-user requirement for ACECARD Streamlit dashboard.

Test IDs: DES-001 through DES-016
Verifies that:
- No hardcoded "50" references survive in streamlit_app.py
- DB-backed pages return data for all 250 users
- Story Mode uses dynamic values, not hardcoded user counts
- Digital Entity page uses load_all_user_ids() for the full population

Requires PostgreSQL at 127.0.0.1:5437 for DB tests (skip if unavailable).
"""

import os
import re
import sys

import pandas as pd
import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set DB env vars before importing pipeline modules
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5437")
os.environ.setdefault("DB_NAME", "cyber_ueba")
os.environ.setdefault("DB_USER", "cyber_ueba")
os.environ.setdefault("DB_PASSWORD", "password")

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
GENERATED_DIR = BASE_DIR / "data" / "generated"
STREAMLIT_APP = BASE_DIR / "streamlit_app.py"

from pipeline.streamlit_db import (
    db_available,
    load_dashboard_stats,
    load_drift_heatmap,
    load_entity_structure,
    load_all_user_ids,
    load_behavioral_signals_from_db,
)

DB_IS_UP = db_available()
requires_db = pytest.mark.skipif(not DB_IS_UP, reason="PostgreSQL not reachable at 127.0.0.1:5437")

# Read streamlit_app.py once for all static analysis tests
APP_TEXT = STREAMLIT_APP.read_text(encoding="utf-8")

ATTACK_USERS = ["USR-156", "USR-234", "USR-042", "USR-118"]


# ── Static Analysis: no hardcoded "50" references ────────────────────────────

class TestNoHardcoded50:
    """DES-001 through DES-004: Ensure all '50' references have been removed."""

    def test_des_001_no_50_entities(self):
        """DES-001: No hardcoded '50 Entities' in streamlit_app.py."""
        assert "50 Entities" not in APP_TEXT, (
            "Found '50 Entities' in streamlit_app.py -- must use dynamic count"
        )

    def test_des_002_no_50_users(self):
        """DES-002: No hardcoded '50 users' (case-insensitive) in streamlit_app.py.
        Note: '50%' is OK, '250-user' is OK, but '50 users' or '50-user' (without 250 prefix) is NOT."""
        # Find all occurrences of '50 users' case insensitive
        matches_50_users = [
            m for m in re.finditer(r'50 users', APP_TEXT, re.IGNORECASE)
        ]
        assert len(matches_50_users) == 0, (
            f"Found '50 users' at positions: {[m.start() for m in matches_50_users]}"
        )

        # Find '50-user' NOT preceded by '2' (which would make it '250-user')
        matches_50_user_dash = [
            m for m in re.finditer(r'50-user', APP_TEXT, re.IGNORECASE)
            if m.start() == 0 or APP_TEXT[m.start() - 1] != '2'
        ]
        assert len(matches_50_user_dash) == 0, (
            f"Found bare '50-user' (not '250-user') at positions: "
            f"{[m.start() for m in matches_50_user_dash]}"
        )

    def test_des_003_no_head_50(self):
        """DES-003: No .head(50) calls in streamlit_app.py."""
        assert ".head(50)" not in APP_TEXT, (
            "Found '.head(50)' in streamlit_app.py -- must show all users"
        )

    def test_des_004_no_users_50_flag(self):
        """DES-004: No '--users 50' in streamlit_app.py (should be --users 250)."""
        assert "--users 50" not in APP_TEXT, (
            "Found '--users 50' in streamlit_app.py -- should be '--users 250'"
        )


# ── Data File Check ──────────────────────────────────────────────────────────

class TestUsersCSV:
    """DES-005: users.csv has exactly 250 rows."""

    def test_des_005_users_csv_250_rows(self):
        csv_path = GENERATED_DIR / "entities" / "users.csv"
        assert csv_path.exists(), f"users.csv not found at {csv_path}"
        df = pd.read_csv(csv_path)
        assert len(df) == 250, (
            f"Expected 250 users in users.csv, found {len(df)}"
        )


# ── DB-Backed Page Tests ─────────────────────────────────────────────────────

class TestDB250Users:
    """DES-006 through DES-010: Verify DB functions return 250-user dataset."""

    @requires_db
    def test_des_006_load_all_user_ids_250(self):
        """DES-006: load_all_user_ids() returns 250 user IDs."""
        ids = load_all_user_ids()
        assert len(ids) == 250, (
            f"Expected 250 user IDs from load_all_user_ids(), got {len(ids)}"
        )

    @requires_db
    def test_des_007_drift_heatmap_250(self):
        """DES-007: load_drift_heatmap() returns 250 rows (one per user)."""
        df = load_drift_heatmap()
        assert not df.empty, "load_drift_heatmap() returned empty DataFrame"
        assert len(df) == 250, (
            f"Expected 250 rows in drift heatmap, got {len(df)}"
        )

    @requires_db
    def test_des_008_dashboard_stats_250_users(self):
        """DES-008: load_dashboard_stats() reports total_users == 250."""
        stats = load_dashboard_stats()
        assert stats, "load_dashboard_stats() returned empty dict"
        assert "total_users" in stats, "total_users key missing from dashboard stats"
        assert stats["total_users"] == 250, (
            f"Expected total_users == 250, got {stats['total_users']}"
        )

    @requires_db
    def test_des_009_entity_structure_attack_users(self):
        """DES-009: load_entity_structure works for all 4 attack users."""
        for uid in ATTACK_USERS:
            entity = load_entity_structure(uid)
            assert entity, f"load_entity_structure('{uid}') returned empty dict"
            assert entity.get("entity_id") == uid, (
                f"Entity ID mismatch for {uid}: got {entity.get('entity_id')}"
            )

    @requires_db
    def test_des_010_behavioral_signals_last_user(self):
        """DES-010: load_behavioral_signals_from_db works for USR-250 (last user)."""
        df = load_behavioral_signals_from_db("USR-250")
        assert not df.empty, (
            "load_behavioral_signals_from_db('USR-250') returned empty -- "
            "last user in 250-user dataset must have data"
        )


# ── Story Mode Dynamic Values ────────────────────────────────────────────────

class TestStoryModeDynamic:
    """DES-011 through DES-014: Story Mode uses dynamic values, not hardcoded '50'."""

    def test_des_011_hero_text_dynamic(self):
        """DES-011: Story Mode hero banner uses _n_story_users or f-string interpolation."""
        # Find the hero banner section (between 'Can You Spot the Attacker?' and 'Act 1')
        hero_match = re.search(
            r'Can You Spot the Attacker\?.*?users\.',
            APP_TEXT, re.DOTALL
        )
        assert hero_match, "Could not find hero banner in streamlit_app.py"
        hero_text = hero_match.group()
        # Must use dynamic interpolation, not hardcoded "50"
        assert "_n_story_users" in hero_text or "{" in hero_text, (
            "Hero banner does not use dynamic _n_story_users or f-string -- "
            "may be hardcoded"
        )
        assert "50 users" not in hero_text.lower(), (
            "Hero banner still contains hardcoded '50 users'"
        )

    def test_des_012_user_table_no_head_50(self):
        """DES-012: Story Mode user table shows all users, not .head(50)."""
        # Find the section between 'User Population' and the next st.subheader
        pop_match = re.search(
            r'User Population.*?st\.dataframe\(.*?\)',
            APP_TEXT, re.DOTALL
        )
        assert pop_match, "Could not find User Population dataframe section"
        pop_section = pop_match.group()
        assert ".head(50)" not in pop_section, (
            "User Population table uses .head(50) -- must show all users"
        )

    def test_des_013_scatter_uses_db(self):
        """DES-013: Story Mode scatter plot uses DB (USE_DB check) or _story_feat_df."""
        # The scatter section should reference USE_DB or _story_feat_df
        scatter_section_match = re.search(
            r'Weekly Activity.*?fig_scatter',
            APP_TEXT, re.DOTALL
        )
        assert scatter_section_match, "Could not find scatter plot section"
        scatter_section = scatter_section_match.group()
        uses_db = "USE_DB" in scatter_section
        uses_story_feat = "_story_feat_df" in scatter_section
        assert uses_db or uses_story_feat, (
            "Scatter plot section does not reference USE_DB or _story_feat_df -- "
            "may not be using DB-sourced data"
        )

    def test_des_014_weekly_activity_header_dynamic(self):
        """DES-014: Weekly Activity header uses f-string with _n_story_users."""
        # Find the Weekly Activity subheader line
        weekly_match = re.search(r'Weekly Activity.*?Users', APP_TEXT)
        assert weekly_match, "Could not find 'Weekly Activity' header"
        weekly_line = weekly_match.group()
        assert "_n_story_users" in weekly_line or "{" in weekly_line, (
            f"Weekly Activity header is not dynamic: '{weekly_line}'"
        )


# ── 250-user References ──────────────────────────────────────────────────────

class TestReferences250:
    """DES-015: Verify '250-user' appears in file (LOF footnotes, dataset references)."""

    def test_des_015_250_user_references(self):
        """DES-015: '250-user' should appear multiple times in streamlit_app.py."""
        matches = re.findall(r'250-user', APP_TEXT)
        assert len(matches) >= 2, (
            f"Expected at least 2 '250-user' references, found {len(matches)}"
        )


# ── Digital Entity Page ──────────────────────────────────────────────────────

class TestDigitalEntityPage:
    """DES-016: Digital Entity page uses load_all_user_ids() for full 250-user population."""

    def test_des_016_digital_entity_uses_load_all(self):
        """DES-016: Digital Entity section calls load_all_user_ids()."""
        # Find the Digital Entity page section
        de_match = re.search(
            r'page == "Digital Entity".*?(?=\nelif page ==|\Z)',
            APP_TEXT, re.DOTALL
        )
        assert de_match, "Could not find Digital Entity page section"
        de_section = de_match.group()
        assert "load_all_user_ids()" in de_section, (
            "Digital Entity page does not call load_all_user_ids() -- "
            "may not be showing all 250 users"
        )
