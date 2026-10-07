"""Streamlit User Interface for L3 Incident Copilot per PROJECT_SPEC.md.

Talks exclusively to the FastAPI backend using httpx.
Features:
- Incident text input and optional log file upload
- Dual modes: Investigate an error vs Scan an application
- Live panel displaying agent steps from SSE stream with live data as_of time
- Resolution plan with claims and colored source labels (KB, ticket, log, live, web)
- Reviewer grounding result and approval policy reasons
- Human approval actions: Approve, Edit and approve, Reject
- Strict mode required "I checked the sources" acknowledgement checkbox
- Sidebar simulator scenario injection via FastAPI
- Knowledge Library and Tickets views
"""

import json
import os
import time
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Tuple

import httpx
import streamlit as st

# ==============================================================================
# Configuration & Constants
# ==============================================================================

st.set_page_config(
    page_title="L3 Incident Copilot",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded",
)

DEFAULT_API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_API_KEY = os.getenv("API_KEY", "")

SOURCE_BADGES = {
    "KB": {"label": "KB", "color": "#2e7d32", "icon": "📚"},
    "ticket": {"label": "Ticket", "color": "#1565c0", "icon": "🎫"},
    "log": {"label": "Log", "color": "#e65100", "icon": "📜"},
    "live": {"label": "Live", "color": "#c62828", "icon": "🔴"},
    "web": {"label": "Web", "color": "#6a1b9a", "icon": "🌐"},
}


# ==============================================================================
# FastAPI Client Helpers (httpx only)
# ==============================================================================

def get_api_url() -> str:
    return st.session_state.get("api_base_url", DEFAULT_API_BASE_URL).rstrip("/")


def get_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = st.session_state.get("api_key", DEFAULT_API_KEY)
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def check_backend_health() -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Check connectivity to FastAPI backend."""
    try:
        url = f"{get_api_url()}/health"
        resp = httpx.get(url, timeout=3.0)
        if resp.status_code == 200:
            return True, resp.json()
        return False, None
    except Exception:
        return False, None


def inject_simulator_scenario(scenario_name: str) -> Tuple[bool, str]:
    """Trigger simulator scenario through FastAPI backend."""
    try:
        url = f"{get_api_url()}/scenario/{scenario_name}"
        resp = httpx.post(url, headers=get_headers(), timeout=6.0)
        if resp.status_code == 200:
            data = resp.json()
            return True, data.get("message", f"Scenario '{scenario_name}' injected successfully")
        return False, f"Failed ({resp.status_code}): {resp.text}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


def post_incident(
    text: str,
    logs: Optional[str] = None,
    mode: str = "investigate",
    service: Optional[str] = None,
) -> Tuple[bool, Any]:
    """Submit a new incident investigation or scan to FastAPI."""
    try:
        url = f"{get_api_url()}/incidents"
        payload = {
            "incident_text": text,
            "logs": logs,
            "mode": mode,
            "service": service,
        }
        resp = httpx.post(url, json=payload, headers=get_headers(), timeout=10.0)
        if resp.status_code == 202:
            return True, resp.json()
        return False, resp.json().get("detail", resp.text)
    except Exception as e:
        return False, str(e)


def fetch_incident(incident_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve complete incident status and details."""
    try:
        url = f"{get_api_url()}/incidents/{incident_id}"
        resp = httpx.get(url, headers=get_headers(), timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def post_approval(
    incident_id: str,
    approved: bool,
    acknowledged_sources: Optional[List[str]] = None,
    edits: Optional[Any] = None,
    reason: Optional[str] = None,
) -> Tuple[bool, str]:
    """Submit human approval decision to FastAPI."""
    try:
        url = f"{get_api_url()}/incidents/{incident_id}/approval"
        payload = {
            "approved": approved,
            "acknowledged_sources": acknowledged_sources,
            "edits": edits,
            "reason": reason,
        }
        resp = httpx.post(url, json=payload, headers=get_headers(), timeout=10.0)
        if resp.status_code == 200:
            return True, "Approval decision recorded successfully."
        err_msg = resp.json().get("detail", resp.text)
        return False, err_msg
    except Exception as e:
        return False, str(e)


def fetch_knowledge_profiles() -> List[Dict[str, Any]]:
    """Fetch saved application knowledge profiles."""
    try:
        url = f"{get_api_url()}/knowledge"
        resp = httpx.get(url, headers=get_headers(), timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


def fetch_tickets() -> List[Dict[str, Any]]:
    """Fetch tickets from FastAPI."""
    try:
        url = f"{get_api_url()}/tickets"
        resp = httpx.get(url, headers=get_headers(), timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


def stream_sse_events(incident_id: str) -> Generator[Tuple[str, Any], None, None]:
    """
    Stream Server-Sent Events from FastAPI /incidents/{id}/events.
    Yields (event_name, parsed_data) tuples.
    """
    url = f"{get_api_url()}/incidents/{incident_id}/events"
    try:
        with httpx.stream("GET", url, headers=get_headers(), timeout=120.0) as response:
            if response.status_code != 200:
                yield "error", {"error": f"Failed to stream events (HTTP {response.status_code})"}
                return

            current_event = "message"
            data_lines = []

            for line in response.iter_lines():
                line = line.strip()
                if not line:
                    if data_lines:
                        raw_data = "\n".join(data_lines)
                        try:
                            parsed_data = json.loads(raw_data)
                        except Exception:
                            parsed_data = raw_data
                        yield current_event, parsed_data
                        data_lines = []
                        current_event = "message"
                    continue

                if line.startswith("event:"):
                    current_event = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:") :].strip())
                elif line.startswith(":"):
                    # SSE comment / ping
                    continue
    except Exception as e:
        yield "error", {"error": f"Streaming connection closed: {str(e)}"}


# ==============================================================================
# UI Helper Functions
# ==============================================================================

def classify_source_type(source_id: str, evidence: List[Dict[str, Any]]) -> str:
    """Classify a source id into KB, ticket, log, live, or web."""
    sid_clean = str(source_id).strip().lower()
    for item in evidence:
        item_id = str(item.get("id", "")).lower()
        orig_id = str(item.get("original_id", "")).lower()
        if sid_clean == item_id or sid_clean == orig_id:
            stype = str(item.get("source_type", "")).lower()
            meta_type = str(item.get("metadata", {}).get("source_type", "")).lower()
            combined = f"{stype} {meta_type}"
            if "web" in combined:
                return "web"
            if "ticket" in combined:
                return "ticket"
            if "log" in combined:
                return "log"
            if "live" in combined or "monitor" in combined or "alert" in combined:
                return "live"
            return "KB"

    if "web" in sid_clean:
        return "web"
    if "ticket" in sid_clean or "tck" in sid_clean:
        return "ticket"
    if "log" in sid_clean:
        return "log"
    if "live" in sid_clean or "alert" in sid_clean or "monitor" in sid:
        return "live"
    return "KB"


def render_source_badge(source_type: str, source_id: str) -> str:
    """Render HTML badge for evidence source."""
    cfg = SOURCE_BADGES.get(source_type, SOURCE_BADGES["KB"])
    return (
        f"<span style='background-color:{cfg['color']}; color:white; "
        f"padding:2px 8px; border-radius:12px; font-size:11px; font-weight:600; "
        f"margin-right:4px; display:inline-block;'>"
        f"{cfg['icon']} {cfg['label']}: {source_id}</span>"
    )


# ==============================================================================
# Session State Initialization
# ==============================================================================

if "api_base_url" not in st.session_state:
    st.session_state.api_base_url = DEFAULT_API_BASE_URL
if "api_key" not in st.session_state:
    st.session_state.api_key = DEFAULT_API_KEY
if "active_incident_id" not in st.session_state:
    st.session_state.active_incident_id = None
if "incident_data" not in st.session_state:
    st.session_state.incident_data = None
if "events_log" not in st.session_state:
    st.session_state.events_log = []
if "findings_log" not in st.session_state:
    st.session_state.findings_log = []
if "live_as_of" not in st.session_state:
    st.session_state.live_as_of = None
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False


# ==============================================================================
# Sidebar: Scenarios & Backend Settings
# ==============================================================================

with st.sidebar:
    st.title("🎛️ Control Center")

    # 1. Simulator Scenarios Injection
    st.subheader("🧪 Monitoring Simulator")
    st.caption("Inject metric anomalies and errors into simulated services.")

    scenarios = {
        "db_lock": "orders-db Lock Wait (DB-1205)",
        "queue_backlog": "msg-queue Lag (MQ-2041)",
        "cpu_spike": "calc-engine CPU Spike (JOB-5003)",
        "batch_failure": "calc-engine Batch Failure (JOB-5003)",
        "reset": "Reset Baseline (Healthy)",
    }

    selected_scenario = st.selectbox(
        "Choose Scenario",
        options=list(scenarios.keys()),
        format_func=lambda s: scenarios[s],
    )

    if st.button("⚡ Inject Simulator Scenario", use_container_width=True):
        with st.spinner("Injecting scenario..."):
            ok, msg = inject_simulator_scenario(selected_scenario)
            if ok:
                st.success(f"Injected: {selected_scenario}")
            else:
                st.error(msg)

    st.markdown("---")

    # 2. Backend Health Status
    st.subheader("📡 Backend Status")
    is_up, health_info = check_backend_health()
    if is_up and health_info:
        st.success("🟢 FastAPI Backend Online")
        st.caption(f"Max Concurrent Runs: {health_info.get('max_concurrent_runs')}")
        services = health_info.get("services", {})
        st.caption(f"Monitoring: `{services.get('monitoring_url')}`")
        st.caption(f"MCP Server: `{services.get('mcp_url')}`")
    else:
        st.error("🔴 FastAPI Backend Unreachable")
        st.caption(f"Ensure server is running on `{get_api_url()}`")

    st.markdown("---")

    # 3. Connection Settings
    with st.expander("⚙️ Connection Settings"):
        st.session_state.api_base_url = st.text_input(
            "FastAPI Base URL",
            value=st.session_state.api_base_url,
        )
        st.session_state.api_key = st.text_input(
            "API Key (X-API-Key)",
            value=st.session_state.api_key,
            type="password",
        )

    # 4. Active Incident Reset
    if st.session_state.active_incident_id:
        st.markdown("---")
        if st.button("🔄 Clear Active Investigation", use_container_width=True):
            st.session_state.active_incident_id = None
            st.session_state.incident_data = None
            st.session_state.events_log = []
            st.session_state.findings_log = []
            st.session_state.live_as_of = None
            st.session_state.edit_mode = False
            st.rerun()


# ==============================================================================
# Main Navigation Tabs
# ==============================================================================

tabs = st.tabs(["🚨 Incident Copilot", "📚 Knowledge Library", "🎫 Support Tickets"])

# ==============================================================================
# TAB 1: Incident Copilot (Main Workflow)
# ==============================================================================

with tabs[0]:
    st.header("🚨 L3 Incident Triage & Resolution Copilot")

    # --------------------------------------------------------------------------
    # Incident Input Section (when no incident is active or to start a new one)
    # --------------------------------------------------------------------------
    with st.container():
        st.subheader("1. Start Workflow")
        workflow_mode = st.radio(
            "Workflow Mode",
            ["Investigate an error", "Scan an application"],
            horizontal=True,
            help="Investigate an error diagnoses logs/errors. Scan an application gathers system profile facts.",
        )

        col_input, col_meta = st.columns([2, 1])

        if workflow_mode == "Investigate an error":
            with col_input:
                incident_text = st.text_area(
                    "Incident Description / Error Report",
                    placeholder="e.g. orders-db lock wait timeout reported with DB-1205 while processing checkout transactions",
                    height=100,
                )
            with col_meta:
                uploaded_log = st.file_uploader(
                    "Upload Logs (Optional)",
                    type=["log", "txt"],
                    help="Upload raw error logs to complement the incident description.",
                )
            chosen_service = None
        else:
            with col_input:
                chosen_service = st.selectbox(
                    "Target Application / Component",
                    ["orders-db", "msg-queue", "feed-gateway", "calc-engine"],
                )
                incident_text = f"Application profile scan for {chosen_service}"
            with col_meta:
                st.info(
                    "💡 Application Scan runs log tailing, live dependency checks, ticket retrieval, "
                    "and builds a draft profile for human review without requiring an error."
                )
                uploaded_log = None

        col_submit, col_space = st.columns([1, 3])
        with col_submit:
            start_btn = st.button("🚀 Start Investigation", type="primary", use_container_width=True)

    # --------------------------------------------------------------------------
    # Trigger Investigation / Scan
    # --------------------------------------------------------------------------
    if start_btn:
        if not incident_text.strip():
            st.error("Please provide an incident description or select a service.")
        else:
            log_content = None
            if uploaded_log is not None:
                log_content = uploaded_log.read().decode("utf-8", errors="replace")

            mode_val = "scan" if workflow_mode == "Scan an application" else "investigate"
            with st.spinner("Submitting to FastAPI backend..."):
                ok, res = post_incident(
                    text=incident_text.strip(),
                    logs=log_content,
                    mode=mode_val,
                    service=chosen_service,
                )
                if ok:
                    st.session_state.active_incident_id = res["incident_id"]
                    st.session_state.incident_data = None
                    st.session_state.events_log = []
                    st.session_state.findings_log = []
                    st.session_state.live_as_of = None
                    st.session_state.edit_mode = False
                    st.success(f"Started investigation: `{res['incident_id']}`")
                    st.rerun()
                else:
                    st.error(f"Failed to start workflow: {res}")

    # --------------------------------------------------------------------------
    # Active Workflow Monitoring & Decision Panels
    # --------------------------------------------------------------------------
    active_id = st.session_state.active_incident_id

    if active_id:
        st.markdown("---")
        st.subheader(f"2. Active Workflow: `{active_id}`")

        # Container placeholders for live stream updates
        col_live, col_results = st.columns([1, 1])

        # Left Column: Live Agent Steps Panel (SSE stream)
        with col_live:
            st.markdown("### 📡 Live Agent Steps & Monitoring")
            live_as_of_ph = st.empty()
            steps_container = st.container(height=480)

        # Right Column: Plan, Reviewer, and Approval Gate
        with col_results:
            st.markdown("### 📋 Findings & Resolution")
            plan_container = st.container(height=480)

        # Bottom Action Container: Approval & Ticketing Gate
        approval_box = st.container()

        # ----------------------------------------------------------------------
        # Fetch or Stream Event Updates
        # ----------------------------------------------------------------------
        incident = fetch_incident(active_id)
        if incident:
            st.session_state.incident_data = incident

        # If waiting approval, escalating, or resolved, show current state; otherwise stream
        curr_status = incident.get("status") if incident else "queued"

        if curr_status in ("queued", "investigating", "scanning", "resuming"):
            # Stream events live
            with st.spinner(f"Agents executing ({curr_status})..."):
                for ev_name, ev_data in stream_sse_events(active_id):
                    st.session_state.events_log.append({"event": ev_name, "data": ev_data})

                    # Handle finding events
                    if ev_name == "finding" and isinstance(ev_data, dict):
                        st.session_state.findings_log.append(ev_data)

                    # Capture as_of from live status updates
                    if ev_name == "agent_step" and isinstance(ev_data, dict):
                        update = ev_data.get("update", {})
                        lf = update.get("live_findings", {})
                        if lf.get("as_of"):
                            st.session_state.live_as_of = lf.get("as_of")

                    # If reached approval_required or done, break stream and refresh
                    if ev_name in ("approval_required", "done", "error"):
                        st.session_state.incident_data = fetch_incident(active_id)
                        st.rerun()
                        break

        # ----------------------------------------------------------------------
        # Render Live Steps Panel
        # ----------------------------------------------------------------------
        inc_data = st.session_state.incident_data or {}
        evidence = inc_data.get("evidence") or []

        # Update Live Data as_of display
        as_of_val = st.session_state.live_as_of
        if not as_of_val and inc_data.get("state", {}).get("live_findings", {}).get("as_of"):
            as_of_val = inc_data["state"]["live_findings"]["as_of"]

        with live_as_of_ph:
            if as_of_val:
                st.caption(f"⏱️ **Live data as_of:** `{as_of_val}`")
            else:
                st.caption("⏱️ **Live data as_of:** Connecting to monitoring simulator...")

        with steps_container:
            # Render deterministic findings
            if st.session_state.findings_log:
                for idx, f in enumerate(st.session_state.findings_log):
                    stage = f.get("stage", "")
                    title = f.get("title", stage.title())
                    detail = f.get("detail", "")
                    status_val = f.get("status", "completed")

                    icon = "🔍"
                    if "log" in stage:
                        icon = "📜"
                    elif "live" in stage:
                        icon = "🩺"
                    elif "retriev" in stage:
                        icon = "📚"
                    elif "plan" in stage:
                        icon = "📝"
                    elif "review" in stage:
                        icon = "🛡️"
                    elif "approval" in stage:
                        icon = "⏳"
                    elif "ticket" in stage:
                        icon = "🎫"
                    elif "knowledge" in stage:
                        icon = "📄"

                    st.markdown(f"**{icon} {title}**")
                    st.info(detail)
            else:
                st.caption("Listening for agent execution updates...")

        # ----------------------------------------------------------------------
        # Render Plan, Reviewer & Evidence Panel
        # ----------------------------------------------------------------------
        with plan_container:
            plan = inc_data.get("plan")
            review = inc_data.get("review")
            policy = inc_data.get("policy") or inc_data.get("pending_approval", {}).get("policy")
            draft_md = inc_data.get("knowledge_draft")

            # 1. Triage Summary (if present)
            triage = inc_data.get("triage")
            if triage:
                st.markdown(
                    f"**Triage:** Severity `{triage.get('severity')}` | "
                    f"Component `{triage.get('component')}` | "
                    f"Category `{triage.get('category')}`"
                )

            # 2. Plan Display
            if plan:
                st.markdown("#### 🎯 Plan & Root Cause")
                rc = plan.get("root_cause", "Unspecified")
                conf = plan.get("confidence", 0.0)
                st.markdown(f"**Likely Root Cause:** {rc}")
                st.progress(min(max(conf, 0.0), 1.0), text=f"Confidence: {int(conf * 100)}%")

                # Fix Steps
                fix_steps = plan.get("fix_steps", [])
                if fix_steps:
                    st.markdown("**Proposed Fix Steps:**")
                    for i, step in enumerate(fix_steps, start=1):
                        st.markdown(f"{i}. {step}")

                # Claims and Evidence Badges
                claims = plan.get("claims", [])
                if claims:
                    st.markdown("**Claims & Grounded Sources:**")
                    for claim in claims:
                        c_text = claim.get("text", "")
                        source_ids = claim.get("source_ids", [])

                        badges_html = ""
                        for sid in source_ids:
                            stype = classify_source_type(sid, evidence)
                            badges_html += render_source_badge(stype, sid)

                        st.markdown(
                            f"• {c_text}<br/>&nbsp;&nbsp;Sources: {badges_html if badges_html else '*(No sources cited)*'}",
                            unsafe_allow_html=True,
                        )

                # Unresolved / Not Found
                not_found = plan.get("not_found", [])
                if not_found:
                    st.warning(f"⚠️ Unresolved points: {'; '.join(not_found)}")

            # 3. Reviewer Result & Policy Reasons
            if review:
                st.markdown("---")
                st.markdown("#### 🛡️ Grounding Reviewer")
                passed = review.get("passed", False)
                if passed:
                    st.success("✅ Grounding Review: PASSED (All claims verified against citations)")
                else:
                    st.error("❌ Grounding Review: FAILED")
                    issues = review.get("issues", [])
                    for iss in issues:
                        st.markdown(f"- ⚠️ {iss}")

            if policy:
                level = str(policy.get("level", "standard")).upper()
                reasons = policy.get("reasons", [])
                st.markdown("#### ⚖️ Approval Policy")
                if level == "STRICT":
                    st.warning(f"🚨 **Policy Level:** `STRICT`")
                else:
                    st.info(f"ℹ️ **Policy Level:** `STANDARD`")

                if reasons:
                    st.markdown("**Policy Reasons:**")
                    for r in reasons:
                        st.markdown(f"- {r}")

            # 4. Application Knowledge Draft (if scan or draft present)
            if draft_md:
                st.markdown("---")
                with st.expander("📄 Application Knowledge Document Draft", expanded=False):
                    st.markdown(draft_md)

        # ----------------------------------------------------------------------
        # Approval Gate Controls
        # ----------------------------------------------------------------------
        with approval_box:
            st.markdown("---")
            pending = inc_data.get("pending_approval")
            status_val = inc_data.get("status")

            if status_val == "waiting_approval" and pending:
                st.subheader("3. ✍️ Human Approval Decision Required")

                policy_obj = pending.get("policy", {})
                is_strict = str(policy_obj.get("level", "standard")).lower() == "strict"

                # Strict mode acknowledgment checkbox
                ack_checked = False
                if is_strict:
                    st.error(
                        "🔒 **STRICT POLICY ACTIVE**: This action requires human verification of all cited evidence sources."
                    )
                    ack_checked = st.checkbox(
                        "I checked the sources and confirmed evidence citations are accurate.",
                        value=False,
                        key="strict_ack_checkbox",
                    )
                else:
                    ack_checked = True

                # Extract acknowledged sources
                all_source_ids = [doc.get("id") for doc in evidence if doc.get("id")]
                if not all_source_ids:
                    all_source_ids = ["doc-1"]

                # Action buttons
                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])

                with col_btn1:
                    approve_disabled = is_strict and not ack_checked
                    if st.button(
                        "✅ Approve Resolution",
                        type="primary",
                        disabled=approve_disabled,
                        use_container_width=True,
                    ):
                        with st.spinner("Recording approval and resuming workflow..."):
                            ok, msg = post_approval(
                                incident_id=active_id,
                                approved=True,
                                acknowledged_sources=all_source_ids if is_strict else None,
                            )
                            if ok:
                                st.success("Approved! Resuming graph execution...")
                                st.rerun()
                            else:
                                st.error(msg)

                with col_btn2:
                    if st.button("✏️ Edit and Approve", use_container_width=True):
                        st.session_state.edit_mode = not st.session_state.edit_mode

                with col_btn3:
                    reject_btn = st.button("❌ Reject Plan", use_container_width=True)

                # Edit and approve expanded form
                if st.session_state.edit_mode:
                    st.markdown("#### ✏️ Modify Plan Before Approval")
                    edit_rc = st.text_input(
                        "Edited Root Cause",
                        value=plan.get("root_cause", "") if plan else "",
                    )
                    edit_steps_raw = st.text_area(
                        "Edited Fix Steps (one per line)",
                        value="\n".join(plan.get("fix_steps", [])) if plan else "",
                    )
                    edit_reason = st.text_input("Approval Comment / Operator Note", value="Operator adjusted fix steps")

                    if st.button(
                        "🚀 Submit Approved Edits",
                        type="primary",
                        disabled=(is_strict and not ack_checked),
                    ):
                        steps_list = [s.strip() for s in edit_steps_raw.split("\n") if s.strip()]
                        edits_payload = {"root_cause": edit_rc, "fix_steps": steps_list}
                        with st.spinner("Submitting edited approval..."):
                            ok, msg = post_approval(
                                incident_id=active_id,
                                approved=True,
                                acknowledged_sources=all_source_ids if is_strict else None,
                                edits=edits_payload,
                                reason=edit_reason,
                            )
                            if ok:
                                st.session_state.edit_mode = False
                                st.success("Submitted edits! Resuming workflow...")
                                st.rerun()
                            else:
                                st.error(msg)

                # Rejection flow
                if reject_btn:
                    st.markdown("#### ❌ Provide Rejection Reason")
                    rej_reason = st.text_input(
                        "Rejection Reason",
                        value="Plan does not resolve root cause",
                        key="reject_reason_input",
                    )
                    if st.button("Confirm Rejection", type="secondary"):
                        with st.spinner("Rejecting plan and escalating..."):
                            ok, msg = post_approval(
                                incident_id=active_id,
                                approved=False,
                                reason=rej_reason,
                            )
                            if ok:
                                st.warning("Plan rejected. Escalating to human engineering.")
                                st.rerun()
                            else:
                                st.error(msg)

            elif status_val == "resolved":
                st.success("🎉 **Workflow Complete**: Resolution verified and ticketed.")
                ticket = inc_data.get("ticket")
                saved_know = inc_data.get("knowledge_saved")
                if ticket:
                    st.markdown(
                        f"**Support Ticket Created:** `{ticket.get('ticket_id')}` | "
                        f"Owner Team: `{ticket.get('owner_team')}` | "
                        f"Severity: `{ticket.get('severity')}`"
                    )
                if saved_know:
                    st.markdown(
                        f"**Application Profile Persisted:** `{saved_know.get('path')}` (v{saved_know.get('version')})"
                    )

            elif status_val == "escalated":
                st.error("🚨 **Incident Escalated to Human Incident Manager**")
                st.caption("Grounding check retries exceeded or operator rejected proposal.")


# ==============================================================================
# TAB 2: Knowledge Library
# ==============================================================================

with tabs[1]:
    st.header("📚 Application Knowledge Library")
    st.caption("Application architecture, dependencies, known errors, and runbook profiles.")

    if st.button("🔄 Refresh Profiles"):
        st.rerun()

    profiles = fetch_knowledge_profiles()
    if not profiles:
        st.info("No saved application knowledge profiles found yet. Run an application scan to build profiles.")
    else:
        for p in profiles:
            svc_name = p.get("service", "unknown")
            version = p.get("version", 1)
            updated = p.get("updated", "unknown")
            with st.expander(f"📦 Service Profile: `{svc_name}` (Version {version} - Updated {updated})"):
                st.markdown(p.get("markdown", "*No content*"))


# ==============================================================================
# TAB 3: Support Tickets
# ==============================================================================

with tabs[2]:
    st.header("🎫 Ticketing System")
    st.caption("Active and resolved incident support tickets from SQLite.")

    if st.button("🔄 Refresh Tickets"):
        st.rerun()

    tickets = fetch_tickets()
    if not tickets:
        st.info("No tickets created yet. Approved incident resolutions will create support tickets.")
    else:
        for t in tickets:
            t_id = t.get("ticket_id")
            title = t.get("title")
            t_status = t.get("status")
            sev = t.get("severity")
            team = t.get("owner_team")
            created_at = t.get("created_at")

            status_icon = "🟢" if t_status == "RESOLVED" else "🟡"
            st.markdown(f"#### {status_icon} `{t_id}`: {title}")
            st.markdown(
                f"**Status:** `{t_status}` | **Severity:** `{sev}` | **Team:** `{team}` | **Created:** `{created_at}`"
            )
            st.markdown(f"_{t.get('description', '')}_")
            st.markdown("---")
