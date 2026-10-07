"""Unit tests for Application Knowledge tools and dependency mapping (PROJECT_SPEC.md Portal features)."""

import os
from unittest.mock import MagicMock, patch
import pytest

from app.sim.engine import engine, health, DEPENDENCY_MAP
from app.mcp_server.tools.appknow import get_app_knowledge, save_app_knowledge
from app.mcp_server.tools.tickets import record_approval


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Set up clean SQLite tickets DB for tests."""
    db_file = str(tmp_path / "test_tickets.db")
    monkeypatch.setenv("TICKET_DB", db_file)
    monkeypatch.setattr("app.mcp_server.tools.tickets.TICKET_DB", db_file)
    yield


# ==============================================================================
# 1. Simulator Dependency Map & Health Tests
# ==============================================================================

def test_dependency_map_structure():
    """Verify dependency map entries per PROJECT_SPEC.md."""
    assert DEPENDENCY_MAP["calc-engine"] == ["orders-db", "msg-queue"]
    assert DEPENDENCY_MAP["feed-gateway"] == ["msg-queue"]
    assert DEPENDENCY_MAP["orders-db"] == []
    assert DEPENDENCY_MAP["msg-queue"] == []


def test_health_returns_dependencies():
    """Verify health(service) and engine.get_service_health(service) return depends_on and used_by."""
    # 1. calc-engine
    h_calc = health("calc-engine")
    assert h_calc["service"] == "calc-engine"
    assert h_calc["depends_on"] == ["orders-db", "msg-queue"]
    assert h_calc["used_by"] == []
    assert h_calc["status"] in {"HEALTHY", "DEGRADED", "CRITICAL"}
    assert "as_of" in h_calc

    # 2. feed-gateway
    h_feed = health("feed-gateway")
    assert h_feed["depends_on"] == ["msg-queue"]
    assert h_feed["used_by"] == []

    # 3. orders-db
    h_db = health("orders-db")
    assert h_db["depends_on"] == []
    assert h_db["used_by"] == ["calc-engine"]

    # 4. msg-queue
    h_mq = health("msg-queue")
    assert h_mq["depends_on"] == []
    assert set(h_mq["used_by"]) == {"calc-engine", "feed-gateway"}

    # 5. engine.health method alias
    h_engine = engine.health("calc-engine")
    assert h_engine["depends_on"] == ["orders-db", "msg-queue"]


# ==============================================================================
# 2. Application Knowledge Approval Gate Tests
# ==============================================================================

@patch("app.mcp_server.tools.appknow.kb_upsert")
def test_save_app_knowledge_fails_without_approved_approval_id(mock_kb, tmp_path):
    """save_app_knowledge must raise PermissionError if approval_id is missing or not approved."""
    base_dir = str(tmp_path / "app_knowledge")

    # Missing / empty approval_id
    with pytest.raises(PermissionError):
        save_app_knowledge(
            service="calc-engine",
            markdown="# Calc Engine Docs",
            approval_id="",
            base_dir=base_dir,
        )

    # Non-existent approval_id
    with pytest.raises(PermissionError):
        save_app_knowledge(
            service="calc-engine",
            markdown="# Calc Engine Docs",
            approval_id="APPR-NONEXISTENT",
            base_dir=base_dir,
        )

    # REJECTED approval_id
    rejected = record_approval(
        incident_id="scan-calc-engine",
        approver="lead-architect",
        decision="REJECTED",
        reason="Draft needs more detail",
    )
    with pytest.raises(PermissionError):
        save_app_knowledge(
            service="calc-engine",
            markdown="# Calc Engine Docs",
            approval_id=rejected["approval_id"],
            base_dir=base_dir,
        )

    # No files should have been created
    assert not os.path.exists(os.path.join(base_dir, "calc-engine.md"))
    mock_kb.assert_not_called()


# ==============================================================================
# 3. Version Increment & History Retention Tests
# ==============================================================================

@patch("app.mcp_server.tools.appknow.kb_upsert")
def test_save_app_knowledge_version_increment_and_history(mock_kb, tmp_path):
    """save_app_knowledge increments version, keeps previous version in history, and indexes chunks."""
    base_dir = str(tmp_path / "app_knowledge")
    history_dir = os.path.join(base_dir, "history")

    # --- Save Version 1 ---
    appr1 = record_approval(
        incident_id="scan-calc-engine-1",
        approver="tech-lead",
        decision="APPROVED",
    )
    v1_content = "## Overview\nInitial documentation for calculation engine."
    res1 = save_app_knowledge(
        service="calc-engine",
        markdown=v1_content,
        approval_id=appr1["approval_id"],
        base_dir=base_dir,
    )

    assert res1["version"] == 1
    assert "updated" in res1
    assert os.path.exists(res1["path"])
    # History directory exists, but no previous version was archived
    assert len(os.listdir(history_dir)) == 0
    assert mock_kb.call_count >= 1

    # Verify get_app_knowledge retrieves v1
    doc1 = get_app_knowledge("calc-engine", base_dir=base_dir)
    assert doc1["exists"] is True
    assert doc1["version"] == 1
    assert "Initial documentation" in doc1["markdown"]

    # --- Save Version 2 ---
    mock_kb.reset_mock()
    appr2 = record_approval(
        incident_id="scan-calc-engine-2",
        approver="tech-lead",
        decision="APPROVED",
    )
    v2_content = "## Overview\nUpdated calculation engine documentation.\n## Known Errors\nJOB-5003 batch failure."
    res2 = save_app_knowledge(
        service="calc-engine",
        markdown=v2_content,
        approval_id=appr2["approval_id"],
        base_dir=base_dir,
    )

    assert res2["version"] == 2

    # Verify history kept version 1
    v1_history_file = os.path.join(history_dir, "calc-engine_v1.md")
    assert os.path.exists(v1_history_file)
    with open(v1_history_file, "r", encoding="utf-8") as f:
        v1_archived = f.read()
    assert "Initial documentation" in v1_archived
    assert "- Version: 1" in v1_archived

    # Verify current file is now version 2
    doc2 = get_app_knowledge("calc-engine", base_dir=base_dir)
    assert doc2["version"] == 2
    assert "JOB-5003" in doc2["markdown"]
    assert mock_kb.call_count >= 1

    # --- Save Version 3 ---
    appr3 = record_approval(
        incident_id="scan-calc-engine-3",
        approver="tech-lead",
        decision="APPROVED",
    )
    v3_content = "## Overview\nV3 calculation engine.\n## Change Log\nAdded dependency diagram."
    res3 = save_app_knowledge(
        service="calc-engine",
        markdown=v3_content,
        approval_id=appr3["approval_id"],
        base_dir=base_dir,
    )

    assert res3["version"] == 3

    # Verify both v1 and v2 are kept in history
    v2_history_file = os.path.join(history_dir, "calc-engine_v2.md")
    assert os.path.exists(v1_history_file)
    assert os.path.exists(v2_history_file)
    with open(v2_history_file, "r", encoding="utf-8") as f:
        v2_archived = f.read()
    assert "- Version: 2" in v2_archived

    # Verify get_app_knowledge on nonexistent service
    unknown = get_app_knowledge("unknown-service", base_dir=base_dir)
    assert unknown["exists"] is False
    assert unknown["version"] == 0
    assert unknown["markdown"] == ""

