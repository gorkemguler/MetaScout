from unittest.mock import MagicMock

import requests

from metascout.downloader import _download_one
from metascout.models import DiscoveredDocument, DiscoverySource


class _FakeResp:
    def __init__(self, content=b"bytes", status_code=200):
        self.content = content
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def iter_content(self, chunk_size=65536):
        yield self.content


def test_download_one_fetches_url_directly_when_no_archive_url(tmp_path):
    doc = DiscoveredDocument(url="https://example.com/a.pdf", source=DiscoverySource.CRAWL, filetype="pdf")
    session = MagicMock()
    session.get.return_value = _FakeResp(b"pdf-bytes")

    result = _download_one(doc, str(tmp_path), session, timeout=10, max_bytes=1_000_000)

    assert result.error is None
    assert result.url == "https://example.com/a.pdf"
    assert session.get.call_count == 1
    session.get.assert_called_with("https://example.com/a.pdf", stream=True, timeout=10)


def test_download_one_falls_back_to_archive_url_when_original_fails(tmp_path):
    doc = DiscoveredDocument(
        url="https://example.com/removed.pdf",
        source=DiscoverySource.WAYBACK,
        filetype="pdf",
        archive_url="https://web.archive.org/web/20200101000000id_/https://example.com/removed.pdf",
    )
    session = MagicMock()
    session.get.side_effect = [
        requests.exceptions.HTTPError("404 Not Found"),
        _FakeResp(b"archived-pdf-bytes"),
    ]

    result = _download_one(doc, str(tmp_path), session, timeout=10, max_bytes=1_000_000)

    assert result.error is None
    # Reported url stays the canonical original, not the archive.org snapshot
    # URL, so cross-engine dedup and the report both key on the same value.
    assert result.url == "https://example.com/removed.pdf"
    assert session.get.call_count == 2
    second_call_url = session.get.call_args_list[1].args[0]
    assert second_call_url == doc.archive_url


def test_download_one_reports_last_error_when_both_urls_fail(tmp_path):
    doc = DiscoveredDocument(
        url="https://example.com/gone.pdf",
        source=DiscoverySource.WAYBACK,
        filetype="pdf",
        archive_url="https://web.archive.org/web/20200101000000id_/https://example.com/gone.pdf",
    )
    session = MagicMock()
    session.get.side_effect = [
        requests.exceptions.HTTPError("404 Not Found"),
        requests.exceptions.HTTPError("archive.org also failed"),
    ]

    result = _download_one(doc, str(tmp_path), session, timeout=10, max_bytes=1_000_000)

    assert result.error == "archive.org also failed"
    assert session.get.call_count == 2


def test_download_one_does_not_try_archive_url_when_same_as_url(tmp_path):
    doc = DiscoveredDocument(url="https://example.com/a.pdf", source=DiscoverySource.CRAWL, filetype="pdf", archive_url="https://example.com/a.pdf")
    session = MagicMock()
    session.get.side_effect = requests.exceptions.HTTPError("404")

    result = _download_one(doc, str(tmp_path), session, timeout=10, max_bytes=1_000_000)

    assert result.error == "404"
    assert session.get.call_count == 1
