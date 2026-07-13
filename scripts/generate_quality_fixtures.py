from __future__ import annotations

import argparse
import json
import struct
import zlib
import zipfile
from pathlib import Path
from typing import Iterable


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
    write_office_fixture(root / "office" / "sample.docx")
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


def write_office_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>
""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
""",
        )
        archive.writestr(
            "word/_rels/document.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
""",
        )
        archive.writestr(
            "word/styles.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:outlineLvl w:val="0"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:outlineLvl w:val="1"/></w:style>
</w:styles>
""",
        )
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>Office Fixture</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Overview</w:t></w:r></w:p>
    <w:p><w:r><w:t>This synthetic DOCX validates the local Office-to-Markdown path without private documents.</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Checklist</w:t></w:r></w:p>
    <w:p><w:r><w:t>Markdown, manifest, and quality evidence must all be present.</w:t></w:r></w:p>
    <w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>
  </w:body>
</w:document>
""",
        )

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
    write_table_pdf(root / "table.pdf")
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


def write_table_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 60), "Table Fixture PDF", fontsize=24)
    page.insert_text((50, 105), "Quarterly Metrics", fontsize=16)
    rows = [
        ("Metric", "Q1", "Q2", "Q3", "Q4"),
        ("Revenue", "120", "132", "141", "155"),
        ("Cost", "80", "83", "90", "96"),
        ("Margin", "40", "49", "51", "59"),
        ("Users", "1000", "1250", "1400", "1680"),
    ]
    x_values = [50, 180, 260, 340, 420]
    y = 150
    for row_index, row in enumerate(rows):
        for x, cell in zip(x_values, row):
            page.insert_text((x, y), cell, fontsize=12)
        page.draw_line((45, y + 8), (510, y + 8), color=(0, 0, 0), width=0.5)
        if row_index == 0:
            page.draw_line((45, y - 16), (510, y - 16), color=(0, 0, 0), width=0.8)
        y += 32
    for x in [45, 160, 240, 320, 400, 510]:
        page.draw_line((x, 130), (x, y - 24), color=(0, 0, 0), width=0.5)
    page.insert_textbox(
        fitz.Rect(50, 350, 540, 500),
        "This generated table PDF is public fixture content. It checks whether converters preserve tabular structure signals.",
        fontsize=12,
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
    write_ocr_image_fixtures(root / "ocr")


def write_ocr_image_fixtures(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    write_text_image(
        root / "english.png",
        ["English OCR Fixture", "Chapter 1: Customer Notes", "Total amount: 128.50"],
        size=(900, 360),
        font_size=36,
    )
    write_text_image(
        root / "chinese.png",
        ["中文识别样本", "第一章 图文材料转换器", "金额 128.50 元"],
        size=(900, 360),
        font_size=34,
        prefer_cjk=True,
    )
    write_text_image(
        root / "lowres.png",
        ["Low resolution screenshot", "status ok", "page 03/08"],
        size=(360, 160),
        font_size=16,
        low_contrast=True,
    )
    write_infographic_text_image(root / "infographic-text.png")


def write_text_image(
    path: Path,
    lines: Iterable[str],
    *,
    size: tuple[int, int],
    font_size: int,
    prefer_cjk: bool = False,
    low_contrast: bool = False,
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)
    background = (245, 244, 238) if not low_contrast else (232, 232, 232)
    foreground = (34, 42, 54) if not low_contrast else (96, 96, 96)
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    font = load_fixture_font(font_size, prefer_cjk=prefer_cjk)
    y = max(24, font_size)
    for line in lines:
        draw.text((36, y), line, font=font, fill=foreground)
        y += int(font_size * 1.55)
    image.save(path)


def write_infographic_text_image(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (980, 560), (242, 239, 230))
    draw = ImageDraw.Draw(image)
    title_font = load_fixture_font(34, prefer_cjk=True)
    card_font = load_fixture_font(24, prefer_cjk=True)
    draw.text((36, 26), "信息图 OCR Fixture / Infographic OCR", font=title_font, fill=(35, 44, 57))
    cards = [
        ("目标", "Goal", 50, 110),
        ("用户", "Users", 360, 110),
        ("渠道", "Channels", 670, 110),
        ("成本", "Cost", 50, 310),
        ("收入", "Revenue", 360, 310),
        ("风险", "Risk", 670, 310),
    ]
    for cn, en, x, y in cards:
        draw.rounded_rectangle((x, y, x + 240, y + 135), radius=18, fill=(255, 255, 250), outline=(80, 110, 120), width=3)
        draw.text((x + 24, y + 24), cn, font=card_font, fill=(40, 64, 80))
        draw.text((x + 24, y + 70), en, font=card_font, fill=(70, 70, 70))
    image.save(path)


def load_fixture_font(size: int, *, prefer_cjk: bool = False):
    from PIL import ImageFont

    candidates = []
    if prefer_cjk:
        candidates.extend(
            [
                r"C:\Windows\Fonts\msyh.ttc",
                r"C:\Windows\Fonts\simsun.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            ]
        )
    candidates.extend(
        [
            r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


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
        {"id": "office-docx-01", "path": rel(root / "office" / "sample.docx"), "category": "office_docx"},
        {"id": "azw3-substitute-01", "path": rel(root / "ebooks" / "sample.epub"), "category": "ebook_azw3_substitute"},
        {"id": "pdf-text-01", "path": rel(root / "pdf" / "text-layer.pdf"), "category": "pdf_text_layer"},
        {"id": "pdf-bookmarked-01", "path": rel(root / "pdf" / "bookmarked.pdf"), "category": "pdf_bookmarked_outline"},
        {"id": "pdf-two-column-01", "path": rel(root / "pdf" / "two-column.pdf"), "category": "pdf_two_column"},
        {"id": "pdf-ppt-export-01", "path": rel(root / "pdf" / "ppt-exported.pdf"), "category": "pdf_presentation_like"},
        {
            "id": "pdf-table-01",
            "path": rel(root / "pdf" / "table.pdf"),
            "category": "pdf_table",
            "expected_table_like_lines": 5,
        },
        {"id": "pdf-scan-01", "path": rel(root / "pdf" / "scanned-image-only.pdf"), "category": "scanned_pdf"},
        {"id": "image-infographic-01", "path": rel(root / "images" / "infographic.png"), "category": "image_infographic"},
        {"id": "screenshots-duplicates-01", "path": rel(root / "images" / "screenshots"), "category": "image_set_duplicates"},
        {"id": "ocr-english-01", "path": rel(root / "images" / "ocr" / "english.png"), "category": "image_ocr_english"},
        {"id": "ocr-chinese-01", "path": rel(root / "images" / "ocr" / "chinese.png"), "category": "image_ocr_chinese"},
        {"id": "ocr-lowres-01", "path": rel(root / "images" / "ocr" / "lowres.png"), "category": "image_ocr_lowres"},
        {"id": "ocr-infographic-01", "path": rel(root / "images" / "ocr" / "infographic-text.png"), "category": "image_ocr_infographic"},
    ]
    minimal_ids = {"txt-01", "epub-01", "office-docx-01", "azw3-substitute-01", "pdf-text-01", "pdf-bookmarked-01", "pdf-two-column-01", "pdf-ppt-export-01"}
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
