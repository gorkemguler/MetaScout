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


def test_summary_notes_documents_that_came_from_the_archive(capsys):
    from metascout.cli import _print_summary
    from metascout.metadata.analyzer import analyze
    from metascout.models import DocumentMetadata

    docs = [
        DocumentMetadata(url="https://example.com/live.pdf", local_path="/tmp/a.pdf", filetype="pdf",
                         raw={"PDF:Author": "jdoe"}),
        DocumentMetadata(url="https://example.com/gone.pdf", local_path="/tmp/b.pdf", filetype="pdf",
                         raw={"PDF:Author": "asmith"},
                         archive_url="https://web.archive.org/web/20200101000000id_/https://example.com/gone.pdf"),
    ]

    _print_summary(analyze(docs, targets=["example.com"]))

    out = capsys.readouterr().out
    # rich wraps at terminal width, so match on unwrapped fragments.
    assert "1 document(s) were no longer live" in out
    assert "Wayback Machine" in out


def test_cli_log_keeps_extras_in_install_advice(capsys):
    """rich reads "[content-scan]" as a markup tag; the advice has to survive."""
    from metascout.cli import _cli_log

    _cli_log("! pypdf missing. Install with `pip install 'metascout[content-scan]'` for full coverage")

    assert "metascout[content-scan]" in capsys.readouterr().out
