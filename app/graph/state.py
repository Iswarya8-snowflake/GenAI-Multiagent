"""State definitions and Pydantic schemas for L3 Incident Copilot graph."""

from typing import Any, Dict, List, Literal, Optional, TypedDict
from pydantic import BaseModel, Field, field_validator


# ==============================================================================
# Pydantic Schemas for Structured Output Validation
# ==============================================================================

class TriageOutput(BaseModel):
    severity: Literal["P1", "P2", "P3", "P4"] = "P2"
    category: str = "system"
    component: Literal["orders-db", "msg-queue", "feed-gateway", "calc-engine"] = "orders-db"
    summary: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, v: Any) -> str:
        s = str(v).upper().strip()
        if s in {"P1", "P2", "P3", "P4"}:
            return s
        if "1" in s: return "P1"
        if "2" in s: return "P2"
        if "3" in s: return "P3"
        if "4" in s: return "P4"
        return "P2"

    @field_validator("component", mode="before")
    @classmethod
    def normalize_component(cls, v: Any) -> str:
        s = str(v).lower().strip()
        valid = {"orders-db", "msg-queue", "feed-gateway", "calc-engine"}
        if s in valid:
            return s
        for item in valid:
            if item in s or s in item:
                return item
        return "orders-db"


class Claim(BaseModel):
    text: str
    source_ids: List[str] = Field(default_factory=list)


class ResolutionPlan(BaseModel):
    root_cause: str
    fix_steps: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8)
    claims: List[Claim] = Field(default_factory=list)
    not_found: List[str] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, v: Any) -> float:
        try:
            val = float(v)
            if 1.0 < val <= 10.0:
                return round(val / 10.0, 2)
            elif 10.0 < val <= 100.0:
                return round(val / 100.0, 2)
            return min(max(val, 0.0), 1.0)
        except Exception:
            return 0.5


# ==============================================================================
# LangGraph Shared State
# ==============================================================================

class IncidentState(TypedDict, total=False):
    incident_text: str
    logs: Optional[str]
    triage: Optional[Dict[str, Any]]
    kb_docs: Optional[List[Dict[str, Any]]]
    log_findings: Optional[Dict[str, Any]]
    live_findings: Optional[Dict[str, Any]]
    evidence: Optional[List[Dict[str, Any]]]
    loops: int
    refined_query: Optional[str]
    plan: Optional[Dict[str, Any]]
    review: Optional[Dict[str, Any]]
    policy: Optional[Dict[str, Any]]
    approved: Optional[bool]
    approval_id: Optional[str]
    ticket: Optional[Dict[str, Any]]
    kb_writeback_result: Optional[Dict[str, Any]]
    status: Optional[str]
    error: Optional[str]
