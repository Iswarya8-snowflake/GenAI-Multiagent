"""Approval policy evaluation: determines standard vs strict approval level per PROJECT_SPEC.md."""

from typing import Any, Dict, List


def evaluate_approval_policy(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate human approval policy level: 'strict' or 'standard'.

    Strict triggers (per PROJECT_SPEC.md):
    - Web evidence present (sources must be acknowledged)
    - P1 or P2 severity
    - Confidence below 0.7
    - A retry (loops > 0)
    - Destructive steps flagged
    """
    reasons: List[str] = []

    triage = state.get("triage") or {}
    severity = str(triage.get("severity", "")).upper()
    if severity in {"P1", "P2"}:
        reasons.append(f"High incident severity ({severity})")

    plan = state.get("plan") or {}
    confidence = float(plan.get("confidence", 1.0))
    if confidence < 0.7:
        reasons.append(f"Confidence score ({confidence:.2f}) is below 0.70 threshold")

    loops = int(state.get("loops", 0))
    if loops > 0:
        reasons.append(f"Workflow underwent {loops} retry iteration(s)")

    evidence = state.get("evidence") or []
    for doc in evidence:
        meta = doc.get("metadata") or {}
        source_type = meta.get("source_type", "")
        if source_type in {"web", "external"} or "http" in meta.get("file", ""):
            reasons.append("Plan relies on external web evidence")
            break

    review = state.get("review") or {}
    destructive = review.get("destructive_steps") or []
    if destructive:
        reasons.append(f"Plan contains potentially destructive steps: {destructive}")

    is_strict = len(reasons) > 0
    return {
        "level": "strict" if is_strict else "standard",
        "reasons": reasons,
    }

