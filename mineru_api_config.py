from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_ENV_VAR = "EBOOK_CONVERTER_MINERU_API_CONFIG"
DEFAULT_CONFIG_PATH = PROJECT_DIR / "config" / "mineru-api.env"


@dataclass(frozen=True)
class MinerUApiConfig:
    scheme: str
    host: str
    port: int
    command: str
    state_root: Path
    source: Path

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def temp_root(self) -> Path:
        return self.state_root / "temp"

    @property
    def client_temp_root(self) -> Path:
        return self.state_root / "client-temp"

    @property
    def data_root(self) -> Path:
        return self.state_root / "data"

    @property
    def log_root(self) -> Path:
        return self.state_root / "logs"

    @property
    def run_root(self) -> Path:
        return self.state_root / "run"

    @property
    def pid_file(self) -> Path:
        return self.run_root / "mineru-api.pid.json"


def load_mineru_api_config(config_path: str | Path | None = None) -> MinerUApiConfig:
    path = Path(config_path or os.environ.get(CONFIG_ENV_VAR) or DEFAULT_CONFIG_PATH).resolve()
    values = read_env_file(path)
    scheme = config_value(values, "EBOOK_CONVERTER_MINERU_API_SCHEME", path).lower()
    host = config_value(values, "EBOOK_CONVERTER_MINERU_API_HOST", path)
    port_text = config_value(values, "EBOOK_CONVERTER_MINERU_API_PORT", path)
    command_text = config_value(values, "EBOOK_CONVERTER_MINERU_API_COMMAND", path)
    state_text = config_value(values, "EBOOK_CONVERTER_MINERU_API_STATE_ROOT", path)

    if scheme != "http":
        raise ValueError(f"MinerU API must use local HTTP in {path}: {scheme}")
    if host != "127.0.0.1":
        raise ValueError(f"MinerU API must bind only to 127.0.0.1 in {path}: {host}")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError(f"Invalid EBOOK_CONVERTER_MINERU_API_PORT in {path}: {port_text}") from exc
    if port <= 0 or port > 65535:
        raise ValueError(f"EBOOK_CONVERTER_MINERU_API_PORT must be 1-65535 in {path}: {port}")

    command = resolve_command(command_text)
    state_root = resolve_project_path(state_text)
    return MinerUApiConfig(
        scheme=scheme,
        host=host,
        port=port,
        command=command,
        state_root=state_root,
        source=path,
    )


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


def resolve_project_path(value: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    if path.is_absolute():
        return path.resolve()
    return (PROJECT_DIR / path).resolve()


def resolve_command(value: str) -> str:
    expanded = os.path.expandvars(os.path.expanduser(value.strip().strip('"')))
    candidate = Path(expanded)
    if candidate.is_absolute() and candidate.exists():
        return str(candidate.resolve())
    found = shutil.which(expanded)
    if found:
        return found
    installed = PROJECT_DIR.parent / "tools" / "mineru-venv" / "Scripts" / "mineru-api.exe"
    if expanded.lower() in {"mineru-api", "mineru-api.exe"} and installed.exists():
        return str(installed.resolve())
    return expanded


def default_mineru_api_url() -> str:
    return os.environ.get("EBOOK_CONVERTER_MINERU_API_URL") or load_mineru_api_config().url


def default_mineru_client_temp_root() -> Path:
    override = os.environ.get("EBOOK_CONVERTER_MINERU_CLIENT_TEMP_ROOT")
    return Path(override).resolve() if override else load_mineru_api_config().client_temp_root
