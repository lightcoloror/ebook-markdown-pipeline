from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_utils import SAMPLE_SCHEMA_VERSION, classify_sample, now, recommendation_for, safe_id, write_json  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import SUPPORTED_FORMATS  # noqa: E402
from ebook_markdown_pipeline.document_locator import IMAGE_EXTENSIONS  # noqa: E402


TARGET_CATEGORIES = ["ebook", "scanned_pdf", "complex_pdf", "pdf", "docling_doc", "text_doc", "image_set"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover local real files for benchmark manifests.")
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "benchmarks" / "samples.local.json")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--per-category", type=int, default=10)
    parser.add_argument("--include-images", action="store_true", help="Include individual images; folders are preferred by default.")
    args = parser.parse_args()

    samples = discover_samples(args.roots, limit=args.limit, per_category=args.per_category, include_images=args.include_images)
    write_json(
        args.output,
        {
            "schema_version": SAMPLE_SCHEMA_VERSION,
            "created_at": now(),
            "roots": [str(root) for root in args.roots],
            "samples": samples,
        },
    )
    print(json.dumps({"output": str(args.output), "count": len(samples), "categories": count_categories(samples)}, ensure_ascii=False, indent=2))
    return 0


def discover_samples(roots: list[Path], *, limit: int, per_category: int, include_images: bool) -> list[dict]:
    samples = []
    category_counts = {category: 0 for category in TARGET_CATEGORIES}
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        candidates = collect_candidates(root, include_images=include_images)
        for path in candidates:
            resolved = str(path.resolve()).lower()
            if resolved in seen:
                continue
            seen.add(resolved)
            category = classify_sample(path)
            if category not in category_counts:
                continue
            if category_counts[category] >= per_category:
                continue
            category_counts[category] += 1
            samples.append(
                {
                    "id": unique_sample_id(path, samples),
                    "path": str(path.resolve()),
                    "category": category,
                    "recommended_pipeline": recommendation_for(path),
                    "size_bytes": folder_size(path) if path.is_dir() else path.stat().st_size,
                    "notes": "",
                }
            )
            if len(samples) >= limit:
                return samples
    return samples


def collect_candidates(root: Path, *, include_images: bool) -> list[Path]:
    if root.is_file():
        return [root]
    supported = SUPPORTED_FORMATS | ({*IMAGE_EXTENSIONS} if include_images else set())
    files = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in supported]
    image_dirs = []
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        image_count = len([item for item in path.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS])
        if image_count >= 5:
            image_dirs.append(path)
    return sorted(image_dirs + files, key=lambda item: (str(item).lower().count("\\"), str(item).lower()))


def unique_sample_id(path: Path, existing: list[dict]) -> str:
    base = safe_id(path.stem if path.is_file() else path.name)
    used = {item["id"] for item in existing}
    if base not in used:
        return base
    index = 2
    while f"{base}-{index}" in used:
        index += 1
    return f"{base}-{index}"


def folder_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def count_categories(samples: list[dict]) -> dict[str, int]:
    counts = {}
    for item in samples:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
