from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.ebook_converter_mcp import read_artifact  # noqa: E402

SCRIPT = Path(__file__).with_name("pix2text_image_to_md.py")
SPEC = importlib.util.spec_from_file_location("pix2text_image_to_md", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {SCRIPT}")
pix2text_wrapper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pix2text_wrapper)


class FakePage:
    def to_markdown(self, out_dir: Path, markdown_fn: str = "output.md") -> str:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / markdown_fn).write_text("# fake\n", encoding="utf-8")
        return "# fake\n\n正文"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pix2text-wrapper-test-") as tmp:
        root = Path(tmp)
        image = root / "sample.png"
        output = root / "sample.md"
        image.write_bytes(b"not-a-real-image-for-dry-run")
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--input",
                str(image),
                "--output",
                str(output),
                "--dry-run",
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.returncode != 0 or "file_type=page" not in completed.stdout or "formula-candidates.json" not in completed.stdout:
            raise RuntimeError(f"Pix2Text wrapper dry-run failed: {completed.returncode}\n{completed.stdout}")
        markdown = pix2text_wrapper.result_to_markdown(FakePage(), root / "raw")
        if "# fake" not in markdown or "正文" not in markdown:
            raise RuntimeError(f"Unexpected Pix2Text markdown normalization: {markdown}")
        assert_formula_candidates_contract(root, image, output)
    print("Pix2Text wrapper contract test passed.")


def assert_formula_candidates_contract(root: Path, image: Path, output: Path) -> None:
    blocks = [
        {"type": "text", "text": "where"},
        {"type": "embedding", "text": "x^2+y^2=z^2", "position": [[1, 2], [9, 2], [9, 5], [1, 5]], "score": 0.91},
        {"type": "isolated", "text": "\\int_0^1 x dx", "position": [[2, 8], [20, 8], [20, 14], [2, 14]], "score": 0.88},
    ]
    markdown = pix2text_wrapper.result_to_markdown(blocks, root / "raw")
    if "$x^2+y^2=z^2$" not in markdown or "\\int_0^1 x dx" not in markdown:
        raise RuntimeError(f"Expected formula-aware Pix2Text markdown rendering: {markdown}")

    artifact = pix2text_wrapper.write_formula_candidates(
        root / "formula-candidates.json",
        blocks,
        input_path=image,
        markdown_path=output,
        file_type="text_formula",
        markdown=markdown,
    )
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    formulas = payload["pages"][0]["formulas"]
    if payload.get("schema_version") != "formula-candidates-v1" or len(formulas) != 2:
        raise RuntimeError(f"Expected Pix2Text formula candidates payload: {payload}")
    if not formulas[0].get("bbox") or formulas[0].get("confidence") != 0.91:
        raise RuntimeError(f"Expected formula bbox/confidence evidence: {formulas}")

    readable = read_artifact({"path": str(artifact), "artifact_type": "formula_candidates_json"})
    summary = readable.get("summary") or {}
    if summary.get("kind") != "formula_candidates_json" or summary.get("formula_count") != 2 or summary.get("candidate_schema_known") is not True:
        raise RuntimeError(f"Expected readable formula candidates summary: {readable}")


if __name__ == "__main__":
    main()
