#!/usr/bin/env python3
"""Runner script to coordinate and start all L3 Incident Copilot services as subprocesses:

1. Monitoring Simulator (port 8001)
2. FastMCP Tool Server (port 8765)
3. FastAPI Application (port 8000)
"""

import os
import signal
import subprocess
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))


def start_services():
    python_bin = sys.executable
    processes = []

    print("\n" + "=" * 75)
    print("STARTING ALL L3 INCIDENT COPILOT SERVICES")
    print("=" * 75)

    try:
        # 1. Monitoring Simulator
        print("[1/3] Launching Monitoring Simulator on http://127.0.0.1:8001 ...")
        sim_proc = subprocess.Popen(
            [python_bin, "-m", "uvicorn", "app.sim.app:app", "--host", "127.0.0.1", "--port", "8001"],
            cwd=PROJECT_ROOT,
        )
        processes.append(("Monitoring Simulator", sim_proc))

        # 2. FastMCP Server
        print("[2/3] Launching FastMCP Server on http://127.0.0.1:8765/mcp ...")
        mcp_proc = subprocess.Popen(
            [python_bin, os.path.join(PROJECT_ROOT, "app", "mcp_server", "server.py")],
            cwd=PROJECT_ROOT,
        )
        processes.append(("FastMCP Server", mcp_proc))

        # 3. FastAPI API
        print("[3/3] Launching FastAPI App on http://127.0.0.1:8000 ...")
        api_proc = subprocess.Popen(
            [python_bin, "-m", "uvicorn", "app.api.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=PROJECT_ROOT,
        )
        processes.append(("FastAPI API", api_proc))

        print("\n" + "=" * 75)
        print("ALL SERVICES LAUNCHED SUCCESSFULLY")
        print("  - Monitoring Simulator : http://127.0.0.1:8001/docs")
        print("  - FastMCP Server       : http://127.0.0.1:8765/mcp")
        print("  - FastAPI Application  : http://127.0.0.1:8000/docs")
        print("=" * 75)
        print("Press Ctrl+C to terminate all services.\n")

        # Monitor processes
        while True:
            for name, proc in processes:
                poll = proc.poll()
                if poll is not None:
                    print(f"Warning: {name} exited unexpectedly with return code {poll}.")
                    raise KeyboardInterrupt
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down all services...")
    finally:
        for name, proc in processes:
            if proc.poll() is None:
                print(f"Stopping {name} (PID: {proc.pid})...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        print("All services stopped.")


if __name__ == "__main__":
    start_services()
