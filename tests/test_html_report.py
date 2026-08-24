import pytest

from metascout.metadata.analyzer import analyze
from metascout.models import DocumentMetadata
from metascout.report import render_html_report


def _sample_findings():
    doc = DocumentMetadata(
        url="https://example.com/report.pdf",
        local_path="/tmp/report.pdf",
        filetype="pdf",
        raw={"PDF:Author": "jdoe", "PDF:Producer": "Microsoft Word: Windows PDF Library"},
    )
    return analyze([doc], targets=["example.com"])


def test_render_html_report_defaults_to_english():
    html = render_html_report(_sample_findings())
    assert '<html lang="en">' in html
    assert "Metadata Leak Report" in html
    assert "Usernames" in html


def test_render_html_report_turkish():
    html = render_html_report(_sample_findings(), lang="tr")
    assert '<html lang="tr">' in html
    assert "Metadata Sızıntı Raporu" in html
    assert "Kullanıcı Adları" in html


def test_render_html_report_rejects_unsupported_language():
    with pytest.raises(ValueError):
        render_html_report(_sample_findings(), lang="fr")
