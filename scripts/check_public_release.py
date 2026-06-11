from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "public-release-check-v1"
MAX_PUBLIC_FILE_BYTES = 20 * 1024 * 1024

PRIVATE_PATTERNS = [
    "C:\\Users\\lightcolor",
    "D:\\downloads",
    "D:\\Baidu",
    "D:\\Umi-OCR",
    "z-library.sk",
    "1lib.sk",
    "z-lib.sk",
]
SECRET_PATTERNS = [
    "LOGSEQ_API_TOKEN",
    "GITHUB_TOKEN=",
    "GH_TOKEN=",
    "OPENAI_API_KEY=",
    "Bearer sk-",
    "ghp_",
    "github_pat_",
    "api_key\": \"sk-",
]
MODEL_CACHE_MARKERS = [
    ".mineru/",
    ".marker/",
    "models--",
    "huggingface/hub",
]


@dataclass
class Check:
    name: str
    ok: bool
    evidence: str
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "evidence": self.evidence, "details": self.details}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether the repository is safe enough for a public release.")
    parser.add_argument("--output", type=Path, help="Optional output directory for public-release-check.json/md.")
    parser.add_argument("--run-smoke", action="store_true", help="Run the minimal entrypoint smoke test as part of the release check.")
    args = parser.parse_args()

    files = tracked_files()
    checks = [
        check_required_docs(),
        check_quickstart_commands(),
        check_private_patterns(files),
        check_secret_patterns(files),
        check_model_cache_markers(files),
        check_large_files(files),
    ]
    if args.run_smoke:
        checks.append(run_minimal_smoke())

    payload = build_payload(checks)
    if args.output:
        write_reports(args.output, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0 if payload["summary"]["status"] == "passed" else 4


def tracked_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {completed.stderr}")
    return [PROJECT_DIR / line.strip() for line in completed.stdout.splitlines() if line.strip()]


def check_required_docs() -> Check:
    required = [
        "README.md",
        "docs/QUICKSTART.md",
        "docs/BACKENDS.md",
        "docs/INSTALLATION.md",
        "THIRD_PARTY_NOTICES.md",
        "docs/TOOL_CONTRACT.md",
    ]
    missing = [path for path in required if not (PROJECT_DIR / path).exists()]
    return Check("required public docs", not missing, ", ".join(required), f"missing={missing}" if missing else "all present")


def check_quickstart_commands() -> Check:
    readme = read_text(PROJECT_DIR / "README.md")
    quickstart = read_text(PROJECT_DIR / "docs" / "QUICKSTART.md")
    needles = [
        "git clone https://github.com/lightcoloror/ebook-markdown-pipeline.git",
        "python -m pip install -r requirements.txt",
        "python book_converter_ui.py",
        "python batch_convert_books.py",
        "python scripts\\run_quality_gate.py --profile minimal",
    ]
    missing = [needle for needle in needles if needle not in (readme + "\n" + quickstart)]
    return Check("quickstart commands documented", not missing, "README.md; docs/QUICKSTART.md", f"missing={missing}" if missing else "all present")


def check_private_patterns(files: list[Path]) -> Check:
    return scan_patterns("private path/sample markers", files, PRIVATE_PATTERNS)


def check_secret_patterns(files: list[Path]) -> Check:
    return scan_patterns("secret markers", files, SECRET_PATTERNS)


def check_model_cache_markers(files: list[Path]) -> Check:
    hits = [relative(path) for path in files if any(marker in relative(path).replace("\\", "/") for marker in MODEL_CACHE_MARKERS)]
    return Check("model cache files not tracked", not hits, "git ls-files", f"hits={hits[:20]}" if hits else "no tracked model cache files")


def check_large_files(files: list[Path]) -> Check:
    hits = []
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_PUBLIC_FILE_BYTES:
            hits.append({"path": relative(path), "bytes": size})
    return Check("large tracked files", not hits, f"threshold={MAX_PUBLIC_FILE_BYTES}", f"hits={hits[:20]}" if hits else "no large tracked files")


def scan_patterns(name: str, files: list[Path], patterns: list[str]) -> Check:
    hits = []
    for path in files:
        text = read_text(path)
        if text is None:
            continue
        for pattern in patterns:
            if pattern in text:
                hits.append({"path": relative(path), "pattern": pattern})
    return Check(name, not hits, "tracked text files", f"hits={hits[:20]}" if hits else "no hits")


def run_minimal_smoke() -> Check:
    completed = subprocess.run(
        [sys.executable, str(PROJECT_DIR / "scripts" / "test_minimal_entrypoints.py")],
        cwd=PROJECT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return Check(
        "minimal smoke",
        completed.returncode == 0,
        "python scripts/test_minimal_entrypoints.py",
        (completed.stdout + completed.stderr)[-2000:],
    )


def build_payload(checks: list[Check]) -> dict[str, Any]:
    failed = [check for check in checks if not check.ok]
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "status": "passed" if not failed else "failed",
            "check_count": len(checks),
            "failed_count": len(failed),
        },
        "checks": [check.to_dict() for check in checks],
    }


def write_reports(output: Path, payload: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "public-release-check.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Public Release Check",
        "",
        f"- Status: {payload['summary']['status']}",
        f"- Checks: {payload['summary']['check_count']}",
        f"- Failed: {payload['summary']['failed_count']}",
        "",
        "| Check | Status | Evidence | Details |",
        "| --- | --- | --- | --- |",
    ]
    for check in payload["checks"]:
        lines.append(f"| {check['name']} | {'ok' if check['ok'] else 'failed'} | `{check['evidence']}` | {markdown_cell(check.get('details') or '')} |")
    (output / "public-release-check.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_PUBLIC_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_DIR))
    except ValueError:
        return str(path)


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")[:240]


if __name__ == "__main__":
    raise SystemExit(main())
