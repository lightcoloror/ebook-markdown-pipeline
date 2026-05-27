from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render_item(item: dict[str, Any]) -> str:
    item_type = item.get("type")
    if item_type == "text":
        text = str(item.get("text", "")).strip()
        if not text:
            return ""
        level = item.get("text_level")
        if isinstance(level, int) and level > 0:
            level = max(1, min(level + 1, 6))
            return f"{'#' * level} {text}"
        return text
    if item_type == "image":
        path = item.get("img_path") or item.get("image_path")
        caption = item.get("img_caption") or item.get("caption") or ""
        if isinstance(caption, list):
            caption = " ".join(str(part) for part in caption)
        if path:
            return f"![{str(caption).strip()}]({path})"
        return str(caption).strip()
    if item_type == "table":
        body = item.get("table_body") or item.get("html") or item.get("text") or ""
        caption = item.get("table_caption") or item.get("caption") or ""
        parts = []
        if caption:
            if isinstance(caption, list):
                caption = " ".join(str(part) for part in caption)
            parts.append(str(caption).strip())
        if body:
            parts.append(str(body).strip())
        return "\n\n".join(part for part in parts if part)
    if item_type == "equation":
        text = item.get("text") or item.get("latex") or ""
        return f"$$\n{text}\n$$" if text else ""
    text = item.get("text") or item.get("content") or ""
    return str(text).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Render MinerU hybrid content list with source page headings.")
    parser.add_argument("--content-list", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()

    content = load_json(args.content_list)
    mapping = load_json(args.mapping)
    source_by_bundle_page = {
        int(item["bundle_page"]) - 1: int(item["source_page"])
        for item in mapping
    }

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in content:
        page_idx = item.get("page_idx")
        if isinstance(page_idx, int):
            grouped[page_idx].append(item)

    lines = [
        f"# {args.title}",
        "",
        "> 这是只对疑难页使用 MinerU hybrid-auto-engine 生成的补强版摘录；页码为原 PDF 物理页码。",
        "",
    ]
    for page_idx in sorted(grouped):
        source_page = source_by_bundle_page.get(page_idx, page_idx + 1)
        lines.extend([f"## 原 PDF 第 {source_page} 页", ""])
        for item in grouped[page_idx]:
            rendered = render_item(item)
            if rendered:
                lines.extend([rendered, ""])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
