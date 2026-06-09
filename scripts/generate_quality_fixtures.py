from __future__ import annotations

import argparse
import json
import struct
import zlib
import zipfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_DIR / "benchmarks" / "fixtures" / "generated"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate small public quality-gate fixtures.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    write_text_fixture(root / "text" / "sample.txt")
    write_epub_fixture(root / "ebooks" / "sample.epub")
    write_pdf_fixtures(root / "pdf")
    write_image_fixtures(root / "images")
    write_manifests(root)
    print(json.dumps({"fixtures": str(root), "manifests": ["quality-minimal.json", "quality-full.json"]}, ensure_ascii=False))
    return 0


def write_text_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Public Quality Fixture\n\n"
        "## Chapter One\n\n"
        "This small text fixture is generated for regression tests.\n\n"
        "## Chapter Two\n\n"
        "It contains headings, body text, and enough structure for Markdown quality scoring.\n",
        encoding="utf-8",
        newline="\n",
    )


def write_epub_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "OPS/package.opf",
            """<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="bookid" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">quality-fixture</dc:identifier>
    <dc:title>Quality Fixture EPUB</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="chapter1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter2" href="chapter2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter1"/>
    <itemref idref="chapter2"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OPS/nav.xhtml",
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <body>
    <nav epub:type="toc">
      <ol>
        <li><a href="chapter1.xhtml">Chapter One</a></li>
        <li><a href="chapter2.xhtml">Chapter Two</a></li>
      </ol>
    </nav>
  </body>
</html>
""",
        )
        archive.writestr("OPS/chapter1.xhtml", xhtml_chapter("Chapter One", "A short public-domain-style chapter."))
        archive.writestr("OPS/chapter2.xhtml", xhtml_chapter("Chapter Two", "A second chapter for heading regression."))


def xhtml_chapter(title: str, body: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>{title}</title></head>
  <body>
    <h1>{title}</h1>
    <p>{body}</p>
    <h2>Section</h2>
    <p>This section gives the converter a nested heading to preserve.</p>
  </body>
</html>
"""


def write_pdf_fixtures(root: Path) -> None:
    import fitz

    root.mkdir(parents=True, exist_ok=True)
    write_text_pdf(root / "text-layer.pdf", title="Text Layer PDF", two_column=False, slide=False)
    write_text_pdf(root / "two-column.pdf", title="Two Column PDF", two_column=True, slide=False)
    write_text_pdf(root / "ppt-exported.pdf", title="Presentation Like PDF", two_column=False, slide=True)
    write_bookmarked_pdf(root / "bookmarked.pdf")
    image_path = root / "scan-source.png"
    write_png(image_path, width=640, height=360)
    doc = fitz.open()
    page = doc.new_page(width=640, height=360)
    page.insert_image(fitz.Rect(0, 0, 640, 360), filename=str(image_path))
    doc.save(root / "scanned-image-only.pdf")
    doc.close()


def write_text_pdf(path: Path, *, title: str, two_column: bool, slide: bool) -> None:
    import fitz

    width, height = (960, 540) if slide else (595, 842)
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.insert_text((50, 60), title, fontsize=24)
    page.insert_text((50, 100), "1. Overview", fontsize=16)
    if two_column:
        page.insert_textbox(fitz.Rect(50, 130, 270, 760), "Left column\n" * 18, fontsize=10)
        page.insert_textbox(fitz.Rect(320, 130, 540, 760), "Right column\n" * 18, fontsize=10)
    else:
        page.insert_textbox(
            fitz.Rect(50, 130, width - 50, height - 80),
            "This generated PDF has a real text layer and predictable headings.\n" * 8,
            fontsize=12,
        )
    page.insert_text((50, height - 50), "2. Closing", fontsize=16)
    doc.save(path)
    doc.close()


def write_bookmarked_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    first = doc.new_page(width=595, height=842)
    first.insert_text((50, 60), "Bookmarked Fixture", fontsize=24)
    first.insert_text((50, 110), "Chapter One", fontsize=18)
    first.insert_textbox(
        fitz.Rect(50, 150, 540, 420),
        "This generated PDF has built-in bookmarks that should align with Markdown headings.\n" * 4,
        fontsize=12,
    )
    first.insert_text((50, 470), "Section One Point One", fontsize=15)
    first.insert_textbox(
        fitz.Rect(50, 510, 540, 760),
        "A nested section gives the quality gate a second-level outline item to match.\n" * 4,
        fontsize=12,
    )
    second = doc.new_page(width=595, height=842)
    second.insert_text((50, 70), "Chapter Two", fontsize=18)
    second.insert_textbox(
        fitz.Rect(50, 120, 540, 760),
        "The second page makes bookmark page references meaningful without adding copyrighted content.\n" * 8,
        fontsize=12,
    )
    doc.set_toc(
        [
            [1, "Chapter One", 1],
            [2, "Section One Point One", 1],
            [1, "Chapter Two", 2],
        ]
    )
    doc.save(path)
    doc.close()


def write_image_fixtures(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    write_png(root / "infographic.png", width=900, height=520)
    screenshots = root / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    write_png(screenshots / "page-002.png", width=640, height=420)
    write_png(screenshots / "page-001.png", width=640, height=420)
    write_png(screenshots / "page-001-duplicate.png", width=640, height=420)


def write_png(path: Path, *, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            card = ((x // 180) + (y // 120)) % 2
            if y < 70:
                color = (40, 80, 120)
            elif card:
                color = (230, 240, 235)
            else:
                color = (245, 235, 220)
            if 20 < x % 180 < 150 and 30 < y % 120 < 45:
                color = (80, 80, 80)
            row.extend(color)
        rows.append(b"\x00" + bytes(row))
    raw = b"".join(rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_manifests(root: Path) -> None:
    def rel(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(PROJECT_DIR)).replace("\\", "/")
        except ValueError:
            return str(path)

    samples = [
        {"id": "txt-01", "path": rel(root / "text" / "sample.txt"), "category": "text_doc"},
        {"id": "epub-01", "path": rel(root / "ebooks" / "sample.epub"), "category": "ebook_epub"},
        {"id": "azw3-substitute-01", "path": rel(root / "ebooks" / "sample.epub"), "category": "ebook_azw3_substitute"},
        {"id": "pdf-text-01", "path": rel(root / "pdf" / "text-layer.pdf"), "category": "pdf_text_layer"},
        {"id": "pdf-bookmarked-01", "path": rel(root / "pdf" / "bookmarked.pdf"), "category": "pdf_bookmarked_outline"},
        {"id": "pdf-two-column-01", "path": rel(root / "pdf" / "two-column.pdf"), "category": "pdf_two_column"},
        {"id": "pdf-ppt-export-01", "path": rel(root / "pdf" / "ppt-exported.pdf"), "category": "pdf_presentation_like"},
        {"id": "pdf-scan-01", "path": rel(root / "pdf" / "scanned-image-only.pdf"), "category": "scanned_pdf"},
        {"id": "image-infographic-01", "path": rel(root / "images" / "infographic.png"), "category": "image_infographic"},
        {"id": "screenshots-duplicates-01", "path": rel(root / "images" / "screenshots"), "category": "image_set_duplicates"},
    ]
    minimal_ids = {"txt-01", "epub-01", "azw3-substitute-01", "pdf-text-01", "pdf-bookmarked-01", "pdf-two-column-01", "pdf-ppt-export-01"}
    write_manifest(root / "quality-minimal.json", [item for item in samples if item["id"] in minimal_ids], "Minimal public quality-gate fixtures.")
    write_manifest(root / "quality-full.json", samples, "Full public quality-gate fixtures, including OCR/image-heavy samples.")


def write_manifest(path: Path, samples: list[dict[str, str]], description: str) -> None:
    payload = {
        "schema_version": "benchmark-samples-v1",
        "description": description,
        "samples": samples,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
