from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "chunk-map-v1"
POLICY = {
    "mode": "metadata_only_no_platform_import",
    "source_markdown": "read_only",
    "text_storage": "line_ranges_and_short_previews_only_by_default",
    "purpose": "RAG/review planning side evidence; not final Markdown routing",
}


@dataclass
class Element:
    element_id: str
    type: str
    line_start: int
    line_end: int
    text_chars: int
    heading_level: int | None
    title: str
    section_path: list[str]
    page: int | None = None
    text_preview: str = ""


def write_chunk_map_artifacts(output: Path, payload: dict[str, Any]) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "chunk-map.json"
    markdown_path = output / "chunk-map.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    markdown_path.write_text(render_chunk_map_markdown(payload), encoding="utf-8", newline="\n")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def build_chunk_map(
    markdown_path: Path,
    *,
    structure_json: Path | None = None,
    max_chunk_chars: int = 1800,
    include_text_preview: bool = False,
) -> dict[str, Any]:
    text = markdown_path.read_text(encoding="utf-8", errors="replace")
    structure_payload = load_optional_json(structure_json)
    elements = parse_markdown_elements(text, include_text_preview=include_text_preview)
    chunks = chunk_by_title(elements, max_chunk_chars=max_chunk_chars)
    summary = summarize(elements, chunks, structure_payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "source_name": markdown_path.name,
        "source_path": str(markdown_path),
        "structure_report_name": structure_json.name if structure_json else "",
        "policy": POLICY,
        "parameters": {
            "max_chunk_chars": max_chunk_chars,
            "include_text_preview": include_text_preview,
        },
        "summary": summary,
        "elements": [element.__dict__ for element in elements],
        "chunks": chunks,
        "structure_evidence": structure_evidence_summary(structure_payload),
        "next_actions": next_actions(summary),
    }


def load_optional_json(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    if not path.exists() or not path.is_file():
        return {"missing": True, "path_name": path.name}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return {"invalid_json": str(exc), "path_name": path.name}


def parse_markdown_elements(text: str, *, include_text_preview: bool) -> list[Element]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    elements: list[Element] = []
    section_stack: list[tuple[int, str]] = []
    current_page: int | None = None
    block_start: int | None = None
    block_lines: list[str] = []
    in_code = False

    def flush_block(end_line: int) -> None:
        nonlocal block_start, block_lines
        if block_start is None or not any(line.strip() for line in block_lines):
            block_start = None
            block_lines = []
            return
        raw = "\n".join(block_lines).strip()
        element_type = classify_block(raw, in_code=False)
        elements.append(
            Element(
                element_id=f"e{len(elements) + 1:04d}",
                type=element_type,
                line_start=block_start,
                line_end=end_line,
                text_chars=len(raw),
                heading_level=None,
                title="",
                section_path=[title for _, title in section_stack],
                page=current_page,
                text_preview=preview(raw) if include_text_preview else "",
            )
        )
        block_start = None
        block_lines = []

    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                block_lines.append(line)
                flush_block(index)
                in_code = False
            else:
                flush_block(index - 1)
                in_code = True
                block_start = index
                block_lines = [line]
            continue
        if in_code:
            block_lines.append(line)
            continue
        page = parse_page_marker(stripped)
        if page is not None:
            flush_block(index - 1)
            current_page = page
            elements.append(
                Element(
                    element_id=f"e{len(elements) + 1:04d}",
                    type="page_break",
                    line_start=index,
                    line_end=index,
                    text_chars=0,
                    heading_level=None,
                    title=f"page {page}",
                    section_path=[title for _, title in section_stack],
                    page=current_page,
                )
            )
            continue
        heading = parse_heading(stripped)
        if heading:
            flush_block(index - 1)
            level, title = heading
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            section_stack.append((level, title))
            elements.append(
                Element(
                    element_id=f"e{len(elements) + 1:04d}",
                    type="title",
                    line_start=index,
                    line_end=index,
                    text_chars=len(title),
                    heading_level=level,
                    title=title,
                    section_path=[item_title for _, item_title in section_stack],
                    page=current_page,
                    text_preview=preview(title) if include_text_preview else "",
                )
            )
            continue
        if not stripped:
            flush_block(index - 1)
            continue
        if block_start is None:
            block_start = index
        block_lines.append(line)
    flush_block(len(lines))
    return elements


def parse_heading(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def parse_page_marker(line: str) -> int | None:
    patterns = [
        r"^<!--\s*page[:=]\s*(\d{1,5})\s*-->$",
        r"^\[page\s+(\d{1,5})\]$",
        r"^---\s*page\s+(\d{1,5})\s*---$",
    ]
    for pattern in patterns:
        match = re.match(pattern, line, re.I)
        if match:
            return int(match.group(1))
    return None


def classify_block(raw: str, *, in_code: bool = False) -> str:
    stripped = raw.strip()
    if in_code or stripped.startswith("```"):
        return "code_block"
    if stripped.startswith("|") and "\n|" in stripped:
        return "table"
    if all(re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line) for line in stripped.splitlines() if line.strip()):
        return "list"
    if re.match(r"^!\[.*?\]\(.+?\)", stripped):
        return "image"
    return "narrative_text"


def chunk_by_title(elements: list[Element], *, max_chunk_chars: int) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[Element] = []
    current_chars = 0

    def flush() -> None:
        nonlocal current, current_chars
        if not current:
            return
        first = current[0]
        last = current[-1]
        section_path = last.section_path or first.section_path
        chunks.append(
            {
                "chunk_id": f"c{len(chunks) + 1:04d}",
                "line_start": first.line_start,
                "line_end": last.line_end,
                "section_path": section_path,
                "page_start": first.page,
                "page_end": last.page,
                "element_ids": [item.element_id for item in current],
                "element_types": sorted({item.type for item in current}),
                "text_chars": current_chars,
                "strategy": "chunk_by_title_and_max_chars",
            }
        )
        current = []
        current_chars = 0

    for element in elements:
        if element.type == "page_break":
            continue
        if element.type == "title" and current:
            flush()
        if current and current_chars + max(element.text_chars, 1) > max_chunk_chars:
            flush()
        current.append(element)
        current_chars += max(element.text_chars, 1)
    flush()
    return chunks


def summarize(elements: list[Element], chunks: list[dict[str, Any]], structure_payload: dict[str, Any]) -> dict[str, Any]:
    element_counts: dict[str, int] = {}
    for item in elements:
        element_counts[item.type] = element_counts.get(item.type, 0) + 1
    repair = structure_payload.get("local_structure_repair") if isinstance(structure_payload.get("local_structure_repair"), dict) else structure_payload
    return {
        "element_count": len(elements),
        "chunk_count": len(chunks),
        "element_types": element_counts,
        "title_count": element_counts.get("title", 0),
        "page_break_count": element_counts.get("page_break", 0),
        "max_chunk_chars": max([int(item.get("text_chars") or 0) for item in chunks] or [0]),
        "structure_decision_count": int((repair or {}).get("decision_count") or 0),
        "structure_cleanup_decision_count": int((repair or {}).get("cleanup_decision_count") or 0),
        "needs_structure_review": element_counts.get("title", 0) == 0 or int((repair or {}).get("decision_count") or 0) > 20,
    }


def structure_evidence_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {"available": False}
    repair = payload.get("local_structure_repair") if isinstance(payload.get("local_structure_repair"), dict) else payload
    return {
        "available": True,
        "schema_version": payload.get("schema_version") or repair.get("schema_version"),
        "decision_count": repair.get("decision_count"),
        "action_counts": repair.get("action_counts") or {},
        "cleanup_counts": repair.get("cleanup_counts") or {},
        "candidate_sources": repair.get("candidate_sources") or {},
    }


def next_actions(summary: dict[str, Any]) -> list[dict[str, Any]]:
    actions = [
        {
            "action": "read_chunk_map",
            "tool": "read_artifact",
            "arguments": {"artifact_type": "chunk_map_json"},
            "safe_default": True,
            "destructive": False,
            "why": "inspect chunk boundaries before using chunks for retrieval or review",
        }
    ]
    if summary.get("needs_structure_review"):
        actions.append(
            {
                "action": "review_structure_before_chunk_use",
                "tool": "enhance_markdown_structure",
                "safe_default": True,
                "destructive": False,
                "why": "chunk map has weak or heavily repaired headings",
            }
        )
    return actions


def preview(value: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def render_chunk_map_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Chunk Map",
        "",
        f"- Schema: `{payload.get('schema_version')}`",
        f"- Source: `{payload.get('source_name', '')}`",
        f"- Elements: {summary.get('element_count', 0)}",
        f"- Chunks: {summary.get('chunk_count', 0)}",
        f"- Titles: {summary.get('title_count', 0)}",
        f"- Page breaks: {summary.get('page_break_count', 0)}",
        f"- Needs structure review: {summary.get('needs_structure_review', False)}",
        "",
        "| Chunk | Lines | Section | Types | Chars |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in payload.get("chunks") or []:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("chunk_id") or ""),
                    f"{item.get('line_start')}-{item.get('line_end')}",
                    escape_md(" > ".join(item.get("section_path") or [])),
                    escape_md(", ".join(item.get("element_types") or [])),
                    str(item.get("text_chars") or 0),
                ]
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n"


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
