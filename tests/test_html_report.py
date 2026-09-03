import pytest

from metascout.metadata.analyzer import analyze
from metascout.models import CriticalFile, DiscoverySource, DocumentMetadata
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


def test_render_html_report_omits_critical_files_section_when_none_found():
    for lang in ("en", "tr"):
        html = render_html_report(_sample_findings(), lang=lang)
        assert 'id="critical-files"' not in html


@pytest.mark.parametrize("lang,heading", [("en", "Critical / Sensitive Files"), ("tr", "Kritik / Hassas Dosyalar")])
def test_render_html_report_includes_critical_files_section(lang, heading):
    findings = _sample_findings()
    findings.critical_files = [
        CriticalFile(url="https://example.com/.env", filetype="env", source=DiscoverySource.CRAWL, size_bytes=1200),
        CriticalFile(url="https://example.com/backup.sql", filetype="sql", source=DiscoverySource.WAYBACK, error="404 Not Found"),
    ]
    html = render_html_report(findings, lang=lang)
    assert 'id="critical-files"' in html
    assert heading in html
    assert "backup.sql" in html
    assert "404 Not Found" in html


def test_render_html_report_no_findings_badge_suppressed_when_only_critical_files_present():
    # Regression: a scan that found nothing else but did turn up critical
    # files must not claim "No Findings" — their existence is itself a finding.
    findings = analyze([], targets=["example.com"])
    findings.critical_files = [CriticalFile(url="https://example.com/.env", filetype="env", source=DiscoverySource.CRAWL)]
    html = render_html_report(findings, lang="en")
    assert "No Findings</span>" not in html
