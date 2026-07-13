from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

try:
    from ebook_markdown_pipeline.mineru_api_config import MinerUApiConfig, load_mineru_api_config
except ModuleNotFoundError:
    from mineru_api_config import MinerUApiConfig, load_mineru_api_config


def ensure_state_dirs(config: MinerUApiConfig) -> None:
    for path in (
        config.state_root,
        config.temp_root,
        config.client_temp_root,
        config.data_root,
        config.log_root,
        config.run_root,
    ):
        path.mkdir(parents=True, exist_ok=True)
    probe = config.run_root / f"write-probe-{os.getpid()}.tmp"
    probe.write_text("ok", encoding="ascii")
    probe.unlink()


def health_payload(config: MinerUApiConfig, timeout_seconds: float = 2.0) -> dict[str, Any]:
    request = urllib.request.Request(f"{config.url}/health", headers={"Accept": "application/json"})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            payload = json.loads(body)
            healthy = response.status == 200 and payload.get("status") == "healthy"
            return {
                "healthy": healthy,
                "url": config.url,
                "status_code": response.status,
                "service": payload,
            }
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"healthy": False, "url": config.url, "error": f"{type(exc).__name__}: {exc}"}


def port_bindable(config: MinerUApiConfig) -> tuple[bool, str | None]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((config.host, config.port))
        return True, None
    except OSError as exc:
        return False, str(exc)


def read_pid_record(config: MinerUApiConfig) -> dict[str, Any] | None:
    try:
        payload = json.loads(config.pid_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def process_command_line(pid: int) -> str | None:
    if os.name != "nt":
        try:
            return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            return None
    script = (
        f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\" -ErrorAction SilentlyContinue; "
        "if ($p) { $p.CommandLine }"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=10,
    )
    value = completed.stdout.strip()
    return value or None


def owned_process(config: MinerUApiConfig, record: dict[str, Any] | None) -> tuple[bool, int | None, str | None]:
    if not record:
        return False, None, None
    try:
        pid = int(record.get("pid"))
    except (TypeError, ValueError):
        return False, None, None
    command_line = process_command_line(pid)
    if not command_line:
        return False, pid, None
    normalized = command_line.lower().replace("_", "-")
    expected = str(config.command).lower().replace("_", "-")
    owned = expected in normalized or "mineru-api" in normalized or "mineru.cli.fast-api" in normalized
    return owned, pid, command_line


def status_payload(config: MinerUApiConfig) -> dict[str, Any]:
    health = health_payload(config)
    record = read_pid_record(config)
    owned, pid, command_line = owned_process(config, record)
    bindable, bind_error = port_bindable(config)
    return {
        "schema_version": "mineru-api-service-status-v1",
        "status": "ready" if health["healthy"] else "stopped" if bindable else "port-in-use",
        "configured_url": config.url,
        "config_path": str(config.source),
        "state_root": str(config.state_root),
        "pid": pid,
        "owned_process": owned,
        "process_command_line": command_line,
        "port_bindable": bindable,
        "port_error": bind_error,
        "health": health,
    }


def build_service_command(config: MinerUApiConfig) -> list[str]:
    command_path = Path(config.command)
    if os.name == "nt" and command_path.name.lower() == "mineru-api.exe":
        python_path = command_path.with_name("python.exe")
        if not python_path.is_file():
            raise FileNotFoundError(
                f"MinerU API venv Python was not found next to {command_path}: {python_path}"
            )
        return [
            str(python_path),
            "-m",
            "mineru.cli.fast_api",
            "--host",
            config.host,
            "--port",
            str(config.port),
        ]
    return [config.command, "--host", config.host, "--port", str(config.port)]


def start_service(config: MinerUApiConfig, timeout_seconds: float) -> dict[str, Any]:
    ensure_state_dirs(config)
    existing_health = health_payload(config)
    if existing_health["healthy"]:
        return {"ok": True, "action": "already-running", **status_payload(config)}
    bindable, bind_error = port_bindable(config)
    if not bindable:
        raise RuntimeError(f"Configured port {config.host}:{config.port} is not bindable: {bind_error}")
    command_path = Path(config.command)
    if not command_path.is_file() and not config.command:
        raise FileNotFoundError("MinerU API command is not configured")

    stdout_path = config.log_root / "mineru-api.stdout.log"
    stderr_path = config.log_root / "mineru-api.stderr.log"
    environment = os.environ.copy()
    for key in ("TEMP", "TMP", "TMPDIR"):
        environment[key] = str(config.temp_root)
    environment["EBOOK_CONVERTER_MINERU_API_URL"] = config.url
    command = build_service_command(config)
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    with stdout_path.open("ab") as stdout_handle, stderr_path.open("ab") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=config.data_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=creationflags,
            close_fds=True,
        )
    record = {
        "pid": process.pid,
        "process_role": "api-server",
        "command": command,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "url": config.url,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }
    config.pid_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    deadline = time.monotonic() + timeout_seconds
    last_health: dict[str, Any] = {"healthy": False, "error": "not checked"}
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"MinerU API exited with code {process.returncode}; inspect {stderr_path} and {stdout_path}"
            )
        last_health = health_payload(config)
        if last_health["healthy"]:
            return {"ok": True, "action": "started", **status_payload(config)}
        time.sleep(1.0)
    stop_service(config)
    raise TimeoutError(f"MinerU API did not become healthy within {timeout_seconds}s: {last_health}")


def stop_service(config: MinerUApiConfig) -> dict[str, Any]:
    record = read_pid_record(config)
    owned, pid, command_line = owned_process(config, record)
    if pid is None or command_line is None:
        config.pid_file.unlink(missing_ok=True)
        return {"ok": True, "action": "already-stopped", **status_payload(config)}
    if not owned:
        raise RuntimeError(f"Refusing to stop unverified PID {pid}: {command_line}")
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        if completed.returncode not in {0, 128}:
            raise RuntimeError(f"Failed to stop MinerU API PID {pid}: {completed.stdout} {completed.stderr}")
    else:
        os.kill(pid, 15)
    config.pid_file.unlink(missing_ok=True)
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline and health_payload(config, timeout_seconds=0.5)["healthy"]:
        time.sleep(0.5)
    return {"ok": True, "action": "stopped", "pid": pid, "configured_url": config.url}


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the shared localhost MinerU API service.")
    parser.add_argument("action", choices=("start", "status", "stop", "health", "init"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--start-timeout", type=float, default=120.0)
    args = parser.parse_args()
    try:
        config = load_mineru_api_config(args.config)
        if args.action == "start":
            payload = start_service(config, args.start_timeout)
        elif args.action == "stop":
            payload = stop_service(config)
        elif args.action == "health":
            payload = health_payload(config)
        elif args.action == "init":
            ensure_state_dirs(config)
            payload = {"ok": True, "action": "initialized", **status_payload(config)}
        else:
            payload = status_payload(config)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if args.action == "health":
            return 0 if payload.get("healthy") else 3
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
