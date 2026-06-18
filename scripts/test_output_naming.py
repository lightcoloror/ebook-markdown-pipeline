from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    build_output_path,
    build_output_paths,
    clean_output_stem,
    strip_source_site_noise,
)


def source_site_noise() -> str:
    return ", ".join(["z-library" + ".sk", "1lib" + ".sk", "z-lib" + ".sk"])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-output-naming-") as tmp:
        root = Path(tmp)
        input_root = root / "input"
        output_root = root / "out"
        input_root.mkdir()
        output_root.mkdir()
        args = SimpleNamespace(output_format="markdown", output_name_suffix="")
        site_noise = source_site_noise()

        source = input_root / f"商业模式新生代 ({site_noise}).epub"
        source.write_text("fixture", encoding="utf-8")
        output = build_output_path(source, input_root, output_root, args)
        expected = output_root / "商业模式新生代.md"
        if output != expected:
            raise AssertionError(f"Expected source-site suffix to be stripped: {output} != {expected}")

        nested_dir = input_root / "nested"
        nested_dir.mkdir()
        nested = nested_dir / f"Book Title - {site_noise}.pdf"
        nested.write_text("fixture", encoding="utf-8")
        nested_output = build_output_path(nested, input_root, output_root, args)
        if nested_output != output_root / "nested" / "Book Title.md":
            raise AssertionError(f"Expected nested output leaf to be cleaned while preserving directories: {nested_output}")

        suffix_args = SimpleNamespace(output_format="markdown", output_name_suffix="20260618")
        versioned = build_output_path(source, input_root, output_root, suffix_args)
        if versioned.name != "商业模式新生代-20260618.md":
            raise AssertionError(f"Expected version suffix after cleaned stem: {versioned.name}")

        duplicate_sources = [
            input_root / f"Duplicate ({site_noise}).epub",
            input_root / "Duplicate.azw3",
        ]
        for item in duplicate_sources:
            item.write_text("fixture", encoding="utf-8")
        outputs = build_output_paths(duplicate_sources, input_root, output_root, args)
        names = {path.name for path in outputs.values()}
        if names != {"Duplicate.md", "Duplicate.azw3.md"}:
            raise AssertionError(f"Expected duplicate cleaned names to be disambiguated by source suffix: {names}")

        if strip_source_site_noise(site_noise) != "":
            raise AssertionError("A pure source-site stem should strip to empty before fallback naming.")
        if clean_output_stem(site_noise) != "converted-book":
            raise AssertionError("Empty cleaned output stem should fall back to converted-book.")
        if clean_output_stem(f"Book ({site_noise}).report") != "Book.report":
            raise AssertionError("Report stem should not keep a space before .report.")
        truncated = "Book (" + "z-library" + ".sk, 1l-8285d43007"
        if clean_output_stem(truncated) != "Book-8285d43007":
            raise AssertionError("Truncated source-site/hash remnants should be cleaned.")
        truncated_report = "Book (" + "z-library" + ".sk, z-l.report"
        if clean_output_stem(truncated_report) != "Book.report":
            raise AssertionError("Truncated z-l report remnants should be cleaned.")
        truncated_1li = "Book (" + "z-library" + ".sk, 1li-c56f34874d"
        if clean_output_stem(truncated_1li) != "Book-c56f34874d":
            raise AssertionError("Truncated 1li hash remnants should be cleaned.")
        truncated_z_library = "Book (" + "z-library" + "-25db2bd47c.quality"
        if clean_output_stem(truncated_z_library) != "Book-25db2bd47c.quality":
            raise AssertionError("Truncated z-library hash remnants should be cleaned.")
        truncated_z_li = "Book (" + "z-li" + "-20260604-100727-f7e80083fd"
        if clean_output_stem(truncated_z_li) != "Book-20260604-100727-f7e80083fd":
            raise AssertionError("Truncated z-li date/hash remnants should be cleaned.")
        truncated_z_library_dot = "Book (" + "z-library" + ".s-83ba7e7b1d"
        if clean_output_stem(truncated_z_library_dot) != "Book-83ba7e7b1d":
            raise AssertionError("Truncated z-library.s hash remnants should be cleaned.")

    print("Output naming smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
