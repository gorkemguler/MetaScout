import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from metascout.cli import main
from metascout.report import pdf_report
from metascout.report.pdf_report import PdfDependencyMissing, render_pdf_report

pytestmark = pytest.mark.skipif(not pdf_report.PDF_AVAILABLE, reason="reportlab not installed ([pdf] extra)")

_SNAPSHOT = "https://web.archive.org/web/20200101000000id_/https://example.com/removed.pdf"


def _payload():
    return {
        "targets": ["example.com", "example.org"],
        "scanned_at": "2026-01-15T09:30:00+00:00",
        "documents_discovered": 3,
        "documents_with_metadata": 2,
        "documents_by_target": {"example.com": 2, "example.org": 1},
        "documents": [
            {"url": "https://example.com/live.pdf", "filetype": "pdf", "local_path": "/tmp/a.pdf",
             "error": None, "archive_url": None, "metadata": {"PDF:Author": "jdoe"}},
            {"url": "https://example.com/removed.pdf", "filetype": "pdf", "local_path": "/tmp/b.pdf",
             "error": None, "archive_url": _SNAPSHOT, "metadata": {"PDF:Author": "asmith"}},
            {"url": "https://example.org/broken.docx", "filetype": "docx", "local_path": "",
             "error": "404 Client Error: Not Found", "archive_url": None, "metadata": {}},
        ],
        "findings": {
            "usernames": {"jdoe": {"document_urls": ["https://example.com/live.pdf"], "field_name": "Author"},
                          "şaziye çağlar": {"document_urls": ["https://example.com/removed.pdf"], "field_name": "Author"}},
            "emails": {},
            "software": {"Adobe InDesign 20.4 (Macintosh)": {"document_urls": ["https://example.com/live.pdf"], "field_name": "Creator"}},
            "operating_systems": {},
            "internal_paths": {"/Users/tasarım-01/Desktop/2025 Yıllık/kapak.tif":
                               {"document_urls": ["https://example.com/live.pdf"], "field_name": "IngredientsFilePath"}},
            "servers_and_printers": {},
            "geolocation": {},
        },
        "content_findings": [
            {"document_url": "https://example.com/live.pdf", "category": "tc_kimlik", "masked_value": "123*****89", "context": "..."}
        ],
        "critical_files": [{"url": "https://example.com/.env", "filetype": "env", "error": None}],
        "errors": ["https://example.org/broken.docx: 404 Client Error: Not Found"],
    }


def _text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader
    import io
    return "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(pdf_bytes)).pages)


@pytest.mark.parametrize("lang,heading", [("en", "Metadata Leak Report"), ("tr", "Metadata Sızıntı Raporu")])
def test_render_pdf_report_covers_every_section(lang, heading):
    pdf = render_pdf_report(_payload(), lang=lang)

    assert pdf.startswith(b"%PDF-")
    text = _text(pdf)
    assert heading in text
    assert "example.com" in text
    # findings, content scan, critical files and the document list all present
    assert "jdoe" in text
    assert "/Users/tasarım-01/Desktop/2025 Yıllık/kapak.tif" in text
    assert "123*****89" in text
    assert ".env" in text
    assert "https://example.com/live.pdf" in text


def test_render_pdf_report_keeps_turkish_characters():
    text = _text(render_pdf_report(_payload(), lang="tr"))

    assert "şaziye çağlar" in text
    assert "İç Dosya Yolları" in text


def test_render_pdf_report_marks_archived_documents():
    en = _text(render_pdf_report(_payload(), lang="en"))
    tr = _text(render_pdf_report(_payload(), lang="tr"))

    assert "ARCHIVE" in en
    assert "1 document(s) are no longer live" in en
    assert "ARŞİV" in tr


def test_render_pdf_report_risk_reflects_critical_content():
    assert "High Risk" in _text(render_pdf_report(_payload(), lang="en"))

    quiet = _payload()
    quiet["content_findings"] = []
    quiet["critical_files"] = []
    quiet["findings"] = {k: {} for k in quiet["findings"]}
    assert "No Findings" in _text(render_pdf_report(quiet, lang="en"))


def test_render_pdf_report_rejects_unknown_language():
    with pytest.raises(ValueError, match="Unsupported report language"):
        render_pdf_report(_payload(), lang="de")


def test_render_pdf_report_handles_an_empty_run():
    empty = {"targets": ["example.com"], "scanned_at": "", "documents": [], "findings": {}}

    pdf = render_pdf_report(empty, lang="en")

    assert pdf.startswith(b"%PDF-")
    assert "No findings in this category" in _text(pdf)


def test_cli_pdf_command_builds_from_an_existing_run(tmp_path):
    run_dir = tmp_path / "web-20260101-120000"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(json.dumps(_payload()), encoding="utf-8")

    result = CliRunner().invoke(main, ["pdf", str(run_dir), "--lang", "tr"])

    assert result.exit_code == 0, result.output
    pdf = (run_dir / "report.pdf").read_bytes()
    assert pdf.startswith(b"%PDF-")
    assert "Metadata Sızıntı Raporu" in _text(pdf)


def test_cli_pdf_command_writes_to_out_path(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(json.dumps(_payload()), encoding="utf-8")
    out = tmp_path / "elsewhere" / "custom.pdf"
    out.parent.mkdir()

    result = CliRunner().invoke(main, ["pdf", str(run_dir), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert out.read_bytes().startswith(b"%PDF-")
    assert not (run_dir / "report.pdf").exists()


def test_cli_pdf_command_needs_a_report_json(tmp_path):
    result = CliRunner().invoke(main, ["pdf", str(tmp_path)])

    assert result.exit_code != 0
    assert "report.json" in result.output


def test_cli_pdf_command_explains_a_missing_extra(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(json.dumps(_payload()), encoding="utf-8")

    with patch("metascout.cli.render_pdf_report", side_effect=PdfDependencyMissing("no reportlab")):
        result = CliRunner().invoke(main, ["pdf", str(run_dir)])

    assert result.exit_code == 1
    assert "metascout[pdf]" in result.output
    assert not (run_dir / "report.pdf").exists()


def test_pdf_report_shows_classification_labels():
    payload = _payload()
    payload["findings"]["classification_labels"] = {
        "Classification: NATO RESTRICTED": {"document_urls": ["https://example.com/live.pdf"], "field_name": "Metadata"},
    }
    payload["content_findings"] = []  # so the risk comes from the label alone

    text = _text(render_pdf_report(payload, lang="en"))

    assert "Classification Labels" in text
    assert "NATO RESTRICTED" in text
    assert "not meant to be public" in text
    assert "High Risk" in text
