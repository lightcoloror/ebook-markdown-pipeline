from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "examples" / "agent-calls"))

from agent_call_helpers import run_material_flow  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="agent-call-helper-") as tmp:
        root = Path(tmp)
        visual_check = root / "archive" / "visual_check"
        visual_check.mkdir(parents=True)
        result_path = visual_check / "visual_check_result.json"
        result_path.write_text(json.dumps({"schema_version": 1, "status": "pending_visual_engine"}), encoding="utf-8")

        def fake_call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if name == "process_material":
                return {
                    "status": "routed",
                    "route": "process_web_archive",
                    "delegated": {
                        "status": "pending_visual_engine",
                        "artifacts": [{"type": "visual_check_json", "path": str(result_path)}],
                    },
                }
            if name == "read_artifact":
                return {
                    "path": arguments["path"],
                    "artifact_type": arguments.get("artifact_type"),
                    "json": json.loads(Path(arguments["path"]).read_text(encoding="utf-8")),
                }
            raise AssertionError(f"Unexpected tool call: {name}")

        result = run_material_flow(fake_call_tool, {"input": str(root / "archive"), "output": str(root / "out")})
        artifact = result.get("artifact") or {}
        if artifact.get("artifact_type") != "visual_check_json" or (artifact.get("json") or {}).get("schema_version") != 1:
            raise AssertionError(f"Expected synchronous visual_check_json artifact: {result}")
        if result.get("job") is not None or not result.get("result"):
            raise AssertionError(f"Expected synchronous delegated result without job: {result}")

    print("Agent call helper smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
