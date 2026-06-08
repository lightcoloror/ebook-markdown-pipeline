from __future__ import annotations

import os
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = PROJECT_DIR / ".env"
LOADED_PROJECT_ENV_KEYS: set[str] = set()


def load_project_env(path: str | Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Load simple KEY=VALUE pairs from the project .env file.

    Existing process environment variables win by default, so values provided by
    the shell, CI, Docker, or an agent remain authoritative.
    """
    env_path = Path(path) if path else DEFAULT_ENV_PATH
    if not env_path.exists():
        return {}
    loaded: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parsed = parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        loaded[key] = value
        LOADED_PROJECT_ENV_KEYS.add(key)
    return loaded


def project_env_status(path: str | Path | None = None) -> dict[str, object]:
    env_path = Path(path) if path else DEFAULT_ENV_PATH
    return {
        "path": str(env_path),
        "exists": env_path.exists(),
        "loaded_keys": sorted(LOADED_PROJECT_ENV_KEYS),
    }


def parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.lower().startswith("export "):
        stripped = stripped[7:].strip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
        return None
    return key, unquote_env_value(value.strip())


def unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
