"""Wiki and runbook keyword search tool."""

import glob
import os
import re
from pathlib import Path
from typing import Any, Dict, List


def search_wiki(query: str, root_dirs: List[str] = None) -> List[Dict[str, Any]]:
    """
    Perform keyword search over runbooks and wiki documents.

    Args:
        query: Search keywords or phrase.
        root_dirs: Directories to scan (defaults to ['data/runbooks', 'data/wiki']).

    Returns:
        List of matching documents with score, title, file path, and snippet.
    """
    if root_dirs is None:
        root_dirs = [os.path.join("data", "runbooks"), os.path.join("data", "wiki")]

    tokens = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
    if not tokens:
        return []

    results = []

    for directory in root_dirs:
        if not os.path.exists(directory):
            continue

        for ext in ("*.md", "*.txt"):
            for file_path in glob.glob(os.path.join(directory, ext)):
                path = Path(file_path)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    continue

                content_lower = content.lower()
                stem = path.stem

                score = 0
                first_match_pos = -1

                for token in tokens:
                    # Higher weight if token appears in file stem/title
                    if token in stem.lower():
                        score += 5
                    # Count occurrences in body
                    matches = list(re.finditer(re.escape(token), content_lower))
                    score += len(matches)
                    if matches and first_match_pos == -1:
                        first_match_pos = matches[0].start()

                if score > 0:
                    # Extract a snippet around the first match
                    start = max(0, first_match_pos - 80)
                    end = min(len(content), first_match_pos + 160)
                    snippet = content[start:end].replace("\n", " ").strip()
                    if start > 0:
                        snippet = "..." + snippet
                    if end < len(content):
                        snippet = snippet + "..."

                    # Extract title from first markdown header if available
                    title = stem
                    first_line = content.strip().splitlines()[0] if content.strip() else ""
                    if first_line.startswith("#"):
                        title = first_line.lstrip("#").strip()

                    results.append({
                        "file": str(path.as_posix()),
                        "title": title,
                        "score": score,
                        "snippet": snippet,
                    })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results
