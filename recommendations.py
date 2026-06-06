from __future__ import annotations

from pathlib import Path
from typing import Any


def recommended_action_for_plan(plan: Any) -> str:
    output = Path(str(getattr(plan, "output", "") or ""))
    if output.exists():
        return "跳过或续跑 / Skip or Resume"
    detected_format = str(getattr(plan, "detected_format", "") or "").upper()
    pipeline = str(getattr(plan, "pipeline", "") or "").lower()
    if detected_format == "PDF" and "mineru" in pipeline:
        return "直接转换，长任务 / Convert, long task"
    return "直接转换 / Convert"
