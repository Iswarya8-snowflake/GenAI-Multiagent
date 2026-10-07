#!/usr/bin/env python3
"""Evaluate knowledge base retrieval hit rate at k=3 against eval/test_set.json."""

import json
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.mcp_server.tools.kb import search_kb


def evaluate_retrieval(test_set_path: str = "eval/test_set.json", k: int = 3):
    if not os.path.exists(test_set_path):
        print(f"Error: Test set file '{test_set_path}' not found.")
        sys.exit(1)

    with open(test_set_path, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    total = len(test_cases)
    hits = 0

    print(f"\n{'='*75}")
    print(f"EVALUATING RETRIEVAL HIT RATE @ {k} ({total} test cases)")
    print(f"{'='*75}\n")

    for idx, tc in enumerate(test_cases, 1):
        tc_id = tc.get("id", f"T-{idx}")
        question = tc.get("question", "")
        expected_cat = tc.get("expected_category", "")
        expected_code = tc.get("expected_error_code", "")

        results = search_kb(query=question, k=k)

        is_hit = False
        retrieved_summary = []

        for rank, r in enumerate(results, 1):
            doc_id = r.get("id", "")
            doc_cat = r.get("metadata", {}).get("category", "")
            doc_text = r.get("text", "")
            doc_score = r.get("score", 0.0)

            # Match criteria: expected category matches or expected error code is found
            matched = (doc_cat == expected_cat) or (expected_code in doc_text)
            if matched:
                is_hit = True

            retrieved_summary.append(
                f"  [{rank}] {doc_id} (cat: {doc_cat}, score: {doc_score:.3f}) - {'HIT' if matched else 'MISS'}"
            )

        if is_hit:
            hits += 1

        status = "PASS" if is_hit else "FAIL"
        print(f"[{tc_id}] {status} | Expected: {expected_cat} / {expected_code}")
        print(f" Query: {question[:70]}...")
        for line in retrieved_summary:
            print(line)
        print("-" * 75)

    hit_rate = (hits / total) * 100 if total > 0 else 0.0
    print(f"\nFinal Results:")
    print(f"Total Test Cases : {total}")
    print(f"Hits @ {k}          : {hits}")
    print(f"Hit Rate @ {k}      : {hit_rate:.1f}% ({hits}/{total})\n")

    return hits, total, hit_rate


if __name__ == "__main__":
    evaluate_retrieval()
