from __future__ import annotations

import os
import re
import uuid
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_GROBID_TIMEOUT_SECONDS = 60.0
TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def grobid_server_url() -> str:
    return os.environ.get("EBOOK_CONVERTER_GROBID_SERVER_URL", "").strip().rstrip("/")


def grobid_available() -> bool:
    return bool(grobid_server_url())


def grobid_health() -> dict[str, str]:
    url = grobid_server_url()
    if url:
        return {"status": "ok", "detail": f"GROBID Server configured: {url}"}
    return {
        "status": "missing",
        "detail": "optional GROBID academic PDF backend not configured; set EBOOK_CONVERTER_GROBID_SERVER_URL",
    }


def inspect_with_grobid(source: Path, *, timeout_seconds: float = DEFAULT_GROBID_TIMEOUT_SECONDS) -> dict[str, Any]:
    source = Path(source)
    url = grobid_server_url()
    if not source.exists():
        return {"status": "missing_source", "tool": "grobid", "source": str(source), "message": "source file does not exist"}
    if source.suffix.lower() != ".pdf":
        return {"status": "unsupported", "tool": "grobid", "source": str(source), "message": "GROBID only supports PDF inputs in this project."}
    if not url:
        return {
            "status": "missing_dependency",
            "tool": "grobid",
            "source": str(source),
            "message": "GROBID Server is not configured. Set EBOOK_CONVERTER_GROBID_SERVER_URL.",
        }
    try:
        header_tei = post_grobid_pdf(source, server_url=url, endpoint="/api/processHeaderDocument", timeout_seconds=timeout_seconds)
        fulltext_tei = post_grobid_pdf(source, server_url=url, endpoint="/api/processFulltextDocument", timeout_seconds=timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "tool": "grobid",
            "source": str(source),
            "server_url": url,
            "message": str(exc),
        }
    return normalize_grobid_tei(source=source, server_url=url, header_tei=header_tei, fulltext_tei=fulltext_tei)


def post_grobid_pdf(source: Path, *, server_url: str, endpoint: str, timeout_seconds: float) -> str:
    boundary = f"----ebook-grobid-{uuid.uuid4().hex}"
    body = multipart_pdf_body(source, boundary=boundary)
    request = urllib.request.Request(
        f"{server_url}{endpoint}",
        data=body,
        method="POST",
        headers={
            "Accept": "application/xml",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - user-configured local/remote GROBID URL.
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GROBID {endpoint} failed with HTTP {exc.code}: {body_text[:500]}") from exc


def multipart_pdf_body(source: Path, *, boundary: str) -> bytes:
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="input"; filename="{source.name}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + source.read_bytes() + tail


def normalize_grobid_tei(*, source: Path, server_url: str, header_tei: str, fulltext_tei: str) -> dict[str, Any]:
    header_root = parse_tei(header_tei)
    fulltext_root = parse_tei(fulltext_tei)
    source_root = fulltext_root or header_root
    if source_root is None:
        return {
            "status": "failed",
            "tool": "grobid",
            "source": str(source),
            "server_url": server_url,
            "message": "GROBID returned invalid TEI XML.",
        }
    title = first_text(
        source_root,
        [
            ".//tei:titleStmt/tei:title",
            ".//tei:analytic/tei:title",
            ".//tei:monogr/tei:title",
        ],
    )
    abstract = first_text(source_root, [".//tei:profileDesc/tei:abstract"])
    authors = extract_authors(source_root)
    doi = first_text(source_root, [".//tei:idno[@type='DOI']", ".//tei:idno[@type='doi']"])
    year = first_text(source_root, [".//tei:sourceDesc//tei:date[@when]", ".//tei:imprint/tei:date"])
    references = source_root.findall(".//tei:listBibl/tei:biblStruct", TEI_NS)
    sections = [text_content(item) for item in source_root.findall(".//tei:text/tei:body//tei:head", TEI_NS)]
    payload = {
        "status": "ok",
        "tool": "grobid",
        "source": str(source),
        "server_url": server_url,
        "title": title,
        "authors": authors[:20],
        "author_count": len(authors),
        "doi": doi,
        "year": year,
        "abstract_sample": collapse_whitespace(abstract)[:1200],
        "reference_count": len(references),
        "section_headings": [collapse_whitespace(item)[:160] for item in sections if item.strip()][:30],
        "tei_chars": len(fulltext_tei or header_tei or ""),
    }
    return payload


def parse_tei(value: str) -> ET.Element | None:
    try:
        return ET.fromstring(value.encode("utf-8"))
    except Exception:
        return None


def first_text(root: ET.Element, paths: list[str]) -> str:
    for path in paths:
        item = root.find(path, TEI_NS)
        if item is None:
            continue
        if path.endswith("[@when]"):
            when = item.attrib.get("when")
            if when:
                return when
        text = collapse_whitespace(text_content(item))
        if text:
            return text
    return ""


def extract_authors(root: ET.Element) -> list[str]:
    authors: list[str] = []
    for author in root.findall(".//tei:titleStmt/tei:author", TEI_NS) + root.findall(".//tei:analytic/tei:author", TEI_NS):
        pers_name = author.find(".//tei:persName", TEI_NS)
        name = person_name_text(pers_name) if pers_name is not None else collapse_whitespace(text_content(author))
        if name and name not in authors:
            authors.append(name)
    return authors


def person_name_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    parts: list[str] = []
    for tag in ("forename", "surname"):
        for item in node.findall(f".//tei:{tag}", TEI_NS):
            text = collapse_whitespace(text_content(item))
            if text:
                parts.append(text)
    return collapse_whitespace(" ".join(parts)) or collapse_whitespace(text_content(node))


def text_content(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(node.itertext())


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
