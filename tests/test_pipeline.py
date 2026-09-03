from unittest.mock import patch

from metascout.config import ScanConfig
from metascout.models import ContentFinding, DiscoveredDocument, DiscoverySource, DocumentMetadata, DownloadedDocument
from metascout.pipeline import run_local_document_scan, run_scan, scan_visual_signatures


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


def test_run_scan_leaves_content_findings_empty_when_scan_content_disabled():
    cfg = _cfg(manual_urls=["https://example.com/a.pdf"], scan_content=False)
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf")]

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", return_value=[]), \
         patch("metascout.pipeline.download_documents", return_value=[]), \
         patch("metascout.pipeline.extract_metadata", return_value=doc_metadata), \
         patch("metascout.pipeline.scan_document") as mock_scan_document:
        findings = run_scan(cfg)

    mock_scan_document.assert_not_called()
    assert findings.content_findings == []


def test_run_scan_calls_content_scan_when_enabled_and_attaches_document_url():
    cfg = _cfg(
        manual_urls=["https://example.com/a.pdf"],
        scan_content=True,
        content_categories=["tc_kimlik"],
    )
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf")]
    fake_hit = ContentFinding(document_url="", category="tc_kimlik", masked_value="123******78")

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", return_value=[]), \
         patch("metascout.pipeline.download_documents", return_value=[]), \
         patch("metascout.pipeline.extract_metadata", return_value=doc_metadata), \
         patch("metascout.pipeline.scan_document", return_value=[fake_hit]) as mock_scan_document:
        findings = run_scan(cfg)

    mock_scan_document.assert_called_once_with("/tmp/a.pdf", "pdf", categories={"tc_kimlik"})
    assert len(findings.content_findings) == 1
    assert findings.content_findings[0].document_url == "https://example.com/a.pdf"


def test_run_scan_skips_content_scan_for_documents_with_download_errors():
    cfg = _cfg(manual_urls=["https://example.com/a.pdf"], scan_content=True)
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="", filetype="pdf", error="404")]

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", return_value=[]), \
         patch("metascout.pipeline.download_documents", return_value=[]), \
         patch("metascout.pipeline.extract_metadata", return_value=doc_metadata), \
         patch("metascout.pipeline.scan_document") as mock_scan_document:
        run_scan(cfg)

    mock_scan_document.assert_not_called()


def test_run_scan_does_not_call_visual_signature_when_flag_is_off():
    cfg = _cfg(manual_urls=["https://example.com/a.pdf"], scan_content=True, visual_signature=False)
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf")]

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", return_value=[]), \
         patch("metascout.pipeline.download_documents", return_value=[]), \
         patch("metascout.pipeline.extract_metadata", return_value=doc_metadata), \
         patch("metascout.pipeline.scan_document", return_value=[]), \
         patch("metascout.pipeline.detect_visual_signature") as mock_detect:
        run_scan(cfg)

    mock_detect.assert_not_called()


def test_run_scan_calls_visual_signature_when_flag_is_on_and_appends_finding():
    cfg = _cfg(
        manual_urls=["https://example.com/a.pdf"],
        scan_content=True, content_categories=[], visual_signature=True,
    )
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf")]

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", return_value=[]), \
         patch("metascout.pipeline.download_documents", return_value=[]), \
         patch("metascout.pipeline.extract_metadata", return_value=doc_metadata), \
         patch("metascout.pipeline.scan_document") as mock_scan_document, \
         patch("metascout.pipeline.detect_visual_signature", return_value=True) as mock_detect:
        findings = run_scan(cfg)

    mock_scan_document.assert_not_called()  # no text categories selected
    mock_detect.assert_called_once_with("/tmp/a.pdf", "pdf")
    assert len(findings.content_findings) == 1
    assert findings.content_findings[0].category == "signature"
    assert findings.content_findings[0].document_url == "https://example.com/a.pdf"


def test_run_scan_visual_signature_false_result_adds_no_finding():
    cfg = _cfg(
        manual_urls=["https://example.com/a.pdf"],
        scan_content=True, content_categories=[], visual_signature=True,
    )
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf")]

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", return_value=[]), \
         patch("metascout.pipeline.download_documents", return_value=[]), \
         patch("metascout.pipeline.extract_metadata", return_value=doc_metadata), \
         patch("metascout.pipeline.detect_visual_signature", return_value=False):
        findings = run_scan(cfg)

    assert findings.content_findings == []


def test_run_scan_visual_signature_disabled_when_content_categories_empty_and_flag_off():
    cfg = _cfg(manual_urls=["https://example.com/a.pdf"], scan_content=True, content_categories=[], visual_signature=False)
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf")]

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", return_value=[]), \
         patch("metascout.pipeline.download_documents", return_value=[]), \
         patch("metascout.pipeline.extract_metadata", return_value=doc_metadata), \
         patch("metascout.pipeline.scan_document") as mock_scan_document, \
         patch("metascout.pipeline.detect_visual_signature") as mock_detect:
        findings = run_scan(cfg)

    mock_scan_document.assert_not_called()
    mock_detect.assert_not_called()
    assert findings.content_findings == []


def test_run_scan_visual_signature_works_independently_of_scan_content():
    # Regression: --visual-signature used to only take effect nested inside
    # --scan-content. It's now fully independent — a user should be able to
    # turn on just the (slow) visual check without the (fast) text/PII scan.
    cfg = _cfg(manual_urls=["https://example.com/a.pdf"], scan_content=False, visual_signature=True)
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf")]

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", return_value=[]), \
         patch("metascout.pipeline.download_documents", return_value=[]), \
         patch("metascout.pipeline.extract_metadata", return_value=doc_metadata), \
         patch("metascout.pipeline.scan_document") as mock_scan_document, \
         patch("metascout.pipeline.detect_visual_signature", return_value=True) as mock_detect:
        findings = run_scan(cfg)

    mock_scan_document.assert_not_called()  # scan_content is off
    mock_detect.assert_called_once_with("/tmp/a.pdf", "pdf")
    assert len(findings.content_findings) == 1
    assert findings.content_findings[0].category == "signature"


def test_scan_visual_signatures_skips_documents_with_errors():
    doc_metadata = [
        DocumentMetadata(url="https://example.com/ok.pdf", local_path="/tmp/ok.pdf", filetype="pdf"),
        DocumentMetadata(url="https://example.com/bad.pdf", local_path="", filetype="pdf", error="404"),
    ]
    with patch("metascout.pipeline.detect_visual_signature", return_value=True) as mock_detect:
        hits = scan_visual_signatures(doc_metadata)

    mock_detect.assert_called_once_with("/tmp/ok.pdf", "pdf")
    assert len(hits) == 1
    assert hits[0].document_url == "https://example.com/ok.pdf"


def test_scan_visual_signatures_logs_and_returns_empty_when_dependency_missing():
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf")]
    logs = []
    with patch("metascout.pipeline.missing_dependencies", return_value=["signature-detect (...)"]), \
         patch("metascout.pipeline.detect_visual_signature") as mock_detect:
        hits = scan_visual_signatures(doc_metadata, log=logs.append)

    mock_detect.assert_not_called()
    assert hits == []
    assert any("missing optional dependencies" in m for m in logs)


# --- Critical/sensitive files discovery (ScanConfig.critical_files) ---

def test_run_scan_leaves_critical_files_empty_when_disabled():
    cfg = _cfg(manual_urls=["https://example.com/a.pdf"], critical_files=False)
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf")]

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", return_value=[]) as mock_discover, \
         patch("metascout.pipeline.download_documents", return_value=[]), \
         patch("metascout.pipeline.extract_metadata", return_value=doc_metadata):
        findings = run_scan(cfg)

    # Only the one (mocked) call for the main document search — no second
    # discovery pass for critical files when the flag is off.
    mock_discover.assert_called_once()
    assert findings.critical_files == []


def test_run_scan_discovers_and_downloads_critical_files_when_enabled():
    cfg = _cfg(
        manual_urls=["https://example.com/a.pdf"],
        critical_files=True, critical_file_types=["env", "log"],
    )
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf")]
    critical_discovered = [DiscoveredDocument(url="https://example.com/.env", source=DiscoverySource.CRAWL, filetype="env")]

    discover_calls = []

    def fake_discover_all(cfg, log=None, *, filetypes=None):
        discover_calls.append(filetypes)
        return critical_discovered if filetypes == ["env", "log"] else []

    downloaded_dirs = []

    def fake_download_documents(documents, *, dest_dir, **kwargs):
        downloaded_dirs.append(dest_dir)
        return [DownloadedDocument(url=d.url, local_path="/tmp/.env", filetype=d.filetype, source=d.source, size_bytes=42) for d in documents]

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", side_effect=fake_discover_all), \
         patch("metascout.pipeline.download_documents", side_effect=fake_download_documents), \
         patch("metascout.pipeline.extract_metadata", return_value=doc_metadata):
        findings = run_scan(cfg)

    assert discover_calls == [None, ["env", "log"]]  # main pass, then the critical-files pass
    assert any(d.endswith("critical_files") for d in downloaded_dirs)
    assert len(findings.critical_files) == 1
    assert findings.critical_files[0].url == "https://example.com/.env"
    assert findings.critical_files[0].filetype == "env"
    assert findings.critical_files[0].size_bytes == 42


def test_run_scan_critical_files_populated_even_when_no_regular_documents_found():
    # Independent of the main document search on purpose — someone may only
    # care about exposed .env/.log-style files, not pdf/doc/... documents.
    cfg = _cfg(critical_files=True, critical_file_types=["env"])
    critical_discovered = [DiscoveredDocument(url="https://example.com/.env", source=DiscoverySource.CRAWL, filetype="env")]

    def fake_discover_all(cfg, log=None, *, filetypes=None):
        return critical_discovered if filetypes == ["env"] else []

    def fake_download_documents(documents, **kwargs):
        return [DownloadedDocument(url=d.url, local_path="/tmp/.env", filetype=d.filetype, source=d.source) for d in documents]

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", side_effect=fake_discover_all), \
         patch("metascout.pipeline.download_documents", side_effect=fake_download_documents), \
         patch("metascout.pipeline.extract_metadata", return_value=[]):
        findings = run_scan(cfg)

    assert findings.documents == []
    assert len(findings.critical_files) == 1


def test_run_scan_scans_critical_files_content_when_scan_content_enabled():
    cfg = _cfg(
        manual_urls=["https://example.com/a.pdf"],
        critical_files=True, critical_file_types=["env"],
        scan_content=True, content_categories=["secrets"],
    )
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf")]
    critical_discovered = [DiscoveredDocument(url="https://example.com/.env", source=DiscoverySource.CRAWL, filetype="env")]

    def fake_discover_all(cfg, log=None, *, filetypes=None):
        return critical_discovered if filetypes == ["env"] else []

    def fake_download_documents(documents, **kwargs):
        return [DownloadedDocument(url=d.url, local_path="/tmp/critical.env", filetype=d.filetype, source=d.source) for d in documents]

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", side_effect=fake_discover_all), \
         patch("metascout.pipeline.download_documents", side_effect=fake_download_documents), \
         patch("metascout.pipeline.extract_metadata", return_value=doc_metadata), \
         patch("metascout.pipeline.scan_document") as mock_scan_document:
        mock_scan_document.return_value = []
        run_scan(cfg)

    called_paths = {call.args[0] for call in mock_scan_document.call_args_list}
    assert called_paths == {"/tmp/a.pdf", "/tmp/critical.env"}


def test_run_scan_does_not_scan_critical_files_content_when_scan_content_disabled():
    cfg = _cfg(
        manual_urls=["https://example.com/a.pdf"],
        critical_files=True, critical_file_types=["env"], scan_content=False,
    )
    doc_metadata = [DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf")]
    critical_discovered = [DiscoveredDocument(url="https://example.com/.env", source=DiscoverySource.CRAWL, filetype="env")]

    def fake_discover_all(cfg, log=None, *, filetypes=None):
        return critical_discovered if filetypes == ["env"] else []

    def fake_download_documents(documents, **kwargs):
        return [DownloadedDocument(url=d.url, local_path="/tmp/critical.env", filetype=d.filetype, source=d.source) for d in documents]

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.discover_all", side_effect=fake_discover_all), \
         patch("metascout.pipeline.download_documents", side_effect=fake_download_documents), \
         patch("metascout.pipeline.extract_metadata", return_value=doc_metadata), \
         patch("metascout.pipeline.scan_document") as mock_scan_document:
        findings = run_scan(cfg)

    mock_scan_document.assert_not_called()
    assert len(findings.critical_files) == 1


def test_run_local_document_scan_lists_critical_files_separately(tmp_path):
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "config.env").write_text("DB_PASSWORD=hunter2\n")

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.extract_metadata", side_effect=lambda docs: [
             DocumentMetadata(url=d.url, local_path=d.local_path, filetype=d.filetype) for d in docs
         ]):
        findings = run_local_document_scan(
            str(tmp_path), filetypes=["pdf"],
            critical_files=True, critical_file_types=["env"],
        )

    assert len(findings.documents) == 1
    assert findings.documents[0].filetype == "pdf"
    assert len(findings.critical_files) == 1
    assert findings.critical_files[0].filetype == "env"


def test_run_local_document_scan_critical_files_off_by_default(tmp_path):
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "config.env").write_text("DB_PASSWORD=hunter2\n")

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.extract_metadata", side_effect=lambda docs: [
             DocumentMetadata(url=d.url, local_path=d.local_path, filetype=d.filetype) for d in docs
         ]):
        findings = run_local_document_scan(str(tmp_path), filetypes=["pdf"])

    assert findings.critical_files == []


def test_run_local_document_scan_works_with_only_critical_files_no_regular_documents(tmp_path):
    (tmp_path / "config.env").write_text("DB_PASSWORD=hunter2\n")

    with patch("metascout.pipeline.exiftool_available", return_value=True):
        findings = run_local_document_scan(
            str(tmp_path), filetypes=["pdf"],
            critical_files=True, critical_file_types=["env"],
        )

    assert findings.documents == []
    assert len(findings.critical_files) == 1


def test_run_local_document_scan_scans_critical_files_content_when_scan_content_enabled(tmp_path):
    (tmp_path / "config.env").write_text("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n")

    with patch("metascout.pipeline.exiftool_available", return_value=True):
        findings = run_local_document_scan(
            str(tmp_path), filetypes=["pdf"],
            critical_files=True, critical_file_types=["env"],
            scan_content=True, content_categories=["secrets"],
        )

    assert len(findings.content_findings) == 1
    assert findings.content_findings[0].category == "secret:AWS Access Key ID"
    assert findings.content_findings[0].document_url.endswith("config.env")


def test_run_local_document_scan_extension_in_both_lists_counts_only_as_document(tmp_path):
    # A file matching --filetypes must not also be double-listed under
    # critical_files, even if the same extension is (unusually) present in
    # --critical-file-types too.
    (tmp_path / "notes.txt").write_text("hello\n")

    with patch("metascout.pipeline.exiftool_available", return_value=True), \
         patch("metascout.pipeline.extract_metadata", side_effect=lambda docs: [
             DocumentMetadata(url=d.url, local_path=d.local_path, filetype=d.filetype) for d in docs
         ]):
        findings = run_local_document_scan(
            str(tmp_path), filetypes=["txt"],
            critical_files=True, critical_file_types=["txt"],
        )

    assert len(findings.documents) == 1
    assert findings.critical_files == []
