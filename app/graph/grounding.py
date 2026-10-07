"""Grounding checker: verifies claim citations, error codes, commands, overlap, and destructive steps."""

import re
from typing import Any, Dict, List, Set

ERROR_CODE_REGEX = re.compile(r"\b(?:DB|MQ|FEED|JOB)-\d{4}\b|\b[A-Z]{2,5}-\d{4}\b")
BACKTICK_CMD_REGEX = re.compile(r"`([^`]+)`")

DESTRUCTIVE_PATTERNS = [
    re.compile(r"\bdrop\s+table\b", re.IGNORECASE),
    re.compile(r"\bdrop\s+database\b", re.IGNORECASE),
    re.compile(r"\btruncate\s+table\b", re.IGNORECASE),
    re.compile(r"\btruncate\b", re.IGNORECASE),
    re.compile(r"\bdelete\s+from\b", re.IGNORECASE),
    re.compile(r"\bdelete\b", re.IGNORECASE),
    re.compile(r"\bpurge\b", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bkill\s+-9\b", re.IGNORECASE),
]

STOPWORDS = {
    "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "with",
    "by", "of", "is", "was", "are", "were", "be", "been", "that", "this",
    "it", "from", "as", "has", "have", "had", "will", "would", "can", "could",
}


def tokenize(text: str) -> Set[str]:
    """Extract lowercased word tokens excluding common stopwords."""
    words = re.findall(r"\b[a-zA-Z0-9_\-]{3,}\b", text.lower())
    return {w for w in words if w not in STOPWORDS}


def check_grounding(plan: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate plan grounding against retrieved evidence.

    Checks:
    1. Every claim cites valid, existing evidence IDs.
    2. Any error codes (e.g. DB-1205) in a claim appear in its cited text.
    3. Any backtick commands (e.g. `kill -9`) in a claim appear in its cited text.
    4. Word overlap between claim and cited text is >= 0.3.
    5. Flags destructive steps in fix_steps (drop, delete, truncate, purge, rm -rf, kill -9).

    Returns:
        dict: {"passed": bool, "issues": list[str], "destructive_steps": list[str]}
    """
    issues: List[str] = []
    destructive_steps: List[str] = []

    # Map available evidence IDs to their full text
    evidence_map: Dict[str, str] = {}
    for doc in evidence:
        doc_id = doc.get("id") or doc.get("original_id")
        if doc_id:
            evidence_map[str(doc_id)] = doc.get("text", "")

    claims = plan.get("claims", [])
    if not claims:
        issues.append("Plan contains no claims with citations.")

    for idx, claim in enumerate(claims, start=1):
        claim_text = claim.get("text", "")
        source_ids = claim.get("source_ids", [])

        # 1. Missing citations
        if not source_ids:
            issues.append(f"Claim {idx} has no source citations: '{claim_text}'")
            continue

        # Check existing evidence IDs
        invalid_ids = [sid for sid in source_ids if sid not in evidence_map]
        if invalid_ids:
            issues.append(f"Claim {idx} cites non-existent source IDs: {invalid_ids}")
            continue

        # Aggregate cited text
        cited_text = " ".join(evidence_map[sid] for sid in source_ids)

        # 2. Error codes in claim must appear in cited text
        claim_codes = set(ERROR_CODE_REGEX.findall(claim_text))
        cited_codes = set(ERROR_CODE_REGEX.findall(cited_text))
        missing_codes = claim_codes - cited_codes
        if missing_codes:
            issues.append(f"Claim {idx} cites error codes not in evidence: {list(missing_codes)}")

        # 3. Backtick commands in claim must appear in cited text
        claim_cmds = set(BACKTICK_CMD_REGEX.findall(claim_text))
        for cmd in claim_cmds:
            if cmd.lower() not in cited_text.lower():
                issues.append(f"Claim {idx} cites backtick command/term `{cmd}` not found in evidence.")

        # 4. Word overlap must be >= 0.3
        claim_tokens = tokenize(claim_text)
        cited_tokens = tokenize(cited_text)
        if claim_tokens:
            overlap = len(claim_tokens & cited_tokens) / len(claim_tokens)
            if overlap < 0.3:
                issues.append(
                    f"Claim {idx} has low evidence word overlap ({overlap:.2f} < 0.30): '{claim_text[:60]}...'"
                )

    # 5. Check destructive steps in fix_steps
    fix_steps = plan.get("fix_steps", [])
    for step in fix_steps:
        for pat in DESTRUCTIVE_PATTERNS:
            if pat.search(step):
                destructive_steps.append(step)
                break

    if destructive_steps:
        issues.append(f"Plan includes destructive action steps: {destructive_steps}")

    passed = len(issues) == 0

    return {
        "passed": passed,
        "issues": issues,
        "destructive_steps": destructive_steps,
    }

