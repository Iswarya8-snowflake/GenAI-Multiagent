"""FastAPI Monitoring Simulator App (Port 8001)."""

from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from app.sim.engine import engine

app = FastAPI(title="L3 Incident Monitoring Simulator", version="1.0.0")


@app.get("/")
def root():
    return {"message": "L3 Monitoring Simulator Running", "as_of": engine._as_of()}


@app.post("/scenario/reset")
def reset_scenario():
    """Reset simulator back to baseline health."""
    return engine.reset()


@app.post("/scenario/{scenario_name}")
def trigger_scenario(scenario_name: str):
    """Ramps one service's metrics over 2 minutes, fires alerts, and alters logs."""
    try:
        return engine.start_scenario(scenario_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/metrics")
def get_all_metrics():
    """Return metrics for all services."""
    return engine.get_all_metrics()


@app.get("/services/{service}/metrics")
def get_service_metrics(service: str):
    """Return metrics for a specific service."""
    try:
        return engine.get_service_metrics(service)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/services/health")
def get_all_health():
    """Return health for all services."""
    return engine.get_all_health()


@app.get("/services/{service}/health")
def get_service_health(service: str):
    """Return health for a specific service."""
    try:
        return engine.get_service_health(service)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/alerts")
def get_alerts(service: Optional[str] = Query(None)):
    """Return active alerts, optionally filtered by service."""
    return engine.get_alerts(service=service)


@app.get("/logs/{service}")
def tail_logs(service: str, lines: int = Query(50, ge=1, le=500)):
    """Return recent log lines for a service."""
    try:
        return engine.tail_logs(service=service, lines=lines)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
