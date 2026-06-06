from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


CONFIG_ENV_VAR = "EBOOK_CONVERTER_HTTP_CONFIG"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "http.env"


@dataclass(frozen=True)
class HttpConfig:
    scheme: str
    host: str
    port: int
    docker_host: str
    source: Path

    @property
    def local_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def docker_url(self) -> str:
        return f"{self.scheme}://host.docker.internal:{self.port}"


def load_http_config(config_path: str | Path | None = None) -> HttpConfig:
    path = Path(config_path or os.environ.get(CONFIG_ENV_VAR) or DEFAULT_CONFIG_PATH)
    values = read_env_file(path)
    scheme = config_value(values, "EBOOK_CONVERTER_HTTP_SCHEME", path)
    host = config_value(values, "EBOOK_CONVERTER_HTTP_HOST", path)
    docker_host = config_value(values, "EBOOK_CONVERTER_DOCKER_HTTP_HOST", path)
    port_text = config_value(values, "EBOOK_CONVERTER_HTTP_PORT", path)
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError(f"Invalid EBOOK_CONVERTER_HTTP_PORT in {path}: {port_text}") from exc
    if port <= 0 or port > 65535:
        raise ValueError(f"EBOOK_CONVERTER_HTTP_PORT must be 1-65535 in {path}: {port}")
    return HttpConfig(scheme=scheme, host=host, port=port, docker_host=docker_host, source=path)


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def config_value(values: dict[str, str], key: str, source: Path) -> str:
    value = os.environ.get(key) or values.get(key)
    if value:
        return value
    raise ValueError(f"Missing {key}; set it in {source}")


def default_http_url() -> str:
    return load_http_config().local_url
