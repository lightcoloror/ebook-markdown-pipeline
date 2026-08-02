from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path
from uuid import uuid4

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import ebook_converter_mcp as mcp  # noqa: E402


def main() -> int:
    output = PROJECT_DIR / f".tmp-online-agent-test-{uuid4().hex[:8]}"
    try:
        schemas = {item["name"]: item for item in mcp.tool_schemas()}
        if "start_online_conversion" not in schemas:
            raise AssertionError("MCP schema is missing start_online_conversion.")
        modes = schemas["process_material"]["inputSchema"]["properties"]["model_mode"]["enum"]
        if "online_only" not in modes:
            raise AssertionError(f"process_material does not advertise online_only: {modes}")
        online_properties = schemas["start_online_conversion"]["inputSchema"]["properties"]
        if online_properties.get("vlm_mode", {}).get("enum") != ["auto", "always", "never"]:
            raise AssertionError(f"start_online_conversion is missing stable VLM controls: {online_properties}")

        source = PROJECT_DIR / "benchmarks" / "fixtures" / "generated" / "images" / "ocr" / "english.png"
        rejected = mcp.start_online_conversion(
            {
                "input": str(source),
                "output": str(output / "rejected"),
                "provider_mode": "vkp_shared",
                "execute": True,
                "max_estimated_cost_usd": 0.1,
            }
        )
        if rejected.get("code") != "data_export_confirmation_required":
            raise AssertionError(f"Remote agent call did not fail closed: {rejected}")

        routed = mcp.process_material(
            {
                "input": str(source),
                "output": str(output / "fake"),
                "model_mode": "online_only",
                "provider_mode": "fake",
                "execute": True,
                "max_estimated_cost_usd": 0.01,
            }
        )
        if routed.get("route") != "start_online_conversion" or not routed.get("job_id"):
            raise AssertionError(f"process_material did not route to online-only job: {routed}")
        job_id = routed["job_id"]
        status = {}
        for _ in range(100):
            status = mcp.get_job_status({"job_id": job_id})
            if status.get("status") != "running":
                break
            time.sleep(0.05)
        if status.get("status") != "done" or not status.get("artifacts"):
            raise AssertionError(f"Online-only MCP job did not finish with artifacts: {status}")
        first_result = next((item for item in status.get("results") or [] if isinstance(item, dict)), {})
        vlm_stage = next((item for item in first_result.get("stages") or [] if item.get("stage") == "vlm_layout"), {})
        if vlm_stage.get("status") != "ok" or vlm_stage.get("selected_count") != 1:
            raise AssertionError(f"Agent online-only job did not preserve the VLM stage evidence: {vlm_stage}")
        print("Online-only Agent contract test passed.")
        return 0
    finally:
        shutil.rmtree(output, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
