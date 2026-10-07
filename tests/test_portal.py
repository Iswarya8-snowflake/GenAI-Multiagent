"""Unit tests for knowledge document builder/merger and step narration (PROJECT_SPEC.md Portal features).

Strictly tests deterministic, template-based narration and document manipulation
with zero LLM and zero network calls.
"""

from app.graph.knowledge_doc import build_profile, merge_known_error
from app.api.narration import narrate


# ==============================================================================
# 1. Knowledge Document Tests
# ==============================================================================

def test_build_profile_with_facts():
    """Verify build_profile correctly formats all sections with provided facts."""
    facts = {
        "owner": "database-engineering",
        "overview": "Primary relational database hosting user orders and transactions.",
        "depends_on": [],
        "used_by": ["calc-engine"],
        "known_errors": [
            {
                "code": "DB-1205",
                "meaning": "Lock wait timeout exceeded",
                "cause": "Long-running report held row locks",
                "fix": "Kill blocking session and tune query",
                "last_seen": "2026-10-06 08:00:00",
                "source": "runbook",
            }
        ],
        "incident_history": [
            {
                "id": "INC-101",
                "symptom": "Orders write timeout",
                "root_cause": "Long report query",
                "fix": "Killed session 4821",
            }
        ],
        "runbooks": ["data/runbooks/db-lock.md"],
    }

    doc = build_profile("orders-db", facts=facts, version=1)

    # Check header
    assert "# Application Knowledge: orders-db" in doc
    assert "- Version: 1" in doc
    assert "- Updated:" in doc

    # Check sections
    assert "## Overview and owner" in doc
    assert "database-engineering" in doc
    assert "## Dependencies" in doc
    assert "- **Depends on:** None" in doc
    assert "- **Used by:** calc-engine" in doc

    assert "## Known errors" in doc
    assert "| DB-1205 | Lock wait timeout exceeded |" in doc

    assert "## Incident history" in doc
    assert "**INC-101**" in doc

    assert "## Runbook links" in doc
    assert "data/runbooks/db-lock.md" in doc

    assert "## Change log" in doc
    assert "Initial profile created (v1)" in doc


def test_build_profile_when_tool_returned_nothing():
    """build_profile must return a valid document structure even with empty facts."""
    doc = build_profile("calc-engine", facts={}, version=1)

    assert "# Application Knowledge: calc-engine" in doc
    assert "## Overview and owner" in doc
    assert "_No overview or owner specified._" in doc
    assert "## Dependencies" in doc
    assert "- **Depends on:** None" in doc
    assert "- **Used by:** None" in doc
    assert "## Known errors" in doc
    assert "_No known errors recorded._" in doc
    assert "## Incident history" in doc
    assert "_No incident history recorded._" in doc
    assert "## Runbook links" in doc
    assert "_No runbooks linked._" in doc
    assert "## Change log" in doc


def test_merge_known_error_adds_updates_and_preserves_rows():
    """merge_known_error adds/updates by code, preserves existing rows, and appends to change log."""
    base_doc = build_profile("orders-db", facts={}, version=1)

    # 1. Add first error
    entry1 = {
        "code": "DB-1205",
        "meaning": "Lock wait timeout",
        "cause": "Row locks",
        "fix": "Kill blocking session",
        "last_seen": "2026-10-06 08:00:00",
        "source": "runbook",
    }
    doc1 = merge_known_error(base_doc, entry1)

    assert "| DB-1205 | Lock wait timeout |" in doc1
    assert "Added known error DB-1205" in doc1

    # 2. Add second error (must not delete first)
    entry2 = {
        "code": "DB-1040",
        "meaning": "Too many connections",
        "cause": "Pool exhausted",
        "fix": "Increase max_connections",
        "last_seen": "2026-10-06 09:00:00",
        "source": "alert",
    }
    doc2 = merge_known_error(doc1, entry2)

    assert "| DB-1205 | Lock wait timeout |" in doc2
    assert "| DB-1040 | Too many connections |" in doc2
    assert "Added known error DB-1040" in doc2

    # 3. Update existing error (DB-1205) with new fix (must not duplicate or delete DB-1040)
    entry1_updated = {
        "code": "DB-1205",
        "meaning": "Lock wait timeout",
        "cause": "Row locks",
        "fix": "Kill blocking session and sort keys before update",
        "last_seen": "2026-10-07 10:00:00",
        "source": "incident-resolution",
    }
    doc3 = merge_known_error(doc2, entry1_updated)

    # Both errors still present
    assert "| DB-1205 |" in doc3
    assert "| DB-1040 |" in doc3
    assert "sort keys before update" in doc3
    # Exactly one row for DB-1205 in the table
    assert doc3.count("| DB-1205 |") == 1
    assert "Updated known error DB-1205" in doc3


def test_merge_known_error_empty_entry():
    """merge_known_error with empty entry returns markdown untouched."""
    doc = build_profile("orders-db")
    res = merge_known_error(doc, {})
    assert res == doc


# ==============================================================================
# 2. Narration Tests
# ==============================================================================

def test_narration_log_analysis_full_and_partial():
    """Test log_analysis narration with full, partial, and empty fields."""
    # Full facts
    delta_full = {
        "log_findings": {
            "stats": {
                "error_count": 14,
                "first_error_time": "2026-10-06 08:00:00",
                "last_error_time": "2026-10-06 08:15:00",
                "error_codes": ["DB-1205"],
            }
        }
    }
    narr_full = narrate("log_analysis", delta=delta_full)
    assert len(narr_full) == 1
    item = narr_full[0]
    assert item["stage"] == "log_analysis"
    assert item["status"] == "completed"
    assert item["title"] == "Log Analysis"
    assert item["detail"] == (
        "I checked the application logs: 14 errors between 2026-10-06 08:00:00 and 2026-10-06 08:15:00; most frequent: DB-1205"
    )

    # Missing timestamps
    delta_no_time = {
        "log_findings": {
            "stats": {
                "error_count": 5,
                "error_codes": ["MQ-2041"],
            }
        }
    }
    narr_no_time = narrate("log_analysis", delta=delta_no_time)
    assert narr_no_time[0]["detail"] == "I checked the application logs: 5 errors; most frequent: MQ-2041"

    # Missing code
    delta_no_code = {
        "log_findings": {
            "stats": {
                "error_count": 3,
                "first_error_time": "10:00",
                "last_error_time": "10:05",
            }
        }
    }
    narr_no_code = narrate("log_analysis", delta=delta_no_code)
    assert narr_no_code[0]["detail"] == "I checked the application logs: 3 errors between 10:00 and 10:05"

    # Tool returned nothing (0 errors / empty)
    narr_empty = narrate("log_analysis", delta={}, state={})
    assert narr_empty[0]["detail"] == "I checked the application logs: no errors detected."


def test_narration_live_status():
    """Test live_status narration with component, status, dependencies, and empty."""
    delta = {
        "live_findings": {
            "component": "calc-engine",
            "status": "CRITICAL",
            "dependencies": [
                {"service": "orders-db", "status": "HEALTHY"},
                {"service": "msg-queue", "status": "DEGRADED"},
            ],
        }
    }
    narr = narrate("live_status", delta=delta)
    assert narr[0]["detail"] == (
        "I checked related systems: calc-engine is CRITICAL; orders-db is HEALTHY; msg-queue is DEGRADED."
    )

    # Tool returned nothing
    narr_empty = narrate("live_status", delta={}, state={})
    assert narr_empty[0]["detail"] == "I checked related systems."


def test_narration_retrieval():
    """Test retrieval narration with matching documents and empty."""
    delta = {
        "kb_docs": [
            {"metadata": {"title": "db-lock.md"}},
            {"metadata": {"title": "INC-101"}},
        ]
    }
    narr = narrate("retrieval", delta=delta)
    assert narr[0]["detail"] == "I searched the knowledge base: 2 relevant documents, best match db-lock.md"

    # Tool returned nothing
    narr_empty = narrate("retrieval", delta={}, state={})
    assert narr_empty[0]["detail"] == "I searched the knowledge base: no relevant documents found."


def test_narration_planner():
    """Test planner narration with root cause, confidence, and empty."""
    delta = {
        "plan": {
            "root_cause": "Long-running report transaction held row locks",
            "confidence": 0.85,
        }
    }
    narr = narrate("planner", delta=delta)
    assert narr[0]["detail"] == "Likely root cause (confidence 0.85): Long-running report transaction held row locks"

    # Tool returned nothing
    narr_empty = narrate("planner", delta={}, state={})
    assert narr_empty[0]["detail"] == "Resolution planning completed."


def test_narration_reviewer():
    """Test reviewer narration with verified claims and issues."""
    state = {
        "plan": {
            "claims": [{"text": "claim 1"}, {"text": "claim 2"}, {"text": "claim 3"}],
        }
    }
    delta_ok = {"review": {"passed": True, "issues": []}}
    narr_ok = narrate("reviewer", delta=delta_ok, state=state)
    assert narr_ok[0]["detail"] == "Verified 3 of 3 claims against their sources"
    assert narr_ok[0]["status"] == "completed"

    delta_issue = {"review": {"passed": False, "issues": ["Invented error code"]}}
    narr_issue = narrate("reviewer", delta=delta_issue, state=state)
    assert narr_issue[0]["detail"] == "Verified 2 of 3 claims against their sources"
    assert narr_issue[0]["status"] == "warning"

    # Tool returned nothing
    narr_empty = narrate("reviewer", delta={}, state={})
    assert narr_empty[0]["detail"] == "Grounding review completed."
