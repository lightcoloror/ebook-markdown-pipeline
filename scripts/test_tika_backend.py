from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.document_inspector import inspect_document  # noqa: E402
from ebook_markdown_pipeline.tika_backend import inspect_with_tika, tika_health  # noqa: E402


def main() -> int:
    old_command = os.environ.get("EBOOK_CONVERTER_TIKA_COMMAND")
    old_server = os.environ.get("EBOOK_CONVERTER_TIKA_SERVER_URL")
    try:
        os.environ.pop("EBOOK_CONVERTER_TIKA_COMMAND", None)
        os.environ.pop("EBOOK_CONVERTER_TIKA_SERVER_URL", None)
        missing = tika_health()
        if missing.get("status") != "missing":
            raise AssertionError(f"Tika should be optional when not configured: {missing}")

        with tempfile.TemporaryDirectory(prefix="ebook-tika-backend-") as tmp:
            root = Path(tmp)
            source = root / "sample.unknown"
            source.write_text("hello from a broad format", encoding="utf-8")
            fake = root / "fake_tika.py"
            fake.write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "import json, sys",
                        "path = sys.argv[1]",
                        "print(json.dumps({",
                        "  'detected_mime': 'text/x-custom',",
                        "  'metadata': {'Content-Type': 'text/x-custom', 'resourceName': path},",
                        "  'text': 'Extracted Tika text from ' + path,",
                        "}, ensure_ascii=False))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            os.environ["EBOOK_CONVERTER_TIKA_COMMAND"] = f'"{sys.executable}" "{fake}" "{{input}}"'

            payload = inspect_with_tika(source)
            if payload.get("status") != "ok" or payload.get("detected_mime") != "text/x-custom":
                raise AssertionError(f"Expected fake Tika payload: {payload}")
            if payload.get("text_chars", 0) <= 0 or "Extracted Tika text" not in payload.get("text_sample", ""):
                raise AssertionError(f"Expected Tika text sample: {payload}")

            inspected = inspect_document(source, use_tika=True)
            if inspected.get("kind") != "tika_inspected" or inspected.get("recommendation") != "manual_tika_text_review":
                raise AssertionError(f"Unsupported extension should expose Tika inspect evidence: {json.dumps(inspected, ensure_ascii=False)}")
            if (inspected.get("tika") or {}).get("status") != "ok":
                raise AssertionError(f"Expected embedded Tika result: {inspected}")

            txt = root / "sample.txt"
            txt.write_text("plain supported text", encoding="utf-8")
            supported = inspect_document(txt, use_tika=True)
            if supported.get("kind") != "pandoc" or (supported.get("tika") or {}).get("status") != "ok":
                raise AssertionError(f"Supported documents should optionally include Tika evidence: {supported}")
    finally:
        restore_env("EBOOK_CONVERTER_TIKA_COMMAND", old_command)
        restore_env("EBOOK_CONVERTER_TIKA_SERVER_URL", old_server)

    print("Tika backend inspect test passed.")
    return 0


def restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    raise SystemExit(main())
