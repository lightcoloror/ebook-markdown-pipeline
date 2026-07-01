from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
HTTP_CLI_PATH = PROJECT_DIR / "examples" / "agent-calls" / "http_agent_batch_handoff.py"

sys.path.insert(0, str(PROJECT_DIR.parent))
from ebook_markdown_pipeline.ebook_converter_http import build_handler  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="agent-batch-handoff-http-") as tmp:
        root = Path(tmp)
        results_path = write_batch_fixture(root / "run-001")
        server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(""))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            wait_for_health(url)
            inspected = run_cli(url, "inspect", str(results_path))
            if inspected.get("schema_version") != "agent-batch-inspection-v1" or inspected.get("recommended_rerun", {}).get("action") != "rerun_failed_or_review":
                raise AssertionError(f"Unexpected HTTP inspect output: {inspected}")
            listed = run_cli(url, "list", str(root), "--max-depth", "2")
            if listed.get("schema_version") != "agent-batch-list-v1" or listed.get("count") != 1:
                raise AssertionError(f"Unexpected HTTP list output: {listed}")
            bundled = run_cli(url, "bundle", "--batch-results", str(results_path), "--output", str(root / "handoff"))
            if bundled.get("schema_version") != "agent-handoff-bundle-tool-v1" or bundled.get("bundle", {}).get("contract_validation", {}).get("ok") is not True:
                raise AssertionError(f"Unexpected HTTP bundle output: {bundled}")
            if not (root / "handoff" / "agent-handoff-bundle.json").exists() or not (root / "handoff" / "agent-handoff-bundle.md").exists():
                raise AssertionError(f"Expected HTTP bundle artifacts on disk: {bundled}")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    print("Agent batch handoff HTTP smoke test passed.")
    return 0


def write_batch_fixture(batch_dir: Path) -> Path:
    batch_dir.mkdir(parents=True)
    comparison_md = batch_dir / "benchmark-quality-comparison.md"
    comparison_json = batch_dir / "benchmark-quality-comparison.json"
    comparison_md.write_text("# Quality Comparison\n\nfailed", encoding="utf-8")
    comparison_json.write_text(
        json.dumps({"schema_version": "benchmark-quality-comparison-v1", "summary": {"status": "failed"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    results_path = batch_dir / "agent-batch-results.json"
    results_path.write_text(
        json.dumps(
            {
                "schema_version": "agent-batch-v1",
                "contract": agent_batch_contract(),
                "manifest": str(batch_dir / "manifest.json"),
                "created_at": "now",
                "summary": {"total": 1, "ok": 0, "review": 1, "hard_failed": 0},
                "selection": {"select": "all", "selected_count": 1, "manifest_job_count": 1},
                "artifact_summary": {"total": 0, "ok": 0, "failed": 0, "type_counts": {}, "failed_artifacts": []},
                "quality_comparison": {"status": "failed", "markdown": str(comparison_md), "json": str(comparison_json)},
                "next_actions": [
                    {
                        "action": "rerun_failed_or_review",
                        "select": "failed-or-review",
                        "rerun_mode": "recommended",
                        "powershell_command": "python runner.py --select failed-or-review --rerun-mode recommended",
                    }
                ],
                "results": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return results_path


def agent_batch_contract() -> dict:
    return {
        "name": "ebook-markdown-pipeline-agent-batch",
        "schema_version": "agent-batch-contract-v1",
        "payload_schema_version": "agent-batch-v1",
        "runner": "test_agent_batch_handoff_http.py",
        "capabilities": [
            "selection_summary",
            "artifact_summary",
            "handoff_next_actions",
            "attention_summary",
            "legacy_action_synthesis",
            "quality_comparison",
            "recommended_rerun",
        ],
        "required_fields": [
            "schema_version",
            "contract",
            "manifest",
            "created_at",
            "summary",
            "selection",
            "artifact_summary",
            "next_actions",
            "results",
        ],
    }


def wait_for_health(url: str) -> None:
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            tools_url = url.rstrip("/") + "/tools"
            with urlopen_local_aware(tools_url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("HTTP server did not expose /tools in time.")


def urlopen_local_aware(url: str, *, timeout: float):
    hostname = urllib.parse.urlparse(url).hostname or ""
    if hostname in {"127.0.0.1", "localhost", "::1"}:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(url, timeout=timeout)
    return urllib.request.urlopen(url, timeout=timeout)


def run_cli(url: str, *args: str) -> dict:
    env = os.environ.copy()
    env["NO_PROXY"] = "localhost,127.0.0.1,::1"
    env["no_proxy"] = "localhost,127.0.0.1,::1"
    completed = subprocess.run(
        [sys.executable, str(HTTP_CLI_PATH), "--url", url, *args],
        cwd=PROJECT_DIR,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
