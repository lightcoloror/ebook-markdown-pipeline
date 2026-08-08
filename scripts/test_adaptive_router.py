from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))

from ebook_markdown_pipeline.adaptive_router import build_adaptive_routing_plan
from ebook_markdown_pipeline.ebook_converter_mcp import choose_pdf_pipeline_mode


def pdf_inspection(**overrides) -> dict:
    preflight = {
        "page_count": 100,
        "bookmark_count": 6,
        "scanned_likely": False,
        "complex_layout_likely": False,
        "presentation_like": False,
        "table_like_pages": 0,
    }
    preflight.update(overrides)
    return {
        "status": "ok",
        "input": "sample.pdf",
        "kind": "pdf",
        "preflight": preflight,
        "structure_strategy": {"confidence": "high"},
    }


def assert_action_contract(action: dict) -> None:
    assert action.get("tool"), action
    assert isinstance(action.get("arguments"), dict), action
    assert action.get("destructive") is False, action
    assert isinstance(action.get("safe_default"), bool), action


def main() -> int:
    balanced = build_adaptive_routing_plan(pdf_inspection(), output="out", routing_profile="balanced")
    assert balanced["schema_version"] == "adaptive-routing-plan-v1"
    assert balanced["primary"]["id"] == "pdf_mineru"
    assert balanced["winner_status"] == "provisional"
    assert balanced["sample_strategy"]["pages"] == sorted(balanced["sample_strategy"]["pages"])
    assert len(balanced["sample_strategy"]["pages"]) <= 8
    assert not any(item["remote"] for item in balanced["portfolio"])
    assert balanced["next_actions"][0]["safe_default"] is True
    fast = build_adaptive_routing_plan(pdf_inspection(), output="out", routing_profile="fast")
    assert fast["primary"]["id"] == "pdf_pymupdf4llm"
    fast_inspection = pdf_inspection()
    fast_inspection["adaptive_routing"] = fast
    assert choose_pdf_pipeline_mode(fast_inspection, "auto", routing_profile="fast") == "pymupdf4llm"
    assert choose_pdf_pipeline_mode(fast_inspection, "marker", routing_profile="fast") == "marker"

    for action in balanced["next_actions"]:
        assert_action_contract(action)

    difficult = build_adaptive_routing_plan(
        pdf_inspection(
            page_count=250,
            bookmark_count=0,
            scanned_likely=True,
            complex_layout_likely=True,
            presentation_like=True,
            table_like_pages=3,
        ),
        output="out",
        routing_profile="best_quality",
    )
    ids = {item["id"] for item in difficult["portfolio"]}
    assert difficult["decision_status"] == "probe_compare_required"
    assert difficult["primary"]["id"] == "pdf_mineru"
    assert difficult["sample_strategy"]["executor_status"] == "available_via_prepare_adaptive_pdf_probe"
    assert difficult["next_actions"][0]["tool"] == "prepare_adaptive_pdf_probe"
    assert difficult["next_actions"][0]["safe_default"] is True
    primary_action = next(item for item in difficult["next_actions"] if item.get("action") == "run_adaptive_primary_route")
    assert primary_action["safe_default"] is False
    assert {"pdf_pymupdf4llm", "pdf_umi", "pdf_docling", "online_only_vlm"}.issubset(ids)
    remote = next(item for item in difficult["portfolio"] if item["id"] == "online_only_vlm")
    assert remote["safe_default"] is False
    assert remote["arguments"]["execute"] is False
    assert difficult["safety"]["remote_calls_made"] is False
    assert difficult["safety"]["source_overwrite_allowed"] is False

    image = build_adaptive_routing_plan(
        {"status": "ok", "input": "screen.png", "kind": "image", "structure_strategy": {"confidence": "medium"}},
        output="out",
        routing_profile="best_quality",
    )
    assert image["primary"]["id"] == "image_book_auto"
    assert any(item["remote"] for item in image["portfolio"])
    assert all(not item["safe_default"] for item in image["portfolio"] if item["remote"])

    ebook = build_adaptive_routing_plan(
        {"status": "ok", "input": "book.epub", "kind": "pandoc", "extension": ".epub", "structure_strategy": {"confidence": "high"}},
        output="out",
    )
    assert ebook["primary"]["tool"] == "start_conversion"
    assert ebook["primary"]["arguments"]["document_pipeline_mode"] == "auto"

    unbound = build_adaptive_routing_plan(pdf_inspection(), routing_profile="fast")
    assert unbound["output_bound"] is False
    assert unbound["next_actions"][0]["safe_default"] is False

    unsupported = build_adaptive_routing_plan({"status": "unsupported", "input": "x.bin", "kind": "unsupported"})
    assert unsupported["decision_status"] == "unsupported"
    assert unsupported["portfolio"] == []
    assert unsupported["next_actions"] == []

    print("adaptive router tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
