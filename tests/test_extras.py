"""Tests for grounding checker, destructive steps, and approval policy."""

from app.graph.grounding import check_grounding
from app.graph.policy import evaluate_approval_policy


SAMPLE_EVIDENCE = [
    {
        "id": "doc-1",
        "text": (
            "Service orders-db emits error DB-1205: lock wait timeout exceeded on orders table. "
            "To diagnose lock contention, run `SHOW INNODB STATUS`. Terminate blocking session."
        ),
    }
]


# ==============================================================================
# Grounding Checker Tests
# ==============================================================================

def test_grounding_accepts_supported_claim():
    plan = {
        "claims": [
            {
                "text": "Service orders-db emits error DB-1205: lock wait timeout exceeded on orders table.",
                "source_ids": ["doc-1"],
            }
        ],
        "fix_steps": ["Terminate blocking session and restart transaction."],
    }
    result = check_grounding(plan, SAMPLE_EVIDENCE)
    assert result["passed"] is True
    assert len(result["issues"]) == 0
    assert len(result["destructive_steps"]) == 0


def test_grounding_rejects_invented_error_code():
    plan = {
        "claims": [
            {
                "text": "orders-db encountered fatal error DB-9999 lock wait timeout exceeded.",
                "source_ids": ["doc-1"],
            }
        ],
        "fix_steps": ["Check logs"],
    }
    result = check_grounding(plan, SAMPLE_EVIDENCE)
    assert result["passed"] is False
    assert any("DB-9999" in issue for issue in result["issues"])


def test_grounding_rejects_missing_or_invalid_citation():
    # Empty citations
    plan_empty = {
        "claims": [
            {
                "text": "Service orders-db emits error DB-1205.",
                "source_ids": [],
            }
        ],
        "fix_steps": ["Check logs"],
    }
    res_empty = check_grounding(plan_empty, SAMPLE_EVIDENCE)
    assert res_empty["passed"] is False
    assert any("no source citations" in issue for issue in res_empty["issues"])

    # Non-existent citation id
    plan_invalid = {
        "claims": [
            {
                "text": "Service orders-db emits error DB-1205.",
                "source_ids": ["doc-999"],
            }
        ],
        "fix_steps": ["Check logs"],
    }
    res_invalid = check_grounding(plan_invalid, SAMPLE_EVIDENCE)
    assert res_invalid["passed"] is False
    assert any("doc-999" in issue for issue in res_invalid["issues"])


def test_grounding_flags_destructive_drop_table():
    plan = {
        "claims": [
            {
                "text": "Service orders-db emits error DB-1205: lock wait timeout exceeded.",
                "source_ids": ["doc-1"],
            }
        ],
        "fix_steps": [
            "DROP TABLE orders_backup;",
            "rm -rf /tmp/data",
            "Restart database service",
        ],
    }
    result = check_grounding(plan, SAMPLE_EVIDENCE)
    assert result["passed"] is False
    assert len(result["destructive_steps"]) >= 2
    assert any("DROP TABLE" in step for step in result["destructive_steps"])
    assert any("rm -rf" in step for step in result["destructive_steps"])


# ==============================================================================
# Approval Policy Tests
# ==============================================================================

def test_policy_strict_for_high_severity():
    state_p1 = {"triage": {"severity": "P1"}, "plan": {"confidence": 0.95}}
    state_p2 = {"triage": {"severity": "P2"}, "plan": {"confidence": 0.95}}

    res_p1 = evaluate_approval_policy(state_p1)
    res_p2 = evaluate_approval_policy(state_p2)

    assert res_p1["level"] == "strict"
    assert any("P1" in r for r in res_p1["reasons"])
    assert res_p2["level"] == "strict"
    assert any("P2" in r for r in res_p2["reasons"])


def test_policy_strict_for_low_confidence():
    state = {
        "triage": {"severity": "P3"},
        "plan": {"confidence": 0.65},
    }
    res = evaluate_approval_policy(state)
    assert res["level"] == "strict"
    assert any("0.70 threshold" in r for r in res["reasons"])


def test_policy_strict_for_retry_loop():
    state = {
        "triage": {"severity": "P3"},
        "plan": {"confidence": 0.85},
        "loops": 1,
    }
    res = evaluate_approval_policy(state)
    assert res["level"] == "strict"
    assert any("retry" in r for r in res["reasons"])


def test_policy_strict_for_web_evidence():
    state = {
        "triage": {"severity": "P3"},
        "plan": {"confidence": 0.85},
        "evidence": [{"metadata": {"source_type": "web"}}],
    }
    res = evaluate_approval_policy(state)
    assert res["level"] == "strict"
    assert any("web evidence" in r for r in res["reasons"])


def test_policy_standard_when_normal():
    state = {
        "triage": {"severity": "P3"},
        "plan": {"confidence": 0.85},
        "loops": 0,
        "evidence": [{"metadata": {"source_type": "kb"}}],
    }
    res = evaluate_approval_policy(state)
    assert res["level"] == "standard"
    assert len(res["reasons"]) == 0

