from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.environment_report import export_environment_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export reproducible environment diagnostics for ebook-markdown-pipeline.")
    parser.add_argument("--input", type=Path, default=None, help="Optional input path used to scope required dependencies.")
    parser.add_argument("--output", type=Path, required=True, help="Directory where environment-report.json/md will be written.")
    parser.add_argument("--recursive", action="store_true", help="Scan input recursively when --input is a directory.")
    parser.add_argument("--include-hidden", action="store_true", help="Include hidden files while scanning input.")
    args = parser.parse_args()

    payload = export_environment_report(
        args.input,
        args.output,
        recursive=args.recursive,
        include_hidden=args.include_hidden,
    )
    print(payload["markdown_report"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
