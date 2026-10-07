"""Application knowledge management tools for scanning, reading, and saving application documentation."""

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

from app.mcp_server.tools.tickets import require_approval
from app.mcp_server.tools.kb import kb_upsert

load_dotenv()

APP_KNOWLEDGE_DIR = os.getenv("APP_KNOWLEDGE_DIR", "data/app_knowledge")


def _extract_version(content: str) -> int:
    """Extract version number from markdown header."""
    match = re.search(r"version\s*[:=]\s*(\d+)", content, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 1


def _extract_updated(content: str) -> Optional[str]:
    """Extract updated timestamp from markdown header."""
    match = re.search(r"updated\s*[:=]\s*([^\n\r]+)", content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _ensure_header(markdown: str, service: str, version: int, updated: str) -> str:
    """Ensure header contains version and updated timestamp per PROJECT_SPEC.md."""
    # If version is already specified in markdown, update it
    if re.search(r"(?i)(?:-\s*)?version\s*[:=]", markdown):
        updated_text = re.sub(
            r"(?i)(?:-\s*)?version\s*[:=]\s*\d+",
            f"- Version: {version}",
            markdown,
        )
        if re.search(r"(?i)(?:-\s*)?updated\s*[:=]", updated_text):
            updated_text = re.sub(
                r"(?i)(?:-\s*)?updated\s*[:=]\s*[^\n\r]+",
                f"- Updated: {updated}",
                updated_text,
            )
        else:
            updated_text = re.sub(
                rf"- Version: {version}",
                f"- Version: {version}\n- Updated: {updated}",
                updated_text,
            )
        return updated_text

    # Otherwise prepend standard header
    header = (
        f"# Application Knowledge: {service}\n"
        f"- Version: {version}\n"
        f"- Updated: {updated}\n\n"
    )
    return header + markdown.strip() + "\n"


def _chunk_markdown(text: str, max_chunk_size: int = 800) -> List[str]:
    """Split markdown text into logical chunks by headings and length."""
    sections = re.split(r"(?=(?:\n|^)#{1,3}\s)", text)
    chunks: List[str] = []
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        if len(sec) <= max_chunk_size:
            chunks.append(sec)
        else:
            for i in range(0, len(sec), max_chunk_size):
                sub = sec[i : i + max_chunk_size].strip()
                if sub:
                    chunks.append(sub)
    return chunks or [text]


def get_app_knowledge(service: str, base_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Retrieve application knowledge document and metadata for a given service.

    Args:
        service: Service identifier (e.g. 'calc-engine', 'orders-db').
        base_dir: Optional base directory override.

    Returns:
        Dict with keys: service, path, markdown, version, updated, exists.
    """
    dir_path = base_dir or APP_KNOWLEDGE_DIR
    file_path = os.path.join(dir_path, f"{service}.md")
    if not os.path.exists(file_path):
        return {
            "service": service,
            "path": file_path,
            "markdown": "",
            "version": 0,
            "updated": None,
            "exists": False,
        }

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    return {
        "service": service,
        "path": file_path,
        "markdown": content,
        "version": _extract_version(content),
        "updated": _extract_updated(content),
        "exists": True,
    }


def save_app_knowledge(
    service: str,
    markdown: str,
    approval_id: str,
    base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Save approved application knowledge document for a service.
    Enforces human approval check, increments version, archives previous
    version to history/<service>_v<N>.md, and indexes document chunks into KB.

    Args:
        service: Service identifier.
        markdown: Full markdown document content.
        approval_id: Validated human approval ID.
        base_dir: Optional base directory override.

    Returns:
        Dict with keys: path, version, updated.
    """
    # 1. Enforce approval gate
    require_approval(approval_id)

    dir_path = base_dir or APP_KNOWLEDGE_DIR
    history_dir = os.path.join(dir_path, "history")
    os.makedirs(history_dir, exist_ok=True)

    file_path = os.path.join(dir_path, f"{service}.md")
    now_str = datetime.now(timezone.utc).isoformat()

    # 2. Check for existing version to archive
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            old_content = f.read()

        old_version = _extract_version(old_content)
        existing_history_versions = []
        for fn in os.listdir(history_dir):
            if fn.startswith(f"{service}_v") and fn.endswith(".md"):
                m = re.match(rf"^{re.escape(service)}_v(\d+)\.md$", fn)
                if m:
                    existing_history_versions.append(int(m.group(1)))
        if existing_history_versions:
            old_version = max(old_version, max(existing_history_versions))

        # Archive old version
        history_path = os.path.join(history_dir, f"{service}_v{old_version}.md")
        with open(history_path, "w", encoding="utf-8") as f:
            f.write(old_content)

        new_version = old_version + 1
    else:
        new_version = 1

    # 3. Write new version
    content_to_save = _ensure_header(markdown, service, new_version, now_str)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content_to_save)

    # 4. Add chunks to knowledge base with kb_upsert
    chunks = _chunk_markdown(content_to_save)
    for idx, chunk in enumerate(chunks, 1):
        kb_upsert(
            text=chunk,
            metadata={
                "category": service,
                "component": service,
                "source_type": "app_knowledge",
                "file": file_path,
                "version": new_version,
                "chunk_index": idx,
            },
        )

    return {
        "path": file_path,
        "version": new_version,
        "updated": now_str,
    }

