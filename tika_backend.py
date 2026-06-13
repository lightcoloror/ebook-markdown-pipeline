from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_TIKA_TIMEOUT_SECONDS = 20.0
DEFAULT_TEXT_SAMPLE_CHARS = 1200


def tika_server_url() -> str:
    return os.environ.get("EBOOK_CONVERTER_TIKA_SERVER_URL", "").strip().rstrip("/")


def tika_command_template() -> str:
    return os.environ.get("EBOOK_CONVERTER_TIKA_COMMAND", "").strip()


def tika_available() -> bool:
    return bool(tika_server_url() or tika_command_template())


def tika_health() -> dict[str, str]:
    server = tika_server_url()
    command = tika_command_template()
    if server:
        return {"status": "ok", "detail": f"Tika Server configured: {server}"}
    if command:
        return {"status": "ok", "detail": "Tika command template configured"}
    return {
        "status": "missing",
        "detail": "optional Tika inspect backend not configured; set EBOOK_CONVERTER_TIKA_SERVER_URL or EBOOK_CONVERTER_TIKA_COMMAND",
    }


def inspect_with_tika(
    source: Path,
    *,
    timeout_seconds: float = DEFAULT_TIKA_TIMEOUT_SECONDS,
    text_sample_chars: int = DEFAULT_TEXT_SAMPLE_CHARS,
) -> dict[str, Any]:
    source = Path(source)
    if not source.exists():
        return {"status": "missing_source", "tool": "tika", "source": str(source), "message": "source file does not exist"}
    server = tika_server_url()
    if server:
        return inspect_with_tika_server(source, server_url=server, timeout_seconds=timeout_seconds, text_sample_chars=text_sample_chars)
    command = tika_command_template()
    if command:
        return inspect_with_tika_command(source, command_template=command, timeout_seconds=timeout_seconds, text_sample_chars=text_sample_chars)
    return {
        "status": "missing_dependency",
        "tool": "tika",
        "source": str(source),
        "message": "Tika is not configured. Set EBOOK_CONVERTER_TIKA_SERVER_URL or EBOOK_CONVERTER_TIKA_COMMAND.",
    }


def inspect_with_tika_server(
    source: Path,
    *,
    server_url: str,
    timeout_seconds: float,
    text_sample_chars: int,
) -> dict[str, Any]:
    try:
        metadata_raw = put_tika_server(source, server_url=server_url, endpoint="/meta", accept="application/json", timeout_seconds=timeout_seconds)
        text = put_tika_server(source, server_url=server_url, endpoint="/tika", accept="text/plain", timeout_seconds=timeout_seconds)
        detected = put_tika_server(source, server_url=server_url, endpoint="/detect/stream", accept="text/plain", timeout_seconds=timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "tool": "tika-server",
            "source": str(source),
            "server_url": server_url,
            "message": str(exc),
        }
    metadata = parse_metadata_payload(metadata_raw)
    return normalize_tika_payload(
        source=source,
        tool="tika-server",
        metadata=metadata,
        text=text,
        detected_mime=detected.strip() or metadata_mime(metadata),
        text_sample_chars=text_sample_chars,
        extra={"server_url": server_url},
    )


def put_tika_server(source: Path, *, server_url: str, endpoint: str, accept: str, timeout_seconds: float) -> str:
    data = source.read_bytes()
    request = urllib.request.Request(
        f"{server_url}{endpoint}",
        data=data,
        method="PUT",
        headers={
            "Accept": accept,
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f'attachment; filename="{source.name}"',
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - local/user-configured URL.
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Tika server {endpoint} failed with HTTP {exc.code}: {body[:500]}") from exc


def inspect_with_tika_command(
    source: Path,
    *,
    command_template: str,
    timeout_seconds: float,
    text_sample_chars: int,
) -> dict[str, Any]:
    command_text = command_template.format(input=str(source))
    cmd = [part.strip('"') for part in shlex.split(command_text, posix=False)]
    if not cmd:
        return {"status": "missing_dependency", "tool": "tika-command", "source": str(source), "message": "empty Tika command template"}
    try:
        completed = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds if timeout_seconds > 0 else None,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "tool": "tika-command", "source": str(source), "message": str(exc)}
    stdout = completed.stdout or ""
    parsed = parse_command_payload(stdout)
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    text = str(parsed.get("text") or parsed.get("content") or "")
    if not text and not metadata:
        text = stdout
    payload = normalize_tika_payload(
        source=source,
        tool="tika-command",
        metadata=metadata,
        text=text,
        detected_mime=str(parsed.get("detected_mime") or parsed.get("mime") or metadata_mime(metadata)),
        text_sample_chars=text_sample_chars,
        extra={"returncode": completed.returncode},
    )
    if completed.returncode != 0:
        payload["status"] = "failed"
        payload["message"] = stdout[-1200:]
    return payload


def parse_command_payload(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_metadata_payload(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return {str(key): normalize_metadata_value(item) for key, item in parsed.items()}
    metadata: dict[str, Any] = {}
    for line in value.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        metadata[key.strip()] = raw.strip()
    return metadata


def normalize_metadata_value(value: Any) -> Any:
    if isinstance(value, list):
        if len(value) == 1:
            return normalize_metadata_value(value[0])
        return [normalize_metadata_value(item) for item in value]
    return value


def normalize_tika_payload(
    *,
    source: Path,
    tool: str,
    metadata: dict[str, Any],
    text: str,
    detected_mime: str,
    text_sample_chars: int,
    extra: dict[str, Any],
) -> dict[str, Any]:
    text = text or ""
    payload = {
        "status": "ok",
        "tool": tool,
        "source": str(source),
        "detected_mime": detected_mime.strip(),
        "metadata": sanitize_metadata(metadata),
        "text_chars": len(text),
        "text_sample": collapse_text_sample(text, text_sample_chars),
    }
    payload.update(extra)
    return payload


def metadata_mime(metadata: dict[str, Any]) -> str:
    for key in ("Content-Type", "content-type", "dc:format", "resourceName"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def sanitize_metadata(metadata: dict[str, Any], *, limit: int = 30) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key in sorted(metadata)[:limit]:
        value = metadata[key]
        if isinstance(value, str):
            clean[key] = value[:500]
        elif isinstance(value, (int, float, bool)) or value is None:
            clean[key] = value
        elif isinstance(value, list):
            clean[key] = [str(item)[:200] for item in value[:10]]
        else:
            clean[key] = str(value)[:500]
    return clean


def collapse_text_sample(text: str, limit: int) -> str:
    sample = re.sub(r"\s+", " ", text).strip()
    if limit <= 0:
        return ""
    return sample[:limit]
