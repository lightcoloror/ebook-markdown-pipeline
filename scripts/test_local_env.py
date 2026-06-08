from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.local_env import load_project_env, parse_env_line  # noqa: E402


def main() -> int:
    assert_parse_env_line()
    assert_load_project_env()
    print("Local env loader smoke test passed.")
    return 0


def assert_parse_env_line() -> None:
    if parse_env_line("# comment") is not None:
        raise AssertionError("Comments should be ignored.")
    if parse_env_line("export EBOOK_CONVERTER_TOOL_CACHE=\"C:\\tools\"") != ("EBOOK_CONVERTER_TOOL_CACHE", "C:\\tools"):
        raise AssertionError("Expected export and quoted value parsing.")
    if parse_env_line("BAD-NAME=value") is not None:
        raise AssertionError("Invalid keys should be ignored.")


def assert_load_project_env() -> None:
    with tempfile.TemporaryDirectory(prefix="ebook-local-env-") as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "# local config",
                    "EBOOK_CONVERTER_TOOL_CACHE=C:\\example-tools",
                    "EBOOK_CONVERTER_UMI_DIR='C:\\Umi-OCR'",
                    "EBOOK_CONVERTER_VLM_PYTHON=C:\\Python\\python.exe",
                    "EBOOK_CONVERTER_PADDLEOCR_COMMAND=paddleocr",
                    "EXISTING_VALUE=from-file",
                ]
            ),
            encoding="utf-8",
        )
        keys = [
            "EBOOK_CONVERTER_TOOL_CACHE",
            "EBOOK_CONVERTER_UMI_DIR",
            "EBOOK_CONVERTER_VLM_PYTHON",
            "EBOOK_CONVERTER_PADDLEOCR_COMMAND",
            "EXISTING_VALUE",
        ]
        old_values = {key: os.environ.get(key) for key in keys}
        try:
            os.environ["EXISTING_VALUE"] = "from-env"
            loaded = load_project_env(env_path)
            if loaded.get("EBOOK_CONVERTER_TOOL_CACHE") != "C:\\example-tools":
                raise AssertionError(f"Expected tool cache to load: {loaded}")
            if loaded.get("EBOOK_CONVERTER_UMI_DIR") != "C:\\Umi-OCR":
                raise AssertionError(f"Expected quoted Umi path to load: {loaded}")
            if loaded.get("EBOOK_CONVERTER_VLM_PYTHON") != "C:\\Python\\python.exe":
                raise AssertionError(f"Expected VLM Python to load: {loaded}")
            if loaded.get("EBOOK_CONVERTER_PADDLEOCR_COMMAND") != "paddleocr":
                raise AssertionError(f"Expected PaddleOCR command to load: {loaded}")
            if os.environ.get("EXISTING_VALUE") != "from-env" or "EXISTING_VALUE" in loaded:
                raise AssertionError(f"Existing environment values must win by default: {loaded}")
            override_loaded = load_project_env(env_path, override=True)
            if os.environ.get("EXISTING_VALUE") != "from-file" or override_loaded.get("EXISTING_VALUE") != "from-file":
                raise AssertionError(f"Override mode should replace values: {override_loaded}")
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
