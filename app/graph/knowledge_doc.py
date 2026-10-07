"""Application Knowledge Document generator and updater (PROJECT_SPEC.md Portal features).

Builds and updates structured markdown application knowledge profiles:
data/app_knowledge/<service>.md with sections:
- Header (service, version, updated)
- Overview and owner
- Dependencies
- Known errors (code, meaning, cause, fix, last seen, source)
- Incident history
- Runbook links
- Change log
"""

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def build_profile(
    service: str,
    facts: Optional[Dict[str, Any]] = None,
    version: int = 1,
) -> str:
    """
    Build application knowledge markdown profile from extracted facts.
    Built strictly from facts passed in, with no LLM or network.

    Args:
        service: Service identifier ('orders-db', 'msg-queue', 'calc-engine', 'feed-gateway').
        facts: Dictionary of extracted facts (owner, dependencies, known_errors, incident_history, runbooks).
        version: Document version number (default 1).

    Returns:
        Structured markdown string.
    """
    if facts is None:
        facts = {}

    now_iso = datetime.now(timezone.utc).isoformat()

    lines: List[str] = [
        f"# Application Knowledge: {service}",
        f"- Version: {version}",
        f"- Updated: {now_iso}",
        "",
    ]

    # 1. Overview and owner
    lines.append("## Overview and owner")
    owner = facts.get("owner") or facts.get("owner_team")
    overview = facts.get("overview") or facts.get("description")
    if owner:
        lines.append(f"- **Owner Team:** {owner}")
    if overview:
        lines.append(f"- **Description:** {overview}")
    if not owner and not overview:
        lines.append("_No overview or owner specified._")
    lines.append("")

    # 2. Dependencies
    lines.append("## Dependencies")
    deps_raw = facts.get("dependencies")
    depends_on = facts.get("depends_on") or []
    used_by = facts.get("used_by") or []

    if isinstance(deps_raw, dict):
        depends_on = deps_raw.get("depends_on") or depends_on
        used_by = deps_raw.get("used_by") or used_by
    elif isinstance(deps_raw, list) and not depends_on:
        depends_on = deps_raw

    has_deps = bool(depends_on or used_by)
    if depends_on:
        lines.append(f"- **Depends on:** {', '.join(depends_on)}")
    else:
        lines.append("- **Depends on:** None")

    if used_by:
        lines.append(f"- **Used by:** {', '.join(used_by)}")
    else:
        lines.append("- **Used by:** None")

    if not has_deps and not deps_raw:
        lines.append("")
    else:
        lines.append("")

    # 3. Known errors
    lines.append("## Known errors")
    known_errors = facts.get("known_errors") or []
    if known_errors:
        lines.append("| Code | Meaning | Cause | Fix | Last Seen | Source |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for err in known_errors:
            code = err.get("code") or err.get("error_code") or "-"
            meaning = err.get("meaning") or "-"
            cause = err.get("cause") or err.get("root_cause") or "-"
            fix = err.get("fix") or err.get("fix_steps") or "-"
            last_seen = err.get("last_seen") or err.get("last seen") or "-"
            source = err.get("source") or "-"
            lines.append(f"| {code} | {meaning} | {cause} | {fix} | {last_seen} | {source} |")
    else:
        lines.append("_No known errors recorded._")
    lines.append("")

    # 4. Incident history
    lines.append("## Incident history")
    history = facts.get("incident_history") or facts.get("incidents") or []
    if history:
        for inc in history:
            if isinstance(inc, dict):
                inc_id = inc.get("id") or inc.get("incident_id") or "INC"
                sym = inc.get("symptom") or inc.get("summary") or ""
                cause = inc.get("root_cause") or ""
                fix = inc.get("fix") or ""
                line = f"- **{inc_id}**:"
                if sym:
                    line += f" {sym}"
                if cause:
                    line += f" (Cause: {cause})"
                if fix:
                    line += f" [Fix: {fix}]"
                lines.append(line)
            else:
                lines.append(f"- {inc}")
    else:
        lines.append("_No incident history recorded._")
    lines.append("")

    # 5. Runbook links
    lines.append("## Runbook links")
    runbooks = facts.get("runbook_files") or facts.get("runbooks") or facts.get("runbook_links") or []
    if runbooks:
        for rb in runbooks:
            lines.append(f"- {rb}")
    else:
        lines.append("_No runbooks linked._")
    lines.append("")

    # 6. Change log
    lines.append("## Change log")
    change_log = facts.get("change_log") or []
    if change_log:
        for entry in change_log:
            lines.append(f"- {entry}")
    else:
        lines.append(f"- [{now_iso}] Initial profile created (v{version})")
    lines.append("")

    return "\n".join(lines)


def merge_known_error(markdown: str, entry: Dict[str, Any]) -> str:
    """
    Adds or updates a row in the ## Known errors section by error code.
    Never deletes other rows. Appends a change log entry under ## Change log
    and updates the Updated timestamp in the header.

    Args:
        markdown: Existing application knowledge markdown document.
        entry: Dict with error details (code, meaning, cause, fix, last_seen, source).

    Returns:
        Updated markdown string.
    """
    if not entry:
        return markdown

    code = entry.get("code") or entry.get("error_code")
    if not code:
        return markdown

    code_clean = str(code).strip()
    meaning = entry.get("meaning") or "-"
    cause = entry.get("cause") or entry.get("root_cause") or "-"
    fix = entry.get("fix") or entry.get("fix_steps") or "-"
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    last_seen = entry.get("last_seen") or entry.get("last seen") or now_iso
    source = entry.get("source") or "incident"

    new_row = f"| {code_clean} | {meaning} | {cause} | {fix} | {last_seen} | {source} |"

    # 1. Parse Known errors section
    known_section_pattern = r"(## Known errors\n)(.*?)(?=\n## |\Z)"
    match = re.search(known_section_pattern, markdown, re.DOTALL)

    is_update = False
    action_desc = ""

    if match:
        section_header = match.group(1)
        section_body = match.group(2).strip()

        # Extract table rows
        rows = []
        for line in section_body.splitlines():
            line_str = line.strip()
            if line_str.startswith("|") and not re.match(r"^\|\s*--", line_str) and not re.match(r"^\|\s*Code\s*\|", line_str, re.IGNORECASE):
                rows.append(line_str)

        # Search for existing code
        row_updated = False
        new_rows = []
        for r in rows:
            parts = [p.strip() for p in r.split("|")[1:-1]]
            if parts and parts[0].upper() == code_clean.upper():
                new_rows.append(new_row)
                row_updated = True
                is_update = True
            else:
                new_rows.append(r)

        if not row_updated:
            new_rows.append(new_row)
            is_update = False

        # Build replacement table
        table_lines = [
            "| Code | Meaning | Cause | Fix | Last Seen | Source |",
            "| --- | --- | --- | --- | --- | --- |",
        ] + new_rows
        new_section_body = "\n".join(table_lines) + "\n"

        markdown = markdown[:match.start()] + section_header + new_section_body + markdown[match.end():]
    else:
        # If no Known errors section found, append one before Incident history or at end
        table_block = (
            "## Known errors\n"
            "| Code | Meaning | Cause | Fix | Last Seen | Source |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            f"{new_row}\n\n"
        )
        if "## Incident history" in markdown:
            markdown = markdown.replace("## Incident history", table_block + "## Incident history")
        else:
            markdown = markdown + "\n" + table_block

    # 2. Add Change log entry
    action_desc = f"Updated known error {code_clean}" if is_update else f"Added known error {code_clean}"
    change_entry = f"- [{now_iso}] {action_desc}"

    changelog_pattern = r"(## Change log\n)(.*?)(?=\n## |\Z)"
    cl_match = re.search(changelog_pattern, markdown, re.DOTALL)
    if cl_match:
        cl_header = cl_match.group(1)
        cl_body = cl_match.group(2).strip()
        cl_lines = [line for line in cl_body.splitlines() if line.strip()]
        cl_lines.append(change_entry)
        new_cl_body = "\n".join(cl_lines) + "\n"
        markdown = markdown[:cl_match.start()] + cl_header + new_cl_body + markdown[cl_match.end():]
    else:
        markdown = markdown + f"\n## Change log\n{change_entry}\n"

    # 3. Update header timestamp
    now_full_iso = datetime.now(timezone.utc).isoformat()
    if re.search(r"(?i)(?:-\s*)?updated\s*[:=]", markdown):
        markdown = re.sub(
            r"(?i)(?:-\s*)?updated\s*[:=]\s*[^\n\r]+",
            f"- Updated: {now_full_iso}",
            markdown,
        )

    return markdown
