from unittest.mock import patch

from metascout.config import ScanConfig
from metascout.models import DiscoveredDocument, DiscoverySource
from metascout.pipeline import run_scan


def _cfg(**overrides) -> ScanConfig:
    defaults = dict(targets=["example.com"], engines=[])
    defaults.update(overrides)
    return ScanConfig(**defaults)


def test_run_scan_merges_manual_urls_with_discovered_documents():
    discovered = [DiscoveredDocument(url="https://example.com/found.pdf", source=DiscoverySource.CRAWL, filetype="pdf")]
    cfg = _cfg(manual_urls=["https://example.com/manual.pdf", "https://example.com/found.pdf"])

    downloaded_urls = []

    def fake_download_documents(documents, **kwargs):
        downloaded_urls.extend(d.url for d in documents)
        return []

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", return_value=discovered), \
         patch("metascout.pipeline.download_documents", side_effect=fake_download_documents), \
         patch("metascout.pipeline.extract_metadata", return_value=[]):
        run_scan(cfg)

    # manual.pdf is new and gets added; found.pdf was already discovered, so
    # it must not appear twice even though it's also listed manually.
    assert sorted(downloaded_urls) == ["https://example.com/found.pdf", "https://example.com/manual.pdf"]


def test_run_scan_works_with_only_manual_urls_and_no_discovery():
    cfg = _cfg(manual_urls=["https://example.com/only-manual.pdf"])

    downloaded_urls = []

    def fake_download_documents(documents, **kwargs):
        downloaded_urls.extend(d.url for d in documents)
        return []

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", return_value=[]), \
         patch("metascout.pipeline.download_documents", side_effect=fake_download_documents), \
         patch("metascout.pipeline.extract_metadata", return_value=[]):
        run_scan(cfg)

    assert downloaded_urls == ["https://example.com/only-manual.pdf"]


def test_run_scan_manual_url_document_has_manual_source_and_inferred_filetype():
    cfg = _cfg(manual_urls=["https://example.com/reports/notes.docx"])
    captured = []

    def fake_download_documents(documents, **kwargs):
        captured.extend(documents)
        return []

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", return_value=[]), \
         patch("metascout.pipeline.download_documents", side_effect=fake_download_documents), \
         patch("metascout.pipeline.extract_metadata", return_value=[]):
        run_scan(cfg)

    assert len(captured) == 1
    assert captured[0].source == DiscoverySource.MANUAL
    assert captured[0].filetype == "docx"
