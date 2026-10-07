"""Log parsing and signature lookup tools."""

import json
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional

LOG_LINE_REGEX = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+([A-Z]+)\s+([a-zA-Z0-9_\-]+)\s+-\s+(?:\[([A-Z0-9_\-]+)\]\s*)?(.*)$"
)
CODE_REGEX = re.compile(r"\b(?:DB|MQ|FEED|JOB)-\d{4}\b|\b[A-Z]{2,5}-\d{4}\b")
DIGITS_REGEX = re.compile(r"\b\d+\b")


def normalize_signature(message: str) -> str:
    """Normalize digits and variable identifiers in error message."""
    # Replace numbers with <N>
    norm = DIGITS_REGEX.sub("<N>", message.strip())
    # Collapse multiple whitespaces
    norm = re.sub(r"\s+", " ", norm)
    return norm


def parse_logs(text: str) -> Dict[str, Any]:
    """
    Parse log text and extract error counts, first/last error times,
    top normalized signatures, error codes, and failing components.
    """
    if not text:
        return {
            "error_count": 0,
            "first_error_time": None,
            "last_error_time": None,
            "top_error_signatures": [],
            "error_codes": [],
            "failing_components": [],
        }

    lines = text.strip().splitlines()
    error_lines = []
    first_error_time = None
    last_error_time = None
    error_codes = set()
    failing_components = set()
    signature_counter = Counter()

    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        match = LOG_LINE_REGEX.match(line_str)
        if match:
            timestamp, level, service, code, message = match.groups()
            is_error = level.upper() in {"ERROR", "CRITICAL", "FATAL"}
            if is_error:
                error_lines.append(line_str)
                if not first_error_time:
                    first_error_time = timestamp
                last_error_time = timestamp
                failing_components.add(service)

                if code:
                    error_codes.add(code)
                else:
                    found_codes = CODE_REGEX.findall(message)
                    error_codes.update(found_codes)

                sig = normalize_signature(message)
                signature_counter[sig] += 1
        else:
            # Fallback if line does not strictly match standard header but has ERROR
            if re.search(r"\b(?:ERROR|CRITICAL|FATAL)\b", line_str, re.IGNORECASE):
                error_lines.append(line_str)
                found_codes = CODE_REGEX.findall(line_str)
                error_codes.update(found_codes)
                sig = normalize_signature(line_str)
                signature_counter[sig] += 1

    top_signatures = [
        {"signature": sig, "count": count}
        for sig, count in signature_counter.most_common(5)
    ]

    return {
        "error_count": len(error_lines),
        "first_error_time": first_error_time,
        "last_error_time": last_error_time,
        "top_error_signatures": top_signatures,
        "error_codes": sorted(list(error_codes)),
        "failing_components": sorted(list(failing_components)),
    }


def lookup_signature(sig: str, incidents_file: str = "data/incidents.json") -> List[Dict[str, Any]]:
    """
    Match an error signature against past incidents in data/incidents.json
    by error codes and keyword overlap.
    """
    if not os.path.exists(incidents_file):
        return []

    with open(incidents_file, "r", encoding="utf-8") as f:
        incidents = json.load(f)

    # Extract target error codes from signature
    target_codes = set(CODE_REGEX.findall(sig))
    # Extract keywords (lowercase words longer than 3 characters, excluding generic stop words)
    words = set(re.findall(r"[a-z]{4,}", sig.lower()))
    stopwords = {"error", "failed", "failure", "with", "from", "that", "this", "have", "been"}
    keywords = words - stopwords

    matches = []
    for inc in incidents:
        text_corp = f"{inc.get('symptom', '')} {inc.get('root_cause', '')} {inc.get('fix', '')}".lower()
        score = 0

        # High weight for error code matches
        for code in target_codes:
            if code.lower() in text_corp or code.lower() in inc.get("id", "").lower():
                score += 10

        # Keyword overlap
        for kw in keywords:
            if kw in text_corp:
                score += 1

        if score > 0:
            matches.append({
                "incident": inc,
                "score": score,
            })

    matches.sort(key=lambda x: x["score"], reverse=True)
    return [m["incident"] for m in matches[:5]]

