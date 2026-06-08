from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class HeadingDecision:
    line_number: int
    original: str
    repaired: str
    level: int
    kind: str
    parent: str
    reason: str
    signals: list[str]


@dataclass
class HeadingCandidate:
    title: str
    level: int | None = None
    source: str = ""
    page: int | None = None
    bbox: list[float] | None = None
    font_size: float | None = None
    font: str = ""
    score: float = 0.0
    reason: str = ""


@dataclass
class StructureRepairResult:
    markdown: str
    decisions: list[HeadingDecision]
    candidates: list[HeadingCandidate] | None = None

    def report(self) -> dict[str, Any]:
        candidates = self.candidates or []
        source_counts: dict[str, int] = {}
        for item in candidates:
            source_counts[item.source or "unknown"] = source_counts.get(item.source or "unknown", 0) + 1
        return {
            "schema_version": "structure-repair-v1",
            "grammar": "chapter_section_article_clause_item_subitem",
            "decision_count": len(self.decisions),
            "candidate_count": len(candidates),
            "candidate_sources": source_counts,
            "candidate_samples": [asdict(item) for item in candidates[:20]],
            "inferred_outline": build_markdown_outline(self.markdown),
            "decisions": [asdict(item) for item in self.decisions],
        }


def repair_markdown_structure(
    text: str,
    *,
    source_kind: str = "",
    heading_candidates: list[HeadingCandidate | dict[str, Any]] | None = None,
) -> StructureRepairResult:
    """Repair conservative heading hierarchy for structured Chinese clauses.

    The first implementation focuses on contract/regulation-style numbering:
    chapter/section headings are usually already present, `第X条 ...` becomes
    an article heading, and `（一）...` becomes a child of the latest article.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    repaired: list[str] = []
    decisions: list[HeadingDecision] = []
    normalized_candidates = [normalize_heading_candidate(item) for item in (heading_candidates or [])]
    candidate_map = build_heading_candidate_map(normalized_candidates)
    current_section = ""
    current_article = ""
    current_clause = ""
    current_item = ""
    for idx, line in enumerate(lines):
        stripped = line.strip()
        existing = parse_existing_heading(stripped)
        if existing:
            level, title = existing
            if is_chapter_heading(title) or is_section_heading(title):
                candidate = candidate_for_title(candidate_map, title)
                level_target = 1 if is_chapter_heading(title) else 2
                repaired_line = f"{'#' * level_target} {title}"
                current_section = title
                current_article = ""
                current_clause = ""
                current_item = ""
                repaired.append(repaired_line)
                if level != level_target or line.strip() != repaired_line:
                    decisions.append(
                        HeadingDecision(
                            line_number=idx + 1,
                            original=line,
                            repaired=repaired_line,
                            level=level_target,
                            kind="chapter" if level_target == 1 else "section",
                            parent="",
                            reason=f"`{title}` normalized to {'#' * level_target} because it matches chapter/section numbering.",
                            signals=[
                                "domain_grammar:chapter_or_section",
                                "normalized_existing_heading",
                                *candidate_signals(candidate),
                            ],
                        )
                    )
                continue
            if is_article_heading(title):
                candidate = candidate_for_title(candidate_map, title)
                repaired_line = f"### {title}"
                current_article = title
                current_clause = ""
                current_item = ""
                repaired.append(repaired_line)
                if level != 3 or line.strip() != repaired_line:
                    decisions.append(
                        HeadingDecision(
                            line_number=idx + 1,
                            original=line,
                            repaired=repaired_line,
                            level=3,
                            kind="article",
                            parent=current_section,
                            reason=(
                                f"`{title}` normalized to ### because it matches 第X条 article numbering"
                                + (f" under section `{current_section}`." if current_section else ".")
                            ),
                            signals=["domain_grammar:article", "normalized_existing_heading", *candidate_signals(candidate)],
                        )
                    )
                continue
            if is_parenthesized_clause_heading(title):
                candidate = candidate_for_title(candidate_map, title)
                level_target = 4 if current_article else 3
                repaired_line = f"{'#' * level_target} {title}"
                current_clause = title
                current_item = ""
                repaired.append(repaired_line)
                if level != level_target or line.strip() != repaired_line:
                    decisions.append(
                        HeadingDecision(
                            line_number=idx + 1,
                            original=line,
                            repaired=repaired_line,
                            level=level_target,
                            kind="parenthesized_clause",
                            parent=current_article or current_section,
                            reason=(
                                f"`{title}` normalized to {'#' * level_target} because it matches Chinese parenthesized numbering"
                                + (f" and nearest article parent is `{current_article}`." if current_article else ".")
                            ),
                            signals=[
                                "domain_grammar:parenthesized_clause",
                                "normalized_existing_heading",
                                "nearest_parent:article" if current_article else "nearest_parent:section_or_none",
                                *candidate_signals(candidate),
                            ],
                        )
                    )
                continue
            if is_numeric_item_heading(title):
                candidate = candidate_for_title(candidate_map, title)
                level_target = 5 if current_clause else 4
                repaired_line = f"{'#' * level_target} {title}"
                current_item = title
                repaired.append(repaired_line)
                if level != level_target or line.strip() != repaired_line:
                    decisions.append(
                        HeadingDecision(
                            line_number=idx + 1,
                            original=line,
                            repaired=repaired_line,
                            level=level_target,
                            kind="numeric_item",
                            parent=current_clause or current_article or current_section,
                            reason=(
                                f"`{title}` normalized to {'#' * level_target} because it matches numeric item numbering"
                                + (f" under clause `{current_clause}`." if current_clause else ".")
                            ),
                            signals=[
                                "domain_grammar:numeric_item",
                                "normalized_existing_heading",
                                "nearest_parent:parenthesized_clause" if current_clause else "nearest_parent:article_or_section",
                                *candidate_signals(candidate),
                            ],
                        )
                    )
                continue
            if is_parenthesized_digit_heading(title):
                candidate = candidate_for_title(candidate_map, title)
                level_target = 6 if current_item or current_clause else 4
                repaired_line = f"{'#' * level_target} {title}"
                repaired.append(repaired_line)
                if level != level_target or line.strip() != repaired_line:
                    decisions.append(
                        HeadingDecision(
                            line_number=idx + 1,
                            original=line,
                            repaired=repaired_line,
                            level=level_target,
                            kind="parenthesized_digit_item",
                            parent=current_item or current_clause or current_article or current_section,
                            reason=(
                                f"`{title}` normalized to {'#' * level_target} because it matches parenthesized digit numbering"
                                + (f" under item `{current_item}`." if current_item else ".")
                            ),
                            signals=[
                                "domain_grammar:parenthesized_digit_item",
                                "normalized_existing_heading",
                                "nearest_parent:numeric_item_or_clause" if (current_item or current_clause) else "nearest_parent:article_or_section",
                                *candidate_signals(candidate),
                            ],
                        )
                    )
                continue
            if level <= 2:
                current_section = title
                current_article = ""
                current_clause = ""
                current_item = ""
            candidate = candidate_for_title(candidate_map, title)
            if candidate and candidate_signals(candidate):
                # Existing headings are kept as-is, but the report should still
                # expose external evidence when a parser/PDF outline agreed.
                decisions.append(
                    HeadingDecision(
                        line_number=idx + 1,
                        original=line,
                        repaired=line,
                        level=level,
                        kind="existing_heading_with_signal",
                        parent=current_section,
                        reason=f"`{title}` kept as existing heading with external structure evidence.",
                        signals=["existing_heading", *candidate_signals(candidate)],
                    )
                )
            repaired.append(line)
            continue

        if should_promote_chapter_or_section_heading(lines, idx):
            candidate = candidate_for_title(candidate_map, stripped)
            level = 1 if is_chapter_heading(stripped) else 2
            repaired_line = f"{'#' * level} {stripped}"
            current_section = stripped
            current_article = ""
            current_clause = ""
            current_item = ""
            repaired.append(repaired_line)
            decisions.append(
                HeadingDecision(
                    line_number=idx + 1,
                    original=line,
                    repaired=repaired_line,
                    level=level,
                    kind="chapter" if level == 1 else "section",
                    parent="",
                    reason=f"`{stripped}` promoted to {'#' * level} because it matches chapter/section numbering.",
                    signals=[
                        "domain_grammar:chapter_or_section",
                        f"source_kind:{source_kind}" if source_kind else "source_kind:unknown",
                        *candidate_signals(candidate),
                    ],
                )
            )
            continue

        if should_promote_article_heading(lines, idx):
            candidate = candidate_for_title(candidate_map, stripped)
            repaired_line = f"### {stripped}"
            current_article = stripped
            current_clause = ""
            current_item = ""
            repaired.append(repaired_line)
            decisions.append(
                HeadingDecision(
                    line_number=idx + 1,
                    original=line,
                    repaired=repaired_line,
                    level=3,
                    kind="article",
                    parent=current_section,
                    reason=(
                        f"`{stripped}` promoted to ### because it matches 第X条 article numbering"
                        + (f" under section `{current_section}`." if current_section else ".")
                    ),
                    signals=[
                        "domain_grammar:article",
                        f"source_kind:{source_kind}" if source_kind else "source_kind:unknown",
                        *candidate_signals(candidate),
                    ],
                )
            )
            continue

        if should_promote_parenthesized_heading(lines, idx):
            candidate = candidate_for_title(candidate_map, stripped)
            level = 4 if current_article else 3
            repaired_line = f"{'#' * level} {stripped}"
            parent = current_article or current_section
            current_clause = stripped
            current_item = ""
            repaired.append(repaired_line)
            decisions.append(
                HeadingDecision(
                    line_number=idx + 1,
                    original=line,
                    repaired=repaired_line,
                    level=level,
                    kind="parenthesized_clause",
                    parent=parent,
                    reason=(
                        f"`{stripped}` set to {'#' * level} because it matches Chinese parenthesized numbering"
                        + (f" and nearest article parent is `{current_article}`." if current_article else ".")
                    ),
                    signals=[
                        "domain_grammar:parenthesized_clause",
                        "nearest_parent:article" if current_article else "nearest_parent:section_or_none",
                        f"source_kind:{source_kind}" if source_kind else "source_kind:unknown",
                        *candidate_signals(candidate),
                    ],
                )
            )
            continue

        if should_promote_numeric_item_heading(lines, idx):
            candidate = candidate_for_title(candidate_map, stripped)
            level = 5 if current_clause else 4
            repaired_line = f"{'#' * level} {stripped}"
            parent = current_clause or current_article or current_section
            current_item = stripped
            repaired.append(repaired_line)
            decisions.append(
                HeadingDecision(
                    line_number=idx + 1,
                    original=line,
                    repaired=repaired_line,
                    level=level,
                    kind="numeric_item",
                    parent=parent,
                    reason=(
                        f"`{stripped}` set to {'#' * level} because it matches numeric item numbering"
                        + (f" and nearest clause parent is `{current_clause}`." if current_clause else ".")
                    ),
                    signals=[
                        "domain_grammar:numeric_item",
                        "nearest_parent:parenthesized_clause" if current_clause else "nearest_parent:article_or_section",
                        f"source_kind:{source_kind}" if source_kind else "source_kind:unknown",
                        *candidate_signals(candidate),
                    ],
                )
            )
            continue

        if should_promote_parenthesized_digit_heading(lines, idx):
            candidate = candidate_for_title(candidate_map, stripped)
            level = 6 if current_item or current_clause else 4
            repaired_line = f"{'#' * level} {stripped}"
            parent = current_item or current_clause or current_article or current_section
            repaired.append(repaired_line)
            decisions.append(
                HeadingDecision(
                    line_number=idx + 1,
                    original=line,
                    repaired=repaired_line,
                    level=level,
                    kind="parenthesized_digit_item",
                    parent=parent,
                    reason=(
                        f"`{stripped}` set to {'#' * level} because it matches parenthesized digit numbering"
                        + (f" and nearest item parent is `{current_item}`." if current_item else ".")
                    ),
                    signals=[
                        "domain_grammar:parenthesized_digit_item",
                        "nearest_parent:numeric_item_or_clause" if (current_item or current_clause) else "nearest_parent:article_or_section",
                        f"source_kind:{source_kind}" if source_kind else "source_kind:unknown",
                        *candidate_signals(candidate),
                    ],
                )
            )
            continue

        candidate = candidate_for_title(candidate_map, stripped)
        if candidate and should_promote_external_candidate(lines, idx, candidate):
            level = normalized_candidate_level(candidate)
            repaired_line = f"{'#' * level} {stripped}"
            parent = current_section if level >= 3 else ""
            if level <= 2:
                current_section = stripped
                current_article = ""
            repaired.append(repaired_line)
            decisions.append(
                HeadingDecision(
                    line_number=idx + 1,
                    original=line,
                    repaired=repaired_line,
                    level=level,
                    kind="external_candidate",
                    parent=parent,
                    reason=f"`{stripped}` promoted to {'#' * level} from external heading candidate evidence.",
                    signals=candidate_signals(candidate),
                )
            )
            continue

        repaired.append(line)
    return StructureRepairResult(markdown="\n".join(repaired), decisions=decisions, candidates=normalized_candidates)


def parse_existing_heading(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def build_markdown_outline(text: str) -> list[dict[str, Any]]:
    """Build a compact heading tree view from repaired Markdown.

    The repair decisions explain why individual lines changed; this outline
    makes the resulting hierarchy auditable by agents and humans without
    reparsing the Markdown themselves.
    """
    stack: list[dict[str, Any]] = []
    outline: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        parsed = parse_existing_heading(line.strip())
        if not parsed:
            continue
        level, title = parsed
        while stack and int(stack[-1]["level"]) >= level:
            stack.pop()
        parent = str(stack[-1]["title"]) if stack else ""
        path = [str(item["title"]) for item in stack] + [title]
        node = {
            "line_number": line_number,
            "level": level,
            "title": title,
            "parent": parent,
            "path": path,
        }
        outline.append(node)
        stack.append(node)
    return outline


def should_promote_article_heading(lines: list[str], idx: int) -> bool:
    line = lines[idx].strip()
    if not line or line.startswith(("#", "-", "*", ">", "|", "<!--")):
        return False
    if len(line) > 160:
        return False
    if not is_article_heading(line):
        return False
    return is_blank_separated(lines, idx)


def should_promote_chapter_or_section_heading(lines: list[str], idx: int) -> bool:
    line = lines[idx].strip()
    if not line or line.startswith(("#", "-", "*", ">", "|", "<!--")):
        return False
    if len(line) > 100:
        return False
    if not (is_chapter_heading(line) or is_section_heading(line)):
        return False
    return is_blank_separated(lines, idx)


def should_promote_parenthesized_heading(lines: list[str], idx: int) -> bool:
    line = lines[idx].strip()
    if not line or line.startswith(("#", "-", "*", ">", "|", "<!--")):
        return False
    if len(line) > 56:
        return False
    if re.search(r"[。！？!?；;，,：:]$", line):
        return False
    if not is_parenthesized_clause_heading(line):
        return False
    if not is_blank_separated(lines, idx):
        return False
    next_line = next_nonempty_line(lines, idx + 1)
    if not next_line or next_line.strip().startswith(("#", "-", "*", ">", "|", "<!--")):
        return False
    return len(next_line.strip()) >= 8


def should_promote_numeric_item_heading(lines: list[str], idx: int) -> bool:
    line = lines[idx].strip()
    if not line or line.startswith(("#", "-", "*", ">", "|", "<!--")):
        return False
    if len(line) > 80:
        return False
    if re.search(r"[。！？!?；;，,：:]$", line):
        return False
    if not is_numeric_item_heading(line):
        return False
    if not is_blank_separated(lines, idx):
        return False
    next_line = next_nonempty_line(lines, idx + 1)
    return bool(next_line and len(next_line.strip()) >= 8)


def should_promote_parenthesized_digit_heading(lines: list[str], idx: int) -> bool:
    line = lines[idx].strip()
    if not line or line.startswith(("#", "-", "*", ">", "|", "<!--")):
        return False
    if len(line) > 80:
        return False
    if re.search(r"[。！？!?；;，,：:]$", line):
        return False
    if not is_parenthesized_digit_heading(line):
        return False
    if not is_blank_separated(lines, idx):
        return False
    next_line = next_nonempty_line(lines, idx + 1)
    return bool(next_line and len(next_line.strip()) >= 8)


def is_blank_separated(lines: list[str], idx: int) -> bool:
    previous_blank = idx == 0 or not lines[idx - 1].strip()
    next_blank = idx + 1 >= len(lines) or not lines[idx + 1].strip()
    return previous_blank and next_blank


def is_chapter_heading(line: str) -> bool:
    return bool(re.match(r"^第[一二三四五六七八九十百零〇\d]+[章篇部卷]\s*\S", line))


def is_section_heading(line: str) -> bool:
    return bool(re.match(r"^第[一二三四五六七八九十百零〇\d]+节\s*\S", line))


def is_article_heading(line: str) -> bool:
    return bool(re.match(r"^第[一二三四五六七八九十百零〇\d]+条\s*\S", line))


def is_parenthesized_clause_heading(line: str) -> bool:
    return bool(
        re.match(r"^（[一二三四五六七八九十百零〇]+）\S", line)
        or re.match(r"^\([一二三四五六七八九十百零〇]+\)\S", line)
    )


def is_numeric_item_heading(line: str) -> bool:
    return bool(re.match(r"^\d{1,2}[\.、]\s*\S", line))


def is_parenthesized_digit_heading(line: str) -> bool:
    return bool(re.match(r"^（\d{1,2}）\S", line) or re.match(r"^\(\d{1,2}\)\S", line))


def next_nonempty_line(lines: list[str], start: int) -> str:
    for line in lines[start:]:
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def build_heading_candidate_map(candidates: list[HeadingCandidate | dict[str, Any]]) -> dict[str, list[HeadingCandidate]]:
    mapped: dict[str, list[HeadingCandidate]] = {}
    for item in candidates:
        candidate = normalize_heading_candidate(item)
        key = normalize_heading_key(candidate.title)
        if not key:
            continue
        mapped.setdefault(key, []).append(candidate)
    for items in mapped.values():
        items.sort(key=lambda item: item.score, reverse=True)
    return mapped


def normalize_heading_candidate(item: HeadingCandidate | dict[str, Any]) -> HeadingCandidate:
    if isinstance(item, HeadingCandidate):
        return item
    return HeadingCandidate(
        title=str(item.get("title") or item.get("content") or "").strip(),
        level=int(item["level"]) if item.get("level") not in {None, ""} else None,
        source=str(item.get("source") or ""),
        page=int(item["page"]) if item.get("page") not in {None, ""} else None,
        bbox=[float(value) for value in item.get("bbox") or []] or None,
        font_size=float(item["font_size"]) if item.get("font_size") not in {None, ""} else None,
        font=str(item.get("font") or ""),
        score=float(item.get("score") or 0.0),
        reason=str(item.get("reason") or ""),
    )


def candidate_for_title(candidate_map: dict[str, list[HeadingCandidate]], title: str) -> HeadingCandidate | None:
    key = normalize_heading_key(title)
    if not key:
        return None
    candidates = candidate_map.get(key) or []
    return candidates[0] if candidates else None


def normalize_heading_key(value: str) -> str:
    value = re.sub(r"^#+\s*", "", str(value).strip())
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[《》“”\"'‘’：:，,。.!！?？、（）()\[\]【】\-—–_·•；;]", "", value)
    return value.casefold()


def candidate_signals(candidate: HeadingCandidate | None) -> list[str]:
    if not candidate:
        return []
    signals = []
    if candidate.source:
        signals.append(f"candidate_source:{candidate.source}")
    if candidate.level:
        signals.append(f"candidate_level:{candidate.level}")
    if candidate.page:
        signals.append(f"candidate_page:{candidate.page}")
    if candidate.font_size:
        signals.append(f"font_size:{candidate.font_size:g}")
    if candidate.font:
        signals.append(f"font:{candidate.font}")
    if candidate.reason:
        signals.append(f"candidate_reason:{candidate.reason}")
    return signals


def should_promote_external_candidate(lines: list[str], idx: int, candidate: HeadingCandidate) -> bool:
    line = lines[idx].strip()
    if not line or line.startswith(("#", "-", "*", ">", "|", "<!--")):
        return False
    if len(line) > 100:
        return False
    if not is_blank_separated(lines, idx):
        return False
    return candidate.score >= 0.65 or candidate.source == "pdf_outline"


def normalized_candidate_level(candidate: HeadingCandidate) -> int:
    if candidate.level:
        return min(max(int(candidate.level), 1), 6)
    return 2
