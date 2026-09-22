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
    session.get.return_value = _FakeResp(b"%PDF-1.7 pdf-bytes")

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
        _FakeResp(b"%PDF-1.7 archived-pdf-bytes"),
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


def test_download_one_records_the_archive_url_it_actually_fetched_from(tmp_path):
    doc = DiscoveredDocument(
        url="https://example.com/removed.pdf",
        source=DiscoverySource.WAYBACK,
        filetype="pdf",
        archive_url="https://web.archive.org/web/20200101000000id_/https://example.com/removed.pdf",
    )
    session = MagicMock()
    session.get.side_effect = [requests.exceptions.HTTPError("404 Not Found"), _FakeResp(b"%PDF-1.7 archived")]

    result = _download_one(doc, str(tmp_path), session, timeout=10, max_bytes=1_000_000)

    # The report needs to say this copy is only still public via the archive.
    assert result.archive_url == doc.archive_url


def test_download_one_leaves_archive_url_empty_when_the_live_url_served_the_file(tmp_path):
    doc = DiscoveredDocument(
        url="https://example.com/live.pdf",
        source=DiscoverySource.WAYBACK,
        filetype="pdf",
        archive_url="https://web.archive.org/web/20200101000000id_/https://example.com/live.pdf",
    )
    session = MagicMock()
    session.get.return_value = _FakeResp(b"%PDF-1.7 pdf-bytes")

    result = _download_one(doc, str(tmp_path), session, timeout=10, max_bytes=1_000_000)

    assert result.archive_url is None


def test_download_one_rejects_a_bot_check_page_served_as_a_pdf(tmp_path):
    """A 200 response carrying an HTML cookie/bot-check page (what some sites
    answer a .pdf URL with) must not be stored or counted as the document."""
    doc = DiscoveredDocument(url="https://example.com/ilan.pdf", source=DiscoverySource.CRAWL, filetype="pdf")
    session = MagicMock()
    session.get.return_value = _FakeResp(b"<html><body onload='resend();'><script>document.cookie=\"x\";</script></body></html>")

    result = _download_one(doc, str(tmp_path), session, timeout=10, max_bytes=1_000_000)

    assert result.local_path == ""
    assert "HTML page" in result.error
    assert "not a pdf file" in result.error
    assert list(tmp_path.iterdir()) == []


def test_download_one_falls_back_to_the_archive_when_the_live_site_serves_a_bot_check(tmp_path):
    snapshot = "https://web.archive.org/web/20120101000000id_/http://example.com/ilan.pdf"
    doc = DiscoveredDocument(
        url="http://example.com/ilan.pdf", source=DiscoverySource.WAYBACK, filetype="pdf", archive_url=snapshot,
    )
    session = MagicMock()
    session.get.side_effect = [_FakeResp(b"<html><body onload='resend();'></body></html>"), _FakeResp(b"%PDF-1.4 real")]

    result = _download_one(doc, str(tmp_path), session, timeout=10, max_bytes=1_000_000)

    assert result.error is None
    assert result.archive_url == snapshot
    assert open(result.local_path, "rb").read().startswith(b"%PDF")


def test_download_one_accepts_office_and_unknown_types(tmp_path):
    for filetype, payload in [("docx", b"PK\x03\x04zip"), ("doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1ole"),
                              ("txt", b"just text"), ("", b"anything at all")]:
        doc = DiscoveredDocument(url=f"https://example.com/a.{filetype}", source=DiscoverySource.CRAWL, filetype=filetype)
        session = MagicMock()
        session.get.return_value = _FakeResp(payload)

        result = _download_one(doc, str(tmp_path), session, timeout=10, max_bytes=1_000_000)

        assert result.error is None, (filetype, result.error)


def test_download_one_accepts_a_pdf_with_junk_before_the_header(tmp_path):
    doc = DiscoveredDocument(url="https://example.com/a.pdf", source=DiscoverySource.CRAWL, filetype="pdf")
    session = MagicMock()
    session.get.return_value = _FakeResp(b"\r\n   %PDF-1.5 body")

    result = _download_one(doc, str(tmp_path), session, timeout=10, max_bytes=1_000_000)

    assert result.error is None
