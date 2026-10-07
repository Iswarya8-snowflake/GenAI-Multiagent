"""Live monitoring HTTP client tools using httpx."""

import os
from typing import Any, Dict, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

MONITORING_URL = os.getenv("MONITORING_URL", "http://127.0.0.1:8001").rstrip("/")


def get_metrics(service: Optional[str] = None) -> Dict[str, Any]:
    """Fetch live metrics for a specific service or all services."""
    url = f"{MONITORING_URL}/services/{service}/metrics" if service else f"{MONITORING_URL}/metrics"
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


def get_service_health(service: Optional[str] = None) -> Dict[str, Any]:
    """Fetch health status for a specific service or all services."""
    url = f"{MONITORING_URL}/services/{service}/health" if service else f"{MONITORING_URL}/services/health"
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


def get_active_alerts(service: Optional[str] = None) -> Dict[str, Any]:
    """Fetch active alerts, optionally filtered by service."""
    url = f"{MONITORING_URL}/alerts"
    params = {"service": service} if service else {}
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def tail_log(service: str, lines: int = 50) -> Dict[str, Any]:
    """Fetch the latest log lines for a service."""
    url = f"{MONITORING_URL}/logs/{service}"
    params = {"lines": lines}
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

