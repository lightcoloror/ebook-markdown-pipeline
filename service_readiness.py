from __future__ import annotations

import socket
from dataclasses import asdict, dataclass
from typing import Any

from ebook_markdown_pipeline.http_config import HttpConfig, load_http_config


@dataclass(frozen=True)
class ListenerStatus:
    checked: bool
    listening: bool
    host: str
    port: int
    error: str | None = None


def check_tcp_listener(host: str, port: int, *, timeout_seconds: float = 0.5) -> ListenerStatus:
    connect_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.create_connection((connect_host, port), timeout=timeout_seconds):
            return ListenerStatus(checked=True, listening=True, host=connect_host, port=port)
    except OSError as exc:
        return ListenerStatus(
            checked=True,
            listening=False,
            host=connect_host,
            port=port,
            error=str(exc),
        )


def service_readiness_payload(
    *,
    config: HttpConfig | None = None,
    require_http: bool = False,
    check_listener: bool = True,
) -> dict[str, Any]:
    http_config = config or load_http_config()
    listener = (
        check_tcp_listener(http_config.host, http_config.port)
        if check_listener
        else ListenerStatus(checked=False, listening=False, host=http_config.host, port=http_config.port)
    )
    if listener.listening:
        status = "ready"
    elif require_http:
        status = "needs_manual_start"
    else:
        status = "stopped-by-design"
    return {
        "schema_version": "ebook-service-readiness-v1",
        "status": status,
        "http": {
            "mode": "on-demand",
            "auto_start": False,
            "configured_url": http_config.local_url,
            "docker_url": http_config.docker_url,
            "config_path": str(http_config.source),
            "listener": asdict(listener),
            "requires_manual_start": not listener.listening,
        },
        "preferred_entrypoints": ["mcp", "http", "cli", "desktop_ui"],
        "fallback": {
            "if_http_unavailable": "Use MCP stdio when available; otherwise use CLI or host-side agent batch handoff.",
            "docker_agents": "Start the HTTP bridge explicitly, then call host.docker.internal with the configured port.",
            "do_not_assume_port": "Read config/http.env or /health instead of hard-coding 8765 or any other port.",
        },
        "state_labels": ["ready", "stopped-by-design", "needs_manual_start", "degraded", "blocked"],
    }

