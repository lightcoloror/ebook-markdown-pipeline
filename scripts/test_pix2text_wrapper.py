from __future__ import annotations

import subprocess
import sys
import tempfile
import importlib.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.returncode != 0 or "file_type=page" not in completed.stdout:
            raise RuntimeError(f"Pix2Text wrapper dry-run failed: {completed.returncode}\n{completed.stdout}")
        markdown = pix2text_wrapper.result_to_markdown(FakePage(), root / "raw")
        if "# fake" not in markdown or "正文" not in markdown:
            raise RuntimeError(f"Unexpected Pix2Text markdown normalization: {markdown}")
    print("Pix2Text wrapper contract test passed.")


if __name__ == "__main__":
    main()
