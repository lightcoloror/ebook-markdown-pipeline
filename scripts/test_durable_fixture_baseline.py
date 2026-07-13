from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from generate_quality_fixtures import write_office_fixture  # noqa: E402
from run_durable_fixture_baseline import baseline_case_specs  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="durable-fixture-baseline-") as tmp:
        root = Path(tmp)
        docx = root / "office" / "sample.docx"
        write_office_fixture(docx)
        if not docx.is_file():
            raise AssertionError("Expected synthetic Office fixture")
        with zipfile.ZipFile(docx) as archive:
            names = set(archive.namelist())
            required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml"}
            if not required.issubset(names):
                raise AssertionError(f"Incomplete DOCX fixture: {names}")
            document = archive.read("word/document.xml").decode("utf-8")
            if "Office Fixture" not in document or "private documents" not in document:
                raise AssertionError("Expected synthetic-only DOCX content")

        specs = baseline_case_specs(root)
        kinds = {str(item["kind"]) for item in specs}
        expected = {"epub", "text_pdf", "complex_pdf", "office", "image_set"}
        if kinds != expected or len(specs) != 5:
            raise AssertionError(f"Expected five durable fixture kinds: {specs}")
        for item in specs:
            source = Path(item["source"])
            if root not in source.parents:
                raise AssertionError(f"Fixture escaped synthetic root: {source}")

    print("Durable fixture baseline contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
