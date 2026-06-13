from __future__ import annotations

import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.document_inspector import inspect_document  # noqa: E402
from ebook_markdown_pipeline.grobid_backend import grobid_health, inspect_with_grobid, normalize_grobid_tei  # noqa: E402


TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>Academic Parsing Test</title>
        <author><persName><forename>Ada</forename><surname>Lovelace</surname></persName></author>
      </titleStmt>
      <sourceDesc>
        <biblStruct>
          <analytic>
            <title>Academic Parsing Test</title>
            <author><persName><forename>Ada</forename><surname>Lovelace</surname></persName></author>
            <idno type="DOI">10.1234/example</idno>
          </analytic>
          <monogr><imprint><date when="2026"/></imprint></monogr>
        </biblStruct>
      </sourceDesc>
    </fileDesc>
    <profileDesc>
      <abstract><p>This paper validates a lightweight GROBID integration.</p></abstract>
    </profileDesc>
  </teiHeader>
  <text>
    <body>
      <head>Introduction</head>
      <head>Method</head>
    </body>
    <back>
      <listBibl>
        <biblStruct><analytic><title>Reference One</title></analytic></biblStruct>
        <biblStruct><analytic><title>Reference Two</title></analytic></biblStruct>
      </listBibl>
    </back>
  </text>
</TEI>
"""


def main() -> int:
    old_url = os.environ.get("EBOOK_CONVERTER_GROBID_SERVER_URL")
    try:
        os.environ.pop("EBOOK_CONVERTER_GROBID_SERVER_URL", None)
        missing = grobid_health()
        if missing.get("status") != "missing":
            raise AssertionError(f"GROBID should be optional when not configured: {missing}")

        with tempfile.TemporaryDirectory(prefix="ebook-grobid-backend-") as tmp:
            root = Path(tmp)
            pdf = root / "paper.pdf"
            make_pdf(pdf)
            normalized = normalize_grobid_tei(source=pdf, server_url="http://127.0.0.1:0", header_tei=TEI, fulltext_tei=TEI)
            if normalized.get("title") != "Academic Parsing Test" or normalized.get("reference_count") != 2:
                raise AssertionError(f"Unexpected normalized GROBID TEI: {normalized}")
            if normalized.get("authors") != ["Ada Lovelace"]:
                raise AssertionError(f"Expected normalized author name: {normalized}")
            if normalized.get("doi") != "10.1234/example" or "Introduction" not in normalized.get("section_headings", []):
                raise AssertionError(f"Expected DOI and headings: {normalized}")

            server = HTTPServer(("127.0.0.1", 0), FakeGrobidHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                os.environ["EBOOK_CONVERTER_GROBID_SERVER_URL"] = f"http://127.0.0.1:{server.server_port}"
                payload = inspect_with_grobid(pdf)
                if payload.get("status") != "ok" or payload.get("title") != "Academic Parsing Test":
                    raise AssertionError(f"Expected fake GROBID payload: {payload}")
                inspected = inspect_document(pdf, use_grobid=True)
                if (inspected.get("grobid") or {}).get("status") != "ok":
                    raise AssertionError(f"Expected embedded GROBID result: {inspected}")
            finally:
                server.shutdown()
                thread.join(timeout=5)
    finally:
        restore_env("EBOOK_CONVERTER_GROBID_SERVER_URL", old_url)

    print("GROBID backend inspect test passed.")
    return 0


class FakeGrobidHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        if self.path not in {"/api/processHeaderDocument", "/api/processFulltextDocument"}:
            self.send_response(404)
            self.end_headers()
            return
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length:
            self.rfile.read(content_length)
        data = TEI.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):  # noqa: A002
        return


def make_pdf(path: Path) -> None:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Academic Parsing Test")
    page.insert_text((72, 100), "This paper validates a lightweight GROBID integration.")
    document.save(path)
    document.close()


def restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    raise SystemExit(main())
