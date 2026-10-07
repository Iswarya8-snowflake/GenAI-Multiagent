#!/usr/bin/env python3
"""Evaluate full multi-agent incident pipeline against eval/test_set.json.

Runs test cases through LangGraph workflow:
1. Triage (LLM structured classification)
2. Parallel Investigation: Retrieval (KB search), Log Analysis, Live Status
3. Join & Unified Evidence Aggregation
4. Planner (LLM structured plan with cited claims)
5. Reviewer (deterministic evidence grounding & safety check)

Reports:
- Retrieval Hit Rate (expected category / error code found in retrieved KB documents)
- Share of Plans Passing Grounding Check (citations valid, error codes grounded, no destructive steps)
- Time per Incident (latency per test case, average, min, max, total elapsed)
"""

import argparse
import json
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.graph.graph import app as graph_app
from app.graph.grounding import check_grounding

load_dotenv()


def evaluate_pipeline(
    test_set_path: str = "eval/test_set.json",
    limit: Optional[int] = None,
    output_path: Optional[str] = "eval/eval_results.json",
    auto_approve: bool = False,
) -> Dict[str, Any]:
    """Run test cases through the multi-agent incident pipeline and report metrics."""
    if not os.path.exists(test_set_path):
        print(f"Error: Test set file '{test_set_path}' not found.")
        sys.exit(1)

    with open(test_set_path, "r", encoding="utf-8") as f:
        all_cases = json.load(f)

    test_cases = all_cases[:limit] if limit is not None else all_cases
    total_cases = len(test_cases)

    print(f"\n{'='*80}")
    print(" L3 INCIDENT COPILOT - MULTI-AGENT PIPELINE EVALUATION")
    print(f"{'='*80}")
    print(f"Test Set File : {test_set_path}")
    print(f"Total Cases   : {total_cases} (Limit: {limit or 'None'})")
    print(f"Auto-Approve  : {auto_approve}")
    print(f"{'='*80}\n")

    results: List[Dict[str, Any]] = []
    retrieval_hits = 0
    grounding_passes = 0
    total_time = 0.0

    for idx, tc in enumerate(test_cases, 1):
        tc_id = tc.get("id", f"TEST-{idx:02d}")
        question = tc.get("question", "")
        expected_cat = tc.get("expected_category", "")
        expected_code = tc.get("expected_error_code", "")

        print(f"[{idx}/{total_cases}] Evaluating {tc_id}...")
        print(f"  Query        : {question[:75]}...")
        print(f"  Expected     : Category='{expected_cat}', ErrorCode='{expected_code}'")

        thread_id = f"eval-{tc_id.lower()}-{uuid.uuid4().hex[:6]}"
        config = {"configurable": {"thread_id": thread_id}}
        initial_state = {
            "incident_text": question,
            "loops": 0,
            "mode": "investigate",
        }

        t_start = time.time()
        last_triage: Dict[str, Any] = {}
        last_kb_docs: List[Dict[str, Any]] = []
        last_plan: Dict[str, Any] = {}
        last_review: Dict[str, Any] = {}
        last_evidence: List[Dict[str, Any]] = []

        try:
            for event in graph_app.stream(initial_state, config, stream_mode="updates"):
                for node_name, update in event.items():
                    if node_name == "triage":
                        last_triage = update.get("triage", {})
                    elif node_name == "retrieval":
                        last_kb_docs = update.get("kb_docs", [])
                    elif node_name == "join":
                        last_evidence = update.get("evidence", [])
                    elif node_name == "planner":
                        last_plan = update.get("plan", {})
                    elif node_name == "reviewer":
                        last_review = update.get("review", {})

            # Inspect post-interrupt state
            post_state = graph_app.get_state(config)
            st_vals = post_state.values if post_state else {}
            if not last_kb_docs:
                last_kb_docs = st_vals.get("kb_docs", [])
            if not last_plan:
                last_plan = st_vals.get("plan", {})
            if not last_review:
                last_review = st_vals.get("review", {})
            if not last_evidence:
                last_evidence = st_vals.get("evidence", [])
            if not last_triage:
                last_triage = st_vals.get("triage", {})

            # If auto-approve is requested and graph paused at interrupt
            if auto_approve and post_state.tasks and any(t.interrupts for t in post_state.tasks):
                from langgraph.types import Command
                from app.mcp_server.tools.tickets import record_approval

                appr = record_approval(
                    incident_id=thread_id,
                    approver="evaluator",
                    decision="APPROVED",
                    reason="Auto-approved evaluation run",
                )
                appr_id = appr.get("approval_id")
                resume_cmd = Command(resume={"approved": True, "approval_id": appr_id})
                for _ in graph_app.stream(resume_cmd, config, stream_mode="updates"):
                    pass

        except Exception as e:
            print(f"  [ERROR] Workflow failed: {e}")

        t_elapsed = time.time() - t_start
        total_time += t_elapsed

        # 1. Evaluate Retrieval Hit
        is_hit = False
        hit_docs = []
        for doc in last_kb_docs:
            doc_id = doc.get("id", "")
            doc_cat = doc.get("metadata", {}).get("category", "")
            doc_text = doc.get("text", "")
            matched = (doc_cat == expected_cat) or (expected_code in doc_text)
            if matched:
                is_hit = True
                hit_docs.append(f"{doc_id} ({doc_cat})")

        if is_hit:
            retrieval_hits += 1

        # 2. Evaluate Grounding Check
        # Reviewer result or fallback verification
        grounding_passed = bool(last_review.get("passed", False))
        if not last_review and last_plan and last_evidence:
            direct_check = check_grounding(last_plan, last_evidence)
            grounding_passed = bool(direct_check.get("passed", False))
            last_review = direct_check

        if grounding_passed:
            grounding_passes += 1

        issues = last_review.get("issues", [])
        confidence = last_plan.get("confidence", 0.0)
        claims_count = len(last_plan.get("claims", []))

        print(f"  -> Triage    : Component='{last_triage.get('component')}', Severity='{last_triage.get('severity')}'")
        print(f"  -> Retrieval : {'HIT' if is_hit else 'MISS'} ({len(last_kb_docs)} docs retrieved; hits: {hit_docs or 'none'})")
        print(f"  -> Planner   : Confidence={confidence:.2f}, Claims={claims_count}")
        print(f"  -> Grounding : {'PASSED' if grounding_passed else 'FAILED'} (Issues: {issues or 'none'})")
        print(f"  -> Time      : {t_elapsed:.2f}s")
        print("-" * 80)

        results.append({
            "id": tc_id,
            "question": question,
            "expected_category": expected_cat,
            "expected_error_code": expected_code,
            "triage": last_triage,
            "retrieval_hit": is_hit,
            "retrieved_docs_count": len(last_kb_docs),
            "hit_docs": hit_docs,
            "planner_confidence": confidence,
            "claims_count": claims_count,
            "grounding_passed": grounding_passed,
            "grounding_issues": issues,
            "time_seconds": round(t_elapsed, 2),
        })

    # Summary calculations
    hit_rate = (retrieval_hits / total_cases) * 100 if total_cases > 0 else 0.0
    grounding_pass_rate = (grounding_passes / total_cases) * 100 if total_cases > 0 else 0.0
    avg_time = (total_time / total_cases) if total_cases > 0 else 0.0
    times = [r["time_seconds"] for r in results] if results else [0.0]
    min_time = min(times)
    max_time = max(times)

    print(f"\n{'='*80}")
    print(" EVALUATION SUMMARY RESULTS")
    print(f"{'='*80}")
    print(f"Total Incidents Evaluated   : {total_cases}")
    print(f"Retrieval Hits @ 3          : {retrieval_hits}/{total_cases} ({hit_rate:.1f}%)")
    print(f"Grounding Check Pass Rate   : {grounding_passes}/{total_cases} ({grounding_pass_rate:.1f}%)")
    print(f"Total Pipeline Runtime      : {total_time:.2f} seconds ({total_time / 60:.2f} minutes)")
    print(f"Average Time per Incident   : {avg_time:.2f} seconds")
    print(f"Min / Max Incident Time     : {min_time:.2f}s / {max_time:.2f}s")
    print(f"{'='*80}\n")

    # Table breakdown
    print(f"{'ID':<9} | {'Category':<15} | {'Code':<10} | {'Retrieval':<10} | {'Grounding':<10} | {'Time (s)':<8}")
    print(f"{'-'*75}")
    for r in results:
        r_str = "HIT" if r["retrieval_hit"] else "MISS"
        g_str = "PASS" if r["grounding_passed"] else "FAIL"
        print(f"{r['id']:<9} | {r['expected_category']:<15} | {r['expected_error_code']:<10} | {r_str:<10} | {g_str:<10} | {r['time_seconds']:<8.2f}")
    print(f"{'-'*75}\n")

    summary_data = {
        "total_cases": total_cases,
        "retrieval_hits": retrieval_hits,
        "retrieval_hit_rate_percent": round(hit_rate, 2),
        "grounding_passes": grounding_passes,
        "grounding_pass_rate_percent": round(grounding_pass_rate, 2),
        "average_time_seconds": round(avg_time, 2),
        "min_time_seconds": round(min_time, 2),
        "max_time_seconds": round(max_time, 2),
        "total_time_seconds": round(total_time, 2),
        "details": results,
    }

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)
        print(f"Saved evaluation metrics to '{output_path}'.\n")

    return summary_data


def main():
    parser = argparse.ArgumentParser(description="Evaluate L3 Incident Copilot Pipeline")
    parser.add_argument("--test-set", type=str, default="eval/test_set.json", help="Path to test set JSON")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of cases to evaluate (e.g. 3)")
    parser.add_argument("--output", type=str, default="eval/eval_results.json", help="Output path for eval JSON results")
    parser.add_argument("--auto-approve", action="store_true", help="Auto-approve plans through ticketing and KB writeback")
    args = parser.parse_args()

    evaluate_pipeline(
        test_set_path=args.test_set,
        limit=args.limit,
        output_path=args.output,
        auto_approve=args.auto_approve,
    )


if __name__ == "__main__":
    main()

