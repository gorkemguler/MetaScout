import json
from unittest.mock import patch

from click.testing import CliRunner

from metascout.cli import main
from metascout.models import ContentFinding


def _write_report(report_dir, documents):
    report_dir.mkdir(parents=True, exist_ok=True)
    with open(report_dir / "report.json", "w", encoding="utf-8") as fh:
        json.dump({"documents": documents}, fh)


def test_visual_signature_scan_requires_report_json(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["visual-signature-scan", str(tmp_path)])
    assert result.exit_code != 0
    assert "report.json" in result.output


def test_visual_signature_scan_fails_clearly_when_dependency_missing(tmp_path):
    local_pdf = tmp_path / "a.pdf"
    local_pdf.write_bytes(b"%PDF-1.4\n")
    _write_report(tmp_path, [{"url": "https://example.com/a.pdf", "filetype": "pdf", "local_path": str(local_pdf), "error": None}])

    runner = CliRunner()
    with patch("metascout.content_scan.missing_dependencies", return_value=["signature-detect (...)"]):
        result = runner.invoke(main, ["visual-signature-scan", str(tmp_path)])

    assert result.exit_code != 0
    assert "not installed" in result.output


def test_visual_signature_scan_skips_documents_with_no_local_file(tmp_path):
    _write_report(tmp_path, [{"url": "https://example.com/missing.pdf", "filetype": "pdf", "local_path": "", "error": None}])

    runner = CliRunner()
    with patch("metascout.content_scan.missing_dependencies", return_value=[]):
        result = runner.invoke(main, ["visual-signature-scan", str(tmp_path)])

    assert result.exit_code == 0
    assert "Nothing to scan" in result.output


def test_visual_signature_scan_writes_results_json(tmp_path):
    local_pdf = tmp_path / "a.pdf"
    local_pdf.write_bytes(b"%PDF-1.4\n")
    _write_report(tmp_path, [{"url": "https://example.com/a.pdf", "filetype": "pdf", "local_path": str(local_pdf), "error": None}])

    fake_hit = ContentFinding(document_url="https://example.com/a.pdf", category="signature", masked_value="visual: ...")
    runner = CliRunner()
    with patch("metascout.content_scan.missing_dependencies", return_value=[]), \
            patch("metascout.pipeline.scan_visual_signatures", return_value=[fake_hit]):
        result = runner.invoke(main, ["visual-signature-scan", str(tmp_path)])

    assert result.exit_code == 0, result.output
    out_file = tmp_path / "visual_signature_report.json"
    assert out_file.exists()
    payload = json.loads(out_file.read_text())
    assert payload == [{"url": "https://example.com/a.pdf", "filetype": "pdf", "visual_signature_detected": True}]
