"""Streamlit Multipage Portal for L3 Incident Copilot per PROJECT_SPEC.md.

Talks exclusively to the FastAPI backend using httpx.
Pages:
1. Investigate: Dual mode (investigate/scan), log upload, Analyse button, finding timeline (st.status),
   root cause with colored source chips (KB, ticket, log, live, web), fix steps checklist, similar tickets,
   metric line chart, live knowledge draft (expander DRAFT), approval panel with policy reasons and strict checkbox,
   and "Saved <service> knowledge vN" redirection button using st.query_params.
2. Live Monitor: Service health cards, active alerts, metric chart, demo scenario injection controls.
3. Knowledge Library: Document list with version and updated date, markdown viewer, download button,
   and version picker from history folder.
4. Tickets: Search and list tickets with status, severity, and details.
5. About: Architectural overview, synthetic services, error codes, grounding and approval policies.
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Tuple

import httpx
import streamlit as st

# ==============================================================================
# Page Configuration & Global Styles
# ==============================================================================

st.set_page_config(
    page_title="L3 Incident Copilot Portal",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom minimal CSS chips and badges
st.markdown(
    """
    <style>
    .source-chip {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
        color: white;
        margin-right: 5px;
        margin-bottom: 3px;
        letter-spacing: 0.3px;
    }
    .chip-kb { background-color: #2e7d32; }
    .chip-ticket { background-color: #1565c0; }
    .chip-log { background-color: #e65100; }
    .chip-live { background-color: #c62828; }
    .chip-web { background-color: #6a1b9a; }
    .chip-default { background-color: #546e7a; }
    .health-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 700;
    }
    .health-healthy { background-color: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7; }
    .health-degraded { background-color: #fff8e1; color: #f57f17; border: 1px solid #ffe082; }
    .health-critical { background-color: #ffebee; color: #c62828; border: 1px solid #ef9a9a; }
    .health-unknown { background-color: #eceff1; color: #546e7a; border: 1px solid #cfd8dc; }
    </style>
    """,
    unsafe_allow_html=True,
)

DEFAULT_API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_API_KEY = os.getenv("API_KEY", "")

SOURCE_CONFIGS = {
    "KB": {"class": "chip-kb", "icon": "📚", "label": "KB"},
    "ticket": {"class": "chip-ticket", "icon": "🎫", "label": "ticket"},
    "log": {"class": "chip-log", "icon": "📜", "label": "log"},
    "live": {"class": "chip-live", "icon": "🔴", "label": "live"},
    "web": {"class": "chip-web", "icon": "🌐", "label": "web"},
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


def inject_scenario(scenario_name: str) -> Tuple[bool, str]:
    """Trigger simulator scenario via FastAPI backend."""
    try:
        url = f"{get_api_url()}/scenario/{scenario_name}"
        resp = httpx.post(url, headers=get_headers(), timeout=6.0)
        if resp.status_code == 200:
            data = resp.json()
            return True, data.get("message", f"Scenario '{scenario_name}' active")
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
    """Retrieve full incident status and details."""
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
    """Fetch all saved application knowledge profiles."""
    try:
        url = f"{get_api_url()}/knowledge"
        resp = httpx.get(url, headers=get_headers(), timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


def fetch_service_knowledge(service: str, version: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Fetch application knowledge profile for a service, optionally by version."""
    try:
        url = f"{get_api_url()}/knowledge/{service}"
        params = {"version": version} if version is not None else None
        resp = httpx.get(url, params=params, headers=get_headers(), timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def fetch_tickets(query: str = "", status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch tickets from FastAPI."""
    try:
        url = f"{get_api_url()}/tickets"
        params = {}
        if query:
            params["query"] = query
        if status_filter and status_filter != "ALL":
            params["status"] = status_filter
        resp = httpx.get(url, params=params, headers=get_headers(), timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


def fetch_monitoring_health() -> Dict[str, Any]:
    """Fetch service health states from FastAPI monitoring proxy."""
    try:
        url = f"{get_api_url()}/monitoring/health"
        resp = httpx.get(url, headers=get_headers(), timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
        return {"services": {}, "as_of": None}
    except Exception:
        return {"services": {}, "as_of": None}


def fetch_monitoring_alerts() -> List[Dict[str, Any]]:
    """Fetch active alerts from FastAPI monitoring proxy."""
    try:
        url = f"{get_api_url()}/monitoring/alerts"
        resp = httpx.get(url, headers=get_headers(), timeout=5.0)
        if resp.status_code == 200:
            return resp.json().get("alerts", [])
        return []
    except Exception:
        return []


def fetch_monitoring_metrics() -> Dict[str, Any]:
    """Fetch service metrics from FastAPI monitoring proxy."""
    try:
        url = f"{get_api_url()}/monitoring/metrics"
        resp = httpx.get(url, headers=get_headers(), timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
        return {"services": {}, "as_of": None}
    except Exception:
        return {"services": {}, "as_of": None}


def stream_sse_events(incident_id: str) -> Generator[Tuple[str, Any], None, None]:
    """
    Stream Server-Sent Events from FastAPI /incidents/{id}/events.
    Yields (event_name, data_payload) tuples.
    """
    url = f"{get_api_url()}/incidents/{incident_id}/events"
    try:
        with httpx.stream("GET", url, headers=get_headers(), timeout=120.0) as response:
            if response.status_code != 200:
                yield "error", {"error": f"SSE connection failed ({response.status_code})"}
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
                    continue
    except Exception as e:
        yield "error", {"error": str(e)}


# ==============================================================================
# Evidence Source & UI Helpers
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


def render_source_chip(source_type: str, source_id: str) -> str:
    """Render CSS source chip."""
    cfg = SOURCE_CONFIGS.get(source_type, {"class": "chip-default", "icon": "📄", "label": source_type})
    return f"<span class='source-chip {cfg['class']}'>{cfg['icon']} {cfg['label']}: {source_id}</span>"


def render_health_pill(status: str) -> str:
    """Render status badge."""
    st_upper = str(status).upper()
    css_class = "health-healthy" if st_upper == "HEALTHY" else ("health-degraded" if st_upper == "DEGRADED" else "health-critical")
    icon = "🟢" if st_upper == "HEALTHY" else ("🟡" if st_upper == "DEGRADED" else "🔴")
    return f"<span class='health-badge {css_class}'>{icon} {st_upper}</span>"


def render_title_bar():
    """Render a screenshot-friendly title bar with the project name."""
    st.markdown(
        """
        <div style="background: linear-gradient(90deg, #0f172a 0%, #1e293b 100%); padding: 14px 22px; border-radius: 8px; margin-bottom: 22px; color: #ffffff; display: flex; align-items: center; justify-content: space-between; border-left: 6px solid #3b82f6; box-shadow: 0 2px 6px rgba(0,0,0,0.15);">
            <div style="display: flex; align-items: center; gap: 14px;">
                <span style="font-size: 28px;">🚨</span>
                <div>
                    <div style="font-size: 20px; font-weight: 700; letter-spacing: 0.5px;">L3 Incident Triage Copilot</div>
                    <div style="font-size: 13px; color: #94a3b8;">Autonomous Multi-Agent Triage, Evidence Grounding & Resolution Portal</div>
                </div>
            </div>
            <div style="font-size: 11px; background: rgba(59,130,246,0.25); color: #93c5fd; padding: 5px 12px; border-radius: 12px; font-weight: 600; letter-spacing: 0.5px; border: 1px solid rgba(59,130,246,0.4);">
                PROJECT_SPEC PORTAL
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer():
    """Render persistent footer stating synthetic data disclaimer."""
    st.markdown(
        """
        <div style="margin-top: 50px; padding: 16px 20px; border-top: 1px solid #e2e8f0; text-align: center; font-size: 12px; color: #64748b; background-color: #f8fafc; border-radius: 6px;">
            🔒 <strong>Disclaimer</strong>: All data is synthetic and the monitoring feed is simulated.
        </div>
        """,
        unsafe_allow_html=True,
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
if "findings_log" not in st.session_state:
    st.session_state.findings_log = []
if "live_as_of" not in st.session_state:
    st.session_state.live_as_of = None
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False


# ==============================================================================
# Sidebar Global Controls (Scenario Injection & API Settings)
# ==============================================================================

def render_sidebar():
    with st.sidebar:
        st.markdown("### 🎛️ Simulator & Settings")

        # Scenario injection demo control
        st.markdown("#### 🧪 Injected Scenarios")
        scenarios = {
            "db_lock": "orders-db Lock Wait (DB-1205)",
            "queue_backlog": "msg-queue Lag (MQ-2041)",
            "cpu_spike": "calc-engine CPU Spike (JOB-5003)",
            "batch_failure": "calc-engine Batch Failure (JOB-5003)",
            "reset": "Reset Baseline (Healthy)",
        }
        chosen_scen = st.selectbox(
            "Demo Scenario",
            options=list(scenarios.keys()),
            format_func=lambda s: scenarios[s],
            key="sb_scen_select",
        )
        if st.button("⚡ Inject Scenario", use_container_width=True, key="sb_inject_btn"):
            ok, msg = inject_scenario(chosen_scen)
            if ok:
                st.success(f"Scenario injected: `{chosen_scen}`")
            else:
                st.error(msg)

        st.markdown("---")

        # Connection health
        is_up, h_info = check_backend_health()
        if is_up:
            st.caption("🟢 **Backend Online** (`" + get_api_url() + "`)")
        else:
            st.caption("🔴 **Backend Offline** (`" + get_api_url() + "`)")

        with st.expander("⚙️ Connection Settings"):
            st.session_state.api_base_url = st.text_input("FastAPI Base URL", value=st.session_state.api_base_url)
            st.session_state.api_key = st.text_input("API Key", value=st.session_state.api_key, type="password")


# ==============================================================================
# Page 1: Investigate
# ==============================================================================

def page_investigate():
    render_title_bar()
    st.title("🚨 L3 Incident Investigation & Triage")
    st.caption("Automated diagnosis, live system inspection, evidence grounding, and human-in-the-loop resolution.")

    # 1. Mode switch & Inputs
    mode_choice = st.radio(
        "Workflow Mode",
        ["Investigate an error", "Scan an application"],
        horizontal=True,
        help="Investigate diagnoses error reports and logs. Scan audits an application to compile its architecture knowledge profile.",
    )

    col1, col2 = st.columns([2, 1])

    if mode_choice == "Investigate an error":
        with col1:
            inc_text = st.text_area(
                "Incident / Error Description",
                placeholder="e.g. orders-db lock wait timeout reported with DB-1205 while executing checkout batch",
                height=105,
            )
        with col2:
            uploaded_log = st.file_uploader("Upload Error Log (Optional)", type=["log", "txt"])
        target_service = None
    else:
        with col1:
            target_service = st.selectbox(
                "Target Application Service",
                ["orders-db", "msg-queue", "feed-gateway", "calc-engine"],
            )
            inc_text = f"Application scan for {target_service}"
        with col2:
            st.info("💡 **Scan Mode** collects live dependencies, metrics, error signatures, and ticket history without an active outage.")
            uploaded_log = None

    # Actions: Analyse and 1-Click Load demo scenario
    col_act1, col_act2, col_act3 = st.columns([1, 1.4, 2])
    with col_act1:
        analyse_btn = st.button("🔍 Analyse", type="primary", use_container_width=True)
    with col_act2:
        demo_btn = st.button("⚡ Load demo scenario", use_container_width=True, help="Injects db_lock scenario into simulator, fills sample error report, and starts investigation in 1 click")

    if demo_btn:
        with st.spinner("Injecting demo scenario 'db_lock' into simulator and starting investigation..."):
            inject_scenario("db_lock")
            demo_text = "orders-db lock wait timeout reported with error code DB-1205: Lock wait timeout exceeded; try restarting transaction while executing checkout batch"
            demo_logs = (
                "2026-10-07 10:00:15 WARN orders-db - Elevated query latency threshold exceeded\n"
                "2026-10-07 10:00:16 ERROR orders-db - [DB-1205] Lock wait timeout exceeded; try restarting transaction\n"
                "2026-10-07 10:00:17 INFO orders-db - Worker connection pool blocked on transaction lock"
            )
            ok, res = post_incident(
                text=demo_text,
                logs=demo_logs,
                mode="investigate",
                service="orders-db",
            )
            if ok:
                st.session_state.active_incident_id = res["incident_id"]
                st.session_state.incident_data = None
                st.session_state.findings_log = []
                st.session_state.live_as_of = None
                st.session_state.edit_mode = False
                st.success("Loaded demo scenario 'db_lock' and initiated investigation!")
                st.rerun()
            else:
                st.error(f"Failed to start demo investigation: {res}")

    elif analyse_btn:
        if not inc_text.strip():
            st.error("Please provide an incident description or select a service.")
        else:
            log_str = None
            if uploaded_log is not None:
                log_str = uploaded_log.read().decode("utf-8", errors="replace")

            mode_val = "scan" if mode_choice == "Scan an application" else "investigate"
            ok, res = post_incident(
                text=inc_text.strip(),
                logs=log_str,
                mode=mode_val,
                service=target_service,
            )
            if ok:
                st.session_state.active_incident_id = res["incident_id"]
                st.session_state.incident_data = None
                st.session_state.findings_log = []
                st.session_state.live_as_of = None
                st.session_state.edit_mode = False
                st.rerun()
            else:
                st.error(f"Failed to submit: {res}")

    # Active Investigation Workspace
    active_id = st.session_state.active_incident_id
    if not active_id:
        render_footer()
        return

    st.markdown("---")
    st.subheader(f"Active Investigation: `{active_id}`")

    # Fetch incident state
    incident = fetch_incident(active_id)
    if incident:
        st.session_state.incident_data = incident

    inc_data = st.session_state.incident_data or {}
    curr_status = inc_data.get("status", "queued")

    # 2. Timeline from Finding Events (st.status with tick per step & spinner on current)
    st.markdown("#### ⏱️ Investigation Timeline")

    if curr_status in ("queued", "investigating", "scanning", "resuming"):
        with st.status(f"Executing workflow steps ({curr_status})...", expanded=True) as status_box:
            status_placeholder = st.empty()
            steps_rendered = []

            for ev_name, ev_data in stream_sse_events(active_id):
                if ev_name == "finding" and isinstance(ev_data, dict):
                    st.session_state.findings_log.append(ev_data)
                    st.write(f"✅ **{ev_data.get('title')}**: {ev_data.get('detail')}")
                elif ev_name == "agent_step" and isinstance(ev_data, dict):
                    lf = ev_data.get("update", {}).get("live_findings", {})
                    if lf.get("as_of"):
                        st.session_state.live_as_of = lf.get("as_of")
                elif ev_name in ("approval_required", "done", "error"):
                    status_box.update(label="Investigation Analysis Complete", state="complete")
                    st.session_state.incident_data = fetch_incident(active_id)
                    st.rerun()
                    break
    else:
        with st.status("Investigation Completed", state="complete", expanded=False):
            if st.session_state.findings_log:
                for f in st.session_state.findings_log:
                    st.write(f"✅ **{f.get('title')}**: {f.get('detail')}")
            else:
                st.write("All investigation steps completed.")

    # 3. Result Cards: Root Cause (with colored source chips), Checklist Fix Steps, Similar Tickets, Metric Chart
    col_res1, col_res2 = st.columns([3, 2])

    evidence = inc_data.get("evidence") or []
    plan = inc_data.get("plan") or {}
    review = inc_data.get("review") or {}
    policy = inc_data.get("policy") or inc_data.get("pending_approval", {}).get("policy") or {}
    triaged_comp = inc_data.get("service") or inc_data.get("triage", {}).get("component") or "orders-db"

    with col_res1:
        st.markdown("#### 🎯 Diagnosis & Root Cause")
        rc = plan.get("root_cause") or "Diagnosis in progress..."
        conf = plan.get("confidence", 0.0)

        st.info(f"**Likely Root Cause:** {rc}")
        st.metric("Confidence", f"{int(conf * 100)}%", delta=f"Rating: {conf:.2f}")

        # Claims with colored source chips
        claims = plan.get("claims", [])
        if claims:
            st.markdown("**Grounded Claims & Source References:**")
            for cl in claims:
                text = cl.get("text", "")
                chips = ""
                for sid in cl.get("source_ids", []):
                    stype = classify_source_type(sid, evidence)
                    chips += render_source_chip(stype, sid)
                st.markdown(f"• {text}<br/>&nbsp;&nbsp;{chips}", unsafe_allow_html=True)

        # Fix steps as an interactive checklist
        fix_steps = plan.get("fix_steps", [])
        if fix_steps:
            st.markdown("#### 🛠️ Actionable Fix Steps (Checklist)")
            for i, step in enumerate(fix_steps, 1):
                st.checkbox(f"{step}", key=f"fix_step_{active_id}_{i}")

        # Grounding review result
        if review:
            if review.get("passed", False):
                st.success("✅ **Grounding Verification Passed**: All claims cite verified sources.")
            else:
                st.warning("⚠️ **Grounding Issues Detected**:")
                for iss in review.get("issues", []):
                    st.caption(f"- {iss}")

    with col_res2:
        # Key Metric Line Chart
        st.markdown(f"#### 📈 Key Metric: `{triaged_comp}`")
        metrics_data = fetch_monitoring_metrics()
        services_m = metrics_data.get("services", {})
        comp_metrics = services_m.get(triaged_comp, {})

        if comp_metrics:
            key_metric_name = list(comp_metrics.keys())[0]
            val = float(comp_metrics.get(key_metric_name, 10.0))
            # Generate trend progression
            trend_data = [max(0.0, val * (0.2 + i * 0.1)) for i in range(8)] + [val]
            st.metric(key_metric_name.replace("_", " ").title(), f"{val:.1f}")
            st.line_chart(trend_data, height=140)
        else:
            st.caption("Monitoring metrics connecting...")

        # Similar Tickets Card
        st.markdown("#### 🎫 Similar Past Incidents")
        similar = inc_data.get("state", {}).get("tickets_found") or []
        if not similar:
            similar = fetch_tickets(query=triaged_comp)[:3]

        if similar:
            for sim in similar[:3]:
                st.caption(f"**[{sim.get('ticket_id')}]** {sim.get('title')}")
                if sim.get("description"):
                    st.text(sim.get("description")[:120])
        else:
            st.caption("No matching past tickets found.")

    # 4. Live Knowledge Draft (expander labelled DRAFT)
    draft_md = inc_data.get("knowledge_draft") or inc_data.get("state", {}).get("knowledge_draft")
    if draft_md:
        with st.expander("📝 DRAFT: Application Knowledge Profile", expanded=False):
            st.markdown(draft_md)

    # 5. Approval Panel with policy reasons & strict checkbox
    st.markdown("---")
    pending = inc_data.get("pending_approval")
    st_val = inc_data.get("status")

    if st_val == "waiting_approval" and pending:
        st.subheader("3. ✍️ Human Approval Gate")
        pol_level = str(policy.get("level", "standard")).upper()
        reasons = policy.get("reasons", [])

        if pol_level == "STRICT":
            st.warning(f"🚨 **Policy Level:** `STRICT`")
            for r in reasons:
                st.caption(f"- {r}")
            strict_ack = st.checkbox(
                "I checked the sources and confirmed all cited facts are accurate (Required)",
                value=False,
                key="strict_ack_box",
            )
            can_approve = strict_ack
        else:
            st.info(f"ℹ️ **Policy Level:** `STANDARD`")
            can_approve = True

        col_a1, col_a2, col_a3 = st.columns([1, 1, 1])

        with col_a1:
            if st.button("✅ Approve", type="primary", disabled=not can_approve, use_container_width=True):
                all_ids = [d.get("id") for d in evidence if d.get("id")] or ["doc-1"]
                ok, msg = post_approval(active_id, approved=True, acknowledged_sources=all_ids if pol_level == "STRICT" else None)
                if ok:
                    st.success("Approved! Resuming...")
                    st.rerun()
                else:
                    st.error(msg)

        with col_a2:
            if st.button("✏️ Edit and Approve", use_container_width=True):
                st.session_state.edit_mode = not st.session_state.edit_mode

        with col_a3:
            reject_btn = st.button("❌ Reject", use_container_width=True)

        if st.session_state.edit_mode:
            st.markdown("##### ✏️ Modify Plan")
            ed_rc = st.text_input("Edited Root Cause", value=plan.get("root_cause", ""))
            ed_fix = st.text_area("Edited Fix Steps (one per line)", value="\n".join(plan.get("fix_steps", [])))
            if st.button("Submit Approved Edits", type="primary", disabled=not can_approve):
                steps_l = [s.strip() for s in ed_fix.split("\n") if s.strip()]
                all_ids = [d.get("id") for d in evidence if d.get("id")] or ["doc-1"]
                ok, msg = post_approval(
                    active_id,
                    approved=True,
                    acknowledged_sources=all_ids if pol_level == "STRICT" else None,
                    edits={"root_cause": ed_rc, "fix_steps": steps_l},
                    reason="Operator edited plan",
                )
                if ok:
                    st.session_state.edit_mode = False
                    st.success("Edits submitted!")
                    st.rerun()
                else:
                    st.error(msg)

        if reject_btn:
            rej_reason = st.text_input("Rejection Reason", value="Incorrect root cause identified")
            if st.button("Confirm Rejection"):
                ok, msg = post_approval(active_id, approved=False, reason=rej_reason)
                if ok:
                    st.warning("Incident escalated to human.")
                    st.rerun()
                else:
                    st.error(msg)

    elif st_val == "resolved":
        saved_know = inc_data.get("knowledge_saved") or inc_data.get("state", {}).get("knowledge_saved")
        v = saved_know.get("version", 1) if saved_know else 1
        svc = triaged_comp

        st.success(f"🎉 **Workflow Completed**: Saved {svc} knowledge v{v}")

        # Redirection button using st.query_params
        if st.button(f"📖 Open {svc} in Knowledge Library", type="primary", key="btn_open_lib"):
            st.query_params["service"] = svc
            st.query_params["page"] = "Knowledge Library"
            st.rerun()

        ticket = inc_data.get("ticket")
        if ticket:
            st.info(f"Support Ticket Created: `{ticket.get('ticket_id')}` assigned to `{ticket.get('owner_team')}`")

    elif st_val == "escalated":
        st.error("🚨 **Incident Escalated to Human Engineering Team**")

    render_footer()


# ==============================================================================
# Page 2: Live Monitor
# ==============================================================================

def page_live_monitor():
    render_title_bar()
    st.title("🩺 Live System Monitoring")
    st.caption("Live health cards, active alerts, and dependency metrics from the monitoring simulator.")

    # 1. Demo Controls: Inject Scenario
    with st.expander("🧪 Demo Simulator Controls", expanded=True):
        col_s1, col_s2 = st.columns([3, 1])
        scenarios = {
            "db_lock": "orders-db Lock Wait (DB-1205)",
            "queue_backlog": "msg-queue Consumer Lag (MQ-2041)",
            "cpu_spike": "calc-engine CPU Spike (JOB-5003)",
            "batch_failure": "calc-engine Batch Failure (JOB-5003)",
            "reset": "Reset Baseline (All Healthy)",
        }
        with col_s1:
            chosen = st.selectbox(
                "Select Failure Scenario",
                options=list(scenarios.keys()),
                format_func=lambda s: scenarios[s],
            )
        with col_s2:
            if st.button("⚡ Inject Scenario", use_container_width=True):
                ok, msg = inject_scenario(chosen)
                if ok:
                    st.success(f"Injected: {chosen}")
                    st.rerun()
                else:
                    st.error(msg)

    # 2. Service Health Cards
    st.markdown("#### 📦 Service Health Overview")
    h_data = fetch_monitoring_health()
    services_h = h_data.get("services", {})
    as_of = h_data.get("as_of", datetime.now().isoformat())
    st.caption(f"⏱️ As of: `{as_of}`")

    cols = st.columns(4)
    services_list = ["orders-db", "msg-queue", "feed-gateway", "calc-engine"]

    for i, sname in enumerate(services_list):
        st_val = services_h.get(sname, "HEALTHY")
        with cols[i]:
            st.metric(label=sname, value=st_val)
            st.markdown(render_health_pill(st_val), unsafe_allow_html=True)

    # 3. Active Alerts
    st.markdown("#### 🚨 Active Monitoring Alerts")
    alerts = fetch_monitoring_alerts()
    if alerts:
        for a in alerts:
            sev = a.get("severity", "WARNING")
            icon = "🔴" if sev == "CRITICAL" else "🟡"
            st.warning(f"{icon} **[{a.get('error_code')}]** on `{a.get('service')}`: {a.get('message')} (Fired: {a.get('fired_at')})")
    else:
        st.success("🟢 No active alerts. All monitored metrics within normal thresholds.")

    # 4. Metric Charts
    st.markdown("#### 📊 Service Metric Trends")
    m_data = fetch_monitoring_metrics()
    services_m = m_data.get("services", {})

    selected_s = st.selectbox("Inspect Metrics For Service", services_list)
    s_metrics = services_m.get(selected_s, {})

    if s_metrics:
        m_cols = st.columns(len(s_metrics))
        for idx, (m_name, m_val) in enumerate(s_metrics.items()):
            with m_cols[idx]:
                st.metric(m_name.replace("_", " ").title(), f"{m_val:.1f}")
                # Trend curve
                curve = [float(m_val) * (0.4 + j * 0.08) for j in range(8)] + [float(m_val)]
                st.line_chart(curve, height=120)
    else:
        st.info("Metrics updating...")

    render_footer()


# ==============================================================================
# Page 3: Knowledge Library
# ==============================================================================

def page_knowledge_library():
    render_title_bar()
    st.title("📚 Application Knowledge Library")
    st.caption("Audited application architecture, dependencies, known errors, runbooks, and historical versions.")

    # Check query param for preselected service
    target_svc = st.query_params.get("service")

    profiles = fetch_knowledge_profiles()
    if not profiles:
        st.info("No saved knowledge profiles found yet. Run an investigation or application scan to generate profiles.")
        render_footer()
        return

    services_available = [p.get("service") for p in profiles if p.get("service")]

    # Service selector
    default_idx = 0
    if target_svc and target_svc in services_available:
        default_idx = services_available.index(target_svc)

    selected_service = st.selectbox(
        "Select Service Profile",
        services_available,
        index=default_idx,
    )

    if not selected_service:
        render_footer()
        return

    # Fetch document metadata and versions
    doc_meta = fetch_service_knowledge(selected_service)
    if not doc_meta:
        st.error(f"Failed to load document for `{selected_service}`.")
        render_footer()
        return

    curr_version = doc_meta.get("version", 1)
    history_versions = doc_meta.get("history_versions", [])
    all_versions = sorted(list(set([curr_version] + history_versions)), reverse=True)

    # Version Picker from history folder
    col_v1, col_v2, col_v3 = st.columns([1, 2, 1])
    with col_v1:
        picked_v = st.selectbox(
            "Version Picker",
            options=all_versions,
            format_func=lambda v: f"v{v} (Current)" if v == curr_version else f"v{v} (Archived)",
        )

    # Fetch picked version content
    picked_doc = fetch_service_knowledge(selected_service, version=(None if picked_v == curr_version else picked_v))
    if not picked_doc:
        picked_doc = doc_meta

    with col_v2:
        st.caption(f"**Last Updated:** `{picked_doc.get('updated', 'N/A')}` | **File:** `{picked_doc.get('path', 'N/A')}`")

    with col_v3:
        st.download_button(
            label="📥 Download Markdown",
            data=picked_doc.get("markdown", ""),
            file_name=f"{selected_service}_v{picked_v}.md",
            mime="text/markdown",
            use_container_width=True,
        )

    st.markdown("---")
    st.markdown(picked_doc.get("markdown", "*No markdown content*"))
    render_footer()


# ==============================================================================
# Page 4: Tickets
# ==============================================================================

def page_tickets():
    render_title_bar()
    st.title("🎫 Support Ticketing System")
    st.caption("Search, filter, and inspect incident resolution tickets persisted in SQLite.")

    col_q, col_st = st.columns([3, 1])
    with col_q:
        q = st.text_input("Search tickets", placeholder="Search by error code, title, or service...")
    with col_st:
        status_filter = st.selectbox("Status Filter", ["ALL", "OPEN", "RESOLVED", "IN_PROGRESS"])

    tickets = fetch_tickets(query=q, status_filter=status_filter)

    st.metric("Total Tickets Found", len(tickets))

    if not tickets:
        st.info("No tickets match the query criteria.")
        render_footer()
        return

    for t in tickets:
        t_id = t.get("ticket_id")
        title = t.get("title")
        st_val = t.get("status", "OPEN")
        sev = t.get("severity", "P2")
        team = t.get("owner_team", "support")
        created = t.get("created_at")

        with st.container():
            st.markdown(f"#### `{t_id}`: {title}")
            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            with col_m1:
                st.caption(f"**Status:** `{st_val}`")
            with col_m2:
                st.caption(f"**Severity:** `{sev}`")
            with col_m3:
                st.caption(f"**Owner Team:** `{team}`")
            with col_m4:
                st.caption(f"**Created:** `{created}`")

            st.text(t.get("description", ""))
            st.markdown("---")

    render_footer()


# ==============================================================================
# Page 5: About
# ==============================================================================

def page_about():
    render_title_bar()
    st.title("ℹ️ About L3 Incident Copilot")
    st.markdown(
        """
        ### Multi-Agent Autonomous Incident Triage Copilot
        An L3 incident resolution system designed per **PROJECT_SPEC.md**.

        #### 🏗️ Architecture
        - **Streamlit UI**: Multi-page portal talking exclusively to FastAPI with `httpx`.
        - **FastAPI**: REST API, SSE streaming, and human-in-the-loop approval management.
        - **LangGraph**: Stateful graph orchestrator with parallel investigation, join barrier, grounding review, and interrupts.
        - **FastMCP Tool Server**: Streamable HTTP tool server on port `8765` exposing 19 tools.
        - **Knowledge & Data**: FAISS vector store with Ollama `nomic-embed-text`, SQLite tickets DB, and monitoring simulator on port `8001`.

        #### 📦 Synthetic Services & Error Codes
        - **`orders-db`**: `DB-1205` (lock wait timeout / deadlock)
        - **`msg-queue`**: `MQ-2041` (consumer lag / queue depth spike)
        - **`calc-engine`**: `JOB-5003` (batch calculation failure / CPU spike)
        - **`feed-gateway`**: `FEED-7002` (thread pool exhaustion)

        #### 🛡️ Grounding & Policies
        - **Grounding Reviewer**: Rejects claims lacking evidence citations, ungrounded error codes, or destructive commands (`DROP`, `DELETE`, `TRUNCATE`, `rm -rf`, `kill -9`).
        - **Strict Policy**: Enforces human verification of evidence citations for P1/P2 incidents, low confidence (<0.7), web sources, or retried reviews.
        """
    )
    render_footer()


# ==============================================================================
# Navigation Setup (st.navigation if available, otherwise sidebar radio)
# ==============================================================================

render_sidebar()

# Determine initial page from query parameters if present
query_page = st.query_params.get("page")

if hasattr(st, "navigation") and hasattr(st, "Page"):
    pages = [
        st.Page(page_investigate, title="Investigate", icon="🔍", url_path="investigate", default=(query_page != "Knowledge Library")),
        st.Page(page_live_monitor, title="Live Monitor", icon="🩺", url_path="monitor"),
        st.Page(page_knowledge_library, title="Knowledge Library", icon="📚", url_path="knowledge", default=(query_page == "Knowledge Library")),
        st.Page(page_tickets, title="Tickets", icon="🎫", url_path="tickets"),
        st.Page(page_about, title="About", icon="ℹ️", url_path="about"),
    ]
    pg = st.navigation(pages)
    pg.run()
else:
    options = ["Investigate", "Live Monitor", "Knowledge Library", "Tickets", "About"]
    default_idx = 0
    if query_page in options:
        default_idx = options.index(query_page)

    choice = st.sidebar.radio("Navigation", options, index=default_idx)
    if choice == "Investigate":
        page_investigate()
    elif choice == "Live Monitor":
        page_live_monitor()
    elif choice == "Knowledge Library":
        page_knowledge_library()
    elif choice == "Tickets":
        page_tickets()
    elif choice == "About":
        page_about()
