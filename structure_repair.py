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
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not self.confidence:
            self.confidence = infer_decision_confidence(self.kind, self.signals)


@dataclass
class NoiseCleanupDecision:
    line_number: int
    original: str
    replacement: str
    kind: str
    reason: str
    signals: list[str]
    confidence: float = 0.84


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
    cleanup_decisions: list[NoiseCleanupDecision] | None = None

    def report(self) -> dict[str, Any]:
        candidates = self.candidates or []
        cleanup_decisions = self.cleanup_decisions or []
        source_counts: dict[str, int] = {}
        for item in candidates:
            source_counts[item.source or "unknown"] = source_counts.get(item.source or "unknown", 0) + 1
        rendered_decisions = [decision_report_item(item) for item in self.decisions]
        action_counts: dict[str, int] = {}
        for item in rendered_decisions:
            action = str(item.get("action") or "unknown")
            action_counts[action] = action_counts.get(action, 0) + 1
        cleanup_counts: dict[str, int] = {}
        rendered_cleanup = []
        for item in cleanup_decisions:
            cleanup_counts[item.kind] = cleanup_counts.get(item.kind, 0) + 1
            rendered_cleanup.append(cleanup_report_item(item))
        return {
            "schema_version": "structure-repair-v1",
            "grammar": "chapter_section_article_clause_item_subitem",
            "decision_count": len(self.decisions),
            "action_counts": action_counts,
            "cleanup_decision_count": len(cleanup_decisions),
            "cleanup_counts": cleanup_counts,
            "candidate_count": len(candidates),
            "candidate_sources": source_counts,
            "candidate_samples": [asdict(item) for item in candidates[:20]],
            "inferred_outline": build_markdown_outline(self.markdown),
            "decisions": rendered_decisions,
            "cleanup_decisions": rendered_cleanup,
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
    lines, cleanup_decisions = cleanup_common_document_noise(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    repaired: list[str] = []
    decisions: list[HeadingDecision] = []
    domain_candidates = collect_domain_heading_candidates(lines)
    normalized_candidates = [normalize_heading_candidate(item) for item in (heading_candidates or [])]
    normalized_candidates.extend(domain_candidates)
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
    return StructureRepairResult(
        markdown="\n".join(repaired),
        decisions=decisions,
        candidates=normalized_candidates,
        cleanup_decisions=cleanup_decisions,
    )


def parse_existing_heading(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def decision_report_item(decision: HeadingDecision) -> dict[str, Any]:
    item = asdict(decision)
    item["action"] = classify_decision_action(decision)
    item["changed"] = decision.original != decision.repaired
    item["confidence"] = round(float(decision.confidence), 3)
    return item


def cleanup_report_item(decision: NoiseCleanupDecision) -> dict[str, Any]:
    item = asdict(decision)
    item["action"] = "replaced_with_audit_comment" if decision.original != decision.replacement else "kept"
    item["changed"] = decision.original != decision.replacement
    item["confidence"] = round(float(decision.confidence), 3)
    return item


def classify_decision_action(decision: HeadingDecision) -> str:
    if decision.original == decision.repaired:
        return "kept_with_evidence"
    original_heading = parse_existing_heading(decision.original.strip())
    repaired_heading = parse_existing_heading(decision.repaired.strip())
    if original_heading and repaired_heading:
        return "normalized_heading"
    if repaired_heading:
        return "promoted_to_heading"
    return "changed"


def infer_decision_confidence(kind: str, signals: list[str]) -> float:
    if kind in {"chapter", "section", "article"}:
        score = 0.82
    elif kind == "parenthesized_clause":
        score = 0.76
    elif kind == "numeric_item":
        score = 0.72
    elif kind == "parenthesized_digit_item":
        score = 0.70
    elif kind == "external_candidate":
        score = 0.74
    elif kind == "existing_heading_with_signal":
        score = 0.86
    else:
        score = 0.65

    joined = "\n".join(signals)
    if "normalized_existing_heading" in joined:
        score += 0.06
    if "candidate_source:pdf_outline" in joined:
        score += 0.10
    if "candidate_source:pymupdf_font_jump" in joined:
        score += 0.08
    if "candidate_source:mineru_paragraph_title" in joined:
        score += 0.08
    if "candidate_source:docling_heading" in joined:
        score += 0.08
    if "candidate_source:domain_grammar" in joined:
        score += 0.04
    if "nearest_parent:" in joined:
        score += 0.03
    candidate_score = max(candidate_scores_from_signals(signals) or [0.0])
    if candidate_score:
        score = max(score, min(0.98, 0.62 + candidate_score * 0.35))
    return round(min(max(score, 0.05), 0.98), 3)


def candidate_scores_from_signals(signals: list[str]) -> list[float]:
    scores: list[float] = []
    for signal in signals:
        match = re.match(r"candidate_score:(\d+(?:\.\d+)?)$", signal)
        if match:
            scores.append(float(match.group(1)))
    return scores


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


def cleanup_common_document_noise(lines: list[str]) -> tuple[list[str], list[NoiseCleanupDecision]]:
    """Replace obvious OCR/PDF noise with audit comments before heading repair.

    The rules are deliberately conservative. They only target artifacts that
    consistently hurt downstream structure: standalone page numbers, repeated
    short running headers/footers, consecutive duplicate lines, and early TOC
    dotted-leader remnants.
    """
    repeated_keys = repeated_document_noise_keys(lines)
    page_number_indexes = standalone_page_number_indexes(lines)
    toc_indexes = toc_remnant_indexes(lines)
    decisions: list[NoiseCleanupDecision] = []
    cleaned: list[str] = []
    previous_key = ""
    for idx, line in enumerate(lines):
        stripped = line.strip()
        key = normalize_document_noise_key(line)
        replacement = ""
        kind = ""
        reason = ""
        signals: list[str] = []

        if idx in toc_indexes:
            kind = "toc_remnant"
            reason = "Early dotted-leader table-of-contents line was replaced with an audit comment."
            signals = ["toc_pattern:dotted_leader", "position:early_document"]
        elif idx in page_number_indexes:
            kind = "standalone_page_number"
            reason = "Standalone page-number line was replaced with an audit comment."
            signals = ["page_number:standalone", "blank_separated"]
        elif key and key in repeated_keys:
            kind = "repeated_header_footer"
            reason = "Short repeated running header/footer candidate was replaced with an audit comment."
            signals = ["noise_key:repeated", f"noise_key:{key}"]
        elif key and previous_key and key == previous_key and not is_structural_heading_text(stripped):
            kind = "consecutive_duplicate"
            reason = "Consecutive duplicate line was replaced with an audit comment."
            signals = ["duplicate:consecutive", f"noise_key:{key}"]

        if kind:
            replacement = f"<!-- removed {kind}: {html_comment_safe(stripped)} -->"
            decisions.append(
                NoiseCleanupDecision(
                    line_number=idx + 1,
                    original=line,
                    replacement=replacement,
                    kind=kind,
                    reason=reason,
                    signals=signals,
                    confidence=cleanup_confidence(kind, signals),
                )
            )
            cleaned.append(replacement)
            previous_key = ""
            continue

        cleaned.append(line)
        if key:
            previous_key = key
        elif stripped and not stripped.startswith("<!--"):
            previous_key = ""
    return cleaned, decisions


def cleanup_confidence(kind: str, signals: list[str]) -> float:
    base = {
        "toc_remnant": 0.80,
        "standalone_page_number": 0.86,
        "repeated_header_footer": 0.84,
        "consecutive_duplicate": 0.78,
    }.get(kind, 0.70)
    if any(signal.startswith("noise_key:") for signal in signals):
        base += 0.04
    return round(min(base, 0.96), 3)


def repeated_document_noise_keys(lines: list[str]) -> set[str]:
    counts: dict[str, int] = {}
    for line in lines:
        key = normalize_document_noise_key(line)
        if key:
            counts[key] = counts.get(key, 0) + 1
    return {key for key, count in counts.items() if count >= 4 and (len(key) <= 20 or count >= 6)}


def standalone_page_number_indexes(lines: list[str]) -> set[int]:
    indexes = [
        idx
        for idx, line in enumerate(lines)
        if is_standalone_page_number_line(line.strip()) and is_blank_separated(lines, idx)
    ]
    return set(indexes) if len(indexes) >= 3 else set()


def toc_remnant_indexes(lines: list[str]) -> set[int]:
    candidates = [
        idx
        for idx, line in enumerate(lines[:160])
        if is_toc_dotted_leader_line(line.strip())
    ]
    return set(candidates) if len(candidates) >= 3 else set()


def is_toc_dotted_leader_line(line: str) -> bool:
    if not line or line.startswith(("#", "|", "<!--")):
        return False
    return bool(re.match(r"^.{2,90}(?:\.{3,}|…{2,}|·{3,})\s*\d{1,4}\s*$", line))


def is_standalone_page_number_line(line: str) -> bool:
    stripped = re.sub(r"\s+", "", line.strip())
    if not stripped:
        return False
    return bool(re.match(r"^[\-—–_·•]*(?:第)?\d{1,4}(?:页)?(?:/\d{1,4})?[\-—–_·•]*$", stripped, re.I))


def normalize_document_noise_key(line: str) -> str:
    stripped = re.sub(r"\s+", "", line.strip())
    if not stripped:
        return ""
    if line.lstrip().startswith(("#", "|", ">", "-", "*", "<!--")):
        return ""
    if is_structural_heading_text(stripped):
        return ""
    if is_standalone_page_number_line(stripped):
        return ""
    stripped = re.sub(r"^[\-—–_·•]*(?:第)?\d{1,4}(?:页)?(?:/\d{1,4})?[\-—–_·•]+", "", stripped)
    stripped = re.sub(r"[\-—–_·•]+(?:第)?\d{1,4}(?:页)?(?:/\d{1,4})?[\-—–_·•]*$", "", stripped)
    stripped = stripped.strip("-—–_·•")
    if not stripped or len(stripped) > 32:
        return ""
    if re.search(r"[。！？!?；;：:，,、]$", stripped):
        return ""
    return stripped.casefold()


def is_structural_heading_text(line: str) -> bool:
    return (
        is_chapter_heading(line)
        or is_section_heading(line)
        or is_article_heading(line)
        or is_parenthesized_clause_heading(line)
        or is_numeric_item_heading(line)
        or is_parenthesized_digit_heading(line)
    )


def html_comment_safe(value: str) -> str:
    return value.replace("--", "- -").strip()


def collect_domain_heading_candidates(lines: list[str]) -> list[HeadingCandidate]:
    candidates: list[HeadingCandidate] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        existing = parse_existing_heading(stripped)
        title = existing[1] if existing else stripped
        if not title:
            continue
        level = domain_heading_level(title)
        if level is None:
            continue
        if existing or should_accept_plain_domain_candidate(lines, idx, title):
            candidates.append(
                HeadingCandidate(
                    title=title,
                    level=level,
                    source=f"domain_grammar:{domain_heading_kind(title)}",
                    score=0.8 if existing else 0.72,
                    reason="Chinese legal/contract numbering pattern",
                )
            )
    return candidates


def should_accept_plain_domain_candidate(lines: list[str], idx: int, title: str) -> bool:
    if is_chapter_heading(title) or is_section_heading(title) or is_article_heading(title):
        return is_blank_separated(lines, idx)
    if is_parenthesized_clause_heading(title):
        return should_promote_parenthesized_heading(lines, idx)
    if is_numeric_item_heading(title):
        return should_promote_numeric_item_heading(lines, idx)
    if is_parenthesized_digit_heading(title):
        return should_promote_parenthesized_digit_heading(lines, idx)
    return False


def domain_heading_level(title: str) -> int | None:
    if is_chapter_heading(title):
        return 1
    if is_section_heading(title):
        return 2
    if is_article_heading(title):
        return 3
    if is_parenthesized_clause_heading(title):
        return 4
    if is_numeric_item_heading(title):
        return 5
    if is_parenthesized_digit_heading(title):
        return 6
    return None


def domain_heading_kind(title: str) -> str:
    if is_chapter_heading(title):
        return "chapter"
    if is_section_heading(title):
        return "section"
    if is_article_heading(title):
        return "article"
    if is_parenthesized_clause_heading(title):
        return "parenthesized_clause"
    if is_numeric_item_heading(title):
        return "numeric_item"
    if is_parenthesized_digit_heading(title):
        return "parenthesized_digit_item"
    return "unknown"


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
    if candidate.score:
        signals.append(f"candidate_score:{candidate.score:g}")
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
