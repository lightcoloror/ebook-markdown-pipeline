from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import fitz

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.ebook_converter_http import build_handler


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-benchmark-tools-") as tmp:
        root = Path(tmp)
        sample_root = root / "samples"
        sample_root.mkdir()
        txt = sample_root / "sample.txt"
        txt.write_text("# Benchmark\n\nThis is a benchmark text sample.", encoding="utf-8")
        pdf = sample_root / "sample.pdf"
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Benchmark PDF\nContract amount 300000")
        document.save(pdf)
        document.close()

        manifest = root / "samples.json"
        run_cmd("discover_benchmark_samples.py", str(sample_root), "--output", str(manifest), "--limit", "10")
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        if len(manifest_payload.get("samples", [])) < 2:
            raise RuntimeError(f"Expected discovered TXT and PDF samples: {manifest_payload}")

        run_dir = root / "run"
        run_cmd("run_benchmarks.py", "--manifest", str(manifest), "--output", str(run_dir), "--limit", "1", "--overwrite", "--skip-heavy")
        if not (run_dir / "benchmark-results.json").exists() or not (run_dir / "benchmark-summary.md").exists():
            raise RuntimeError("Benchmark runner did not write expected reports.")

        compare_dir = root / "compare"
        run_cmd("compare_pipelines.py", "--input", str(pdf), "--output", str(compare_dir), "--pipelines", "pymupdf4llm", "--overwrite")
        if not (compare_dir / "pipeline-comparison.json").exists() or not (compare_dir / "pipeline-comparison.md").exists():
            raise RuntimeError("Pipeline comparison did not write expected reports.")

        stress_manifest = root / "stress-samples.json"
        stress_manifest.write_text(
            json.dumps({"schema_version": "benchmark-samples-v1", "samples": [{"id": "sample-pdf", "path": str(pdf), "category": "pdf"}]}, indent=2),
            encoding="utf-8",
        )
        server = start_http_server()
        try:
            stress_dir = root / "stress"
            run_cmd(
                "stress_agent_http.py",
                "--url",
                f"http://127.0.0.1:{server.server_port}",
                "--manifest",
                str(stress_manifest),
                "--output",
                str(stress_dir),
                "--iterations",
                "1",
                "--concurrency",
                "1",
                "--timeout",
                "60",
                "--ocr",
                "never",
                "--pdf-pipeline-mode",
                "pymupdf4llm",
            )
            if not (stress_dir / "agent-stress-results.json").exists():
                raise RuntimeError("Agent stress test did not write expected report.")
        finally:
            server.shutdown()

    print("Benchmark tools smoke test passed.")
    return 0


def run_cmd(script: str, *args: str) -> None:
    subprocess.run([sys.executable, str(PROJECT_DIR / "scripts" / script), *args], check=True, cwd=PROJECT_DIR)


def start_http_server():
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(""))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=1).read()
            return server
        except Exception:
            time.sleep(0.1)
    server.shutdown()
    raise RuntimeError("HTTP server did not start")


if __name__ == "__main__":
    raise SystemExit(main())
