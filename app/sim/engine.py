"""Monitoring simulation engine tracking services, metrics, and failure scenarios."""

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SERVICES = ["orders-db", "msg-queue", "feed-gateway", "calc-engine"]

SCENARIOS = {
    "db_lock": {
        "service": "orders-db",
        "error_code": "DB-1205",
        "alert_title": "[DB-1205] Lock wait timeout exceeded on orders-db",
        "log_msg": "[DB-1205] Lock wait timeout exceeded on transaction; thread blocked on row lock in table orders",
    },
    "queue_backlog": {
        "service": "msg-queue",
        "error_code": "MQ-2041",
        "alert_title": "[MQ-2041] Consumer lag threshold exceeded on msg-queue",
        "log_msg": "[MQ-2041] Consumer lag threshold exceeded on topic orders.inbound partition 2 (lag > 50000)",
    },
    "cpu_spike": {
        "service": "feed-gateway",
        "error_code": "FEED-7002",
        "alert_title": "[FEED-7002] Thread pool saturated on feed-gateway",
        "log_msg": "[FEED-7002] Thread pool saturated: 200/200 threads busy, rejection queue full",
    },
    "batch_failure": {
        "service": "calc-engine",
        "error_code": "JOB-5003",
        "alert_title": "[JOB-5003] Calculation batch failure in calc-engine",
        "log_msg": "[JOB-5003] Calculation batch failure: unhandled exception in batch worker 4, batch aborted",
    },
}


class SimulationEngine:
    def __init__(self):
        self.active_scenario: Optional[str] = None
        self.scenario_start_time: Optional[float] = None
        self.ramp_duration_seconds: float = 120.0  # 2 minutes ramp

    def start_scenario(self, scenario_name: str) -> Dict[str, Any]:
        normalized = scenario_name.lower().replace("-", "_")
        if normalized not in SCENARIOS:
            raise ValueError(f"Unknown scenario '{scenario_name}'. Valid: {list(SCENARIOS.keys())}")
        self.active_scenario = normalized
        self.scenario_start_time = time.time()
        return {
            "status": "started",
            "scenario": self.active_scenario,
            "target_service": SCENARIOS[self.active_scenario]["service"],
            "as_of": self._as_of(),
        }

    def reset(self) -> Dict[str, Any]:
        self.active_scenario = None
        self.scenario_start_time = None
        return {
            "status": "reset",
            "active_scenario": None,
            "as_of": self._as_of(),
        }

    def _get_ramp_factor(self, service: str) -> float:
        """Return 0.0 to 1.0 ramp factor based on elapsed time if service is affected."""
        if not self.active_scenario or not self.scenario_start_time:
            return 0.0
        cfg = SCENARIOS[self.active_scenario]
        if cfg["service"] != service:
            return 0.0
        elapsed = max(0.0, time.time() - self.scenario_start_time)
        return min(1.0, elapsed / self.ramp_duration_seconds)

    def _as_of(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_service_metrics(self, service: str) -> Dict[str, Any]:
        if service not in SERVICES:
            raise ValueError(f"Unknown service '{service}'")

        ramp = self._get_ramp_factor(service)
        base = {}

        if service == "orders-db":
            base = {
                "active_connections": int(25 + ramp * 75),
                "lock_wait_seconds": round(0.05 + ramp * 45.0, 2),
                "active_locks": int(3 + ramp * 120),
                "cpu_percent": round(18.0 + ramp * 65.0, 1),
            }
        elif service == "msg-queue":
            base = {
                "consumer_lag": int(10 + ramp * 52000),
                "messages_in_sec": int(1200 + ramp * 2000),
                "consumer_count": max(0, int(8 - ramp * 8)),
                "cpu_percent": round(22.0 + ramp * 50.0, 1),
            }
        elif service == "feed-gateway":
            base = {
                "active_threads": int(40 + ramp * 160),
                "max_threads": 200,
                "latency_ms": round(15.0 + ramp * 2400.0, 1),
                "cpu_percent": round(25.0 + ramp * 74.0, 1),
            }
        elif service == "calc-engine":
            base = {
                "active_jobs": int(4 - ramp * 3),
                "failed_jobs": int(0 + ramp * 8),
                "memory_percent": round(35.0 + ramp * 58.0, 1),
                "cpu_percent": round(30.0 + ramp * 60.0, 1),
            }

        return {
            "service": service,
            "metrics": base,
            "ramp_progress": round(ramp, 3),
            "as_of": self._as_of(),
        }

    def get_all_metrics(self) -> Dict[str, Any]:
        return {
            "services": {s: self.get_service_metrics(s)["metrics"] for s in SERVICES},
            "active_scenario": self.active_scenario,
            "as_of": self._as_of(),
        }

    def get_service_health(self, service: str) -> Dict[str, Any]:
        if service not in SERVICES:
            raise ValueError(f"Unknown service '{service}'")

        ramp = self._get_ramp_factor(service)
        if ramp > 0.5:
            status = "CRITICAL"
        elif ramp > 0.1:
            status = "DEGRADED"
        else:
            status = "HEALTHY"

        return {
            "service": service,
            "status": status,
            "as_of": self._as_of(),
        }

    def get_all_health(self) -> Dict[str, Any]:
        return {
            "services": {s: self.get_service_health(s)["status"] for s in SERVICES},
            "as_of": self._as_of(),
        }

    def get_alerts(self, service: Optional[str] = None) -> Dict[str, Any]:
        alerts = []
        if self.active_scenario:
            cfg = SCENARIOS[self.active_scenario]
            target_svc = cfg["service"]
            ramp = self._get_ramp_factor(target_svc)

            if ramp > 0.15:
                if service is None or service == target_svc:
                    alerts.append({
                        "id": f"ALT-{cfg['error_code']}",
                        "service": target_svc,
                        "error_code": cfg["error_code"],
                        "severity": "CRITICAL" if ramp > 0.5 else "WARNING",
                        "message": cfg["alert_title"],
                        "fired_at": self._as_of(),
                    })

        return {
            "alerts": alerts,
            "count": len(alerts),
            "as_of": self._as_of(),
        }

    def tail_logs(self, service: str, lines: int = 50) -> Dict[str, Any]:
        if service not in SERVICES:
            raise ValueError(f"Unknown service '{service}'")

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        log_entries = [
            f"{now_str} INFO {service} - Health check ok, worker pool running",
            f"{now_str} INFO {service} - Standard heartbeat acknowledged",
        ]

        ramp = self._get_ramp_factor(service)
        if ramp > 0.1 and self.active_scenario:
            cfg = SCENARIOS[self.active_scenario]
            if cfg["service"] == service:
                log_entries.append(
                    f"{now_str} WARN {service} - Elevated latency threshold exceeded"
                )
                log_entries.append(
                    f"{now_str} ERROR {service} - {cfg['log_msg']}"
                )

        return {
            "service": service,
            "lines": log_entries[-lines:],
            "as_of": self._as_of(),
        }


# Global simulator engine instance
engine = SimulationEngine()

