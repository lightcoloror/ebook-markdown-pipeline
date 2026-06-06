from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from ebook_markdown_pipeline.http_config import load_http_config


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-http-config-") as tmpdir:
        config_path = Path(tmpdir) / "http.env"
        config_path.write_text(
            "\n".join(
                [
                    "EBOOK_CONVERTER_HTTP_SCHEME=http",
                    "EBOOK_CONVERTER_HTTP_HOST=127.0.0.1",
                    "EBOOK_CONVERTER_HTTP_PORT=9241",
                    "EBOOK_CONVERTER_DOCKER_HTTP_HOST=0.0.0.0",
                ]
            ),
            encoding="utf-8",
        )
        config = load_http_config(config_path)
        if config.local_url != "http://127.0.0.1:9241":
            raise AssertionError(f"Unexpected local URL: {config.local_url}")
        if config.docker_url != "http://host.docker.internal:9241":
            raise AssertionError(f"Unexpected Docker URL: {config.docker_url}")

        os.environ["EBOOK_CONVERTER_HTTP_PORT"] = "9351"
        try:
            override = load_http_config(config_path)
        finally:
            os.environ.pop("EBOOK_CONVERTER_HTTP_PORT", None)
        if override.local_url != "http://127.0.0.1:9351":
            raise AssertionError(f"Environment override did not apply: {override.local_url}")

        missing_path = Path(tmpdir) / "missing.env"
        try:
            load_http_config(missing_path)
        except ValueError as exc:
            if "Missing EBOOK_CONVERTER_HTTP_SCHEME" not in str(exc):
                raise AssertionError(f"Unexpected missing config error: {exc}") from exc
        else:
            raise AssertionError("Missing config file should fail instead of falling back to a hard-coded port.")

    print("HTTP config test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
