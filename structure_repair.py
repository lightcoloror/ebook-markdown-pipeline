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
class StructureRepairResult:
    markdown: str
    decisions: list[HeadingDecision]

    def report(self) -> dict[str, Any]:
        return {
            "schema_version": "structure-repair-v1",
            "decision_count": len(self.decisions),
            "decisions": [asdict(item) for item in self.decisions],
        }


def repair_markdown_structure(text: str, *, source_kind: str = "") -> StructureRepairResult:
    """Repair conservative heading hierarchy for structured Chinese clauses.

    The first implementation focuses on contract/regulation-style numbering:
    chapter/section headings are usually already present, `第X条 ...` becomes
    an article heading, and `（一）...` becomes a child of the latest article.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    repaired: list[str] = []
    decisions: list[HeadingDecision] = []
    current_section = ""
    current_article = ""
    for idx, line in enumerate(lines):
        stripped = line.strip()
        existing = parse_existing_heading(stripped)
        if existing:
            level, title = existing
            if is_article_heading(title):
                repaired_line = f"### {title}"
                current_article = title
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
                            signals=["domain_grammar:article", "normalized_existing_heading"],
                        )
                    )
                continue
            if is_parenthesized_clause_heading(title):
                level_target = 4 if current_article else 3
                repaired_line = f"{'#' * level_target} {title}"
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
                            ],
                        )
                    )
                continue
            if level <= 2:
                current_section = title
                current_article = ""
            repaired.append(line)
            continue

        if should_promote_article_heading(lines, idx):
            repaired_line = f"### {stripped}"
            current_article = stripped
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
                    signals=["domain_grammar:article", f"source_kind:{source_kind}" if source_kind else "source_kind:unknown"],
                )
            )
            continue

        if should_promote_parenthesized_heading(lines, idx):
            level = 4 if current_article else 3
            repaired_line = f"{'#' * level} {stripped}"
            parent = current_article or current_section
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
                    ],
                )
            )
            continue

        repaired.append(line)
    return StructureRepairResult(markdown="\n".join(repaired), decisions=decisions)


def parse_existing_heading(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def should_promote_article_heading(lines: list[str], idx: int) -> bool:
    line = lines[idx].strip()
    if not line or line.startswith(("#", "-", "*", ">", "|", "<!--")):
        return False
    if len(line) > 160:
        return False
    if not is_article_heading(line):
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


def is_blank_separated(lines: list[str], idx: int) -> bool:
    previous_blank = idx == 0 or not lines[idx - 1].strip()
    next_blank = idx + 1 >= len(lines) or not lines[idx + 1].strip()
    return previous_blank and next_blank


def is_article_heading(line: str) -> bool:
    return bool(re.match(r"^第[一二三四五六七八九十百零〇\d]+条\s*\S", line))


def is_parenthesized_clause_heading(line: str) -> bool:
    return bool(
        re.match(r"^（[一二三四五六七八九十百零〇]+）\S", line)
        or re.match(r"^\([一二三四五六七八九十百零〇]+\)\S", line)
    )


def next_nonempty_line(lines: list[str], start: int) -> str:
    for line in lines[start:]:
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
