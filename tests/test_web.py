from unittest.mock import patch

import metascout.web as web_module
from metascout.web import create_app


def test_index_form_includes_manual_urls_field():
    app = create_app()
    client = app.test_client()
    html = client.get("/").data.decode()
    assert 'name="manual_urls"' in html
    assert 'name="targets"' in html
    assert "required" not in html.split('name="targets"')[1].split(">")[0]


def test_scan_requires_targets_or_manual_urls():
    app = create_app()
    client = app.test_client()
    resp = client.post("/scan", data={"targets": "", "manual_urls": ""})
    assert resp.status_code == 400
    assert "target" in resp.data.decode().lower()


def test_scan_requires_targets_or_manual_urls_turkish():
    app = create_app()
    client = app.test_client()
    resp = client.post("/scan", data={"targets": "", "manual_urls": "", "ui_lang": "tr"})
    assert resp.status_code == 400
    assert "hedef" in resp.data.decode().lower()


def test_index_defaults_to_english_and_lang_query_switches_to_turkish():
    app = create_app()
    client = app.test_client()

    html_en = client.get("/").data.decode()
    assert '<html lang="en">' in html_en
    assert "Targets (one per line" in html_en

    html_tr = client.get("/?lang=tr").data.decode()
    assert '<html lang="tr">' in html_tr
    assert "Hedefler (her satıra" in html_tr


def test_scan_derives_target_from_manual_urls_when_targets_empty(tmp_path):
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()

    captured_cfg = {}

    def fake_run_scan(cfg, log=None):
        captured_cfg["targets"] = cfg.targets
        captured_cfg["manual_urls"] = cfg.manual_urls
        from metascout.metadata.analyzer import analyze
        return analyze([], targets=cfg.targets)

    with patch("metascout.web.run_scan", side_effect=fake_run_scan):
        resp = client.post("/scan", data={
            "targets": "",
            "manual_urls": "https://example.com/a.pdf\nhttps://example.com/b.pdf",
            "engines": ["crawl"],
        })

    assert resp.status_code == 200
    assert captured_cfg["targets"] == ["example.com"]
    assert captured_cfg["manual_urls"] == ["https://example.com/a.pdf", "https://example.com/b.pdf"]


def test_scan_content_defaults_off_and_wires_categories_when_enabled(tmp_path):
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()

    captured_cfg = {}

    def fake_run_scan(cfg, log=None):
        captured_cfg["scan_content"] = cfg.scan_content
        captured_cfg["content_categories"] = cfg.content_categories
        from metascout.metadata.analyzer import analyze
        return analyze([], targets=cfg.targets)

    with patch("metascout.web.run_scan", side_effect=fake_run_scan):
        client.post("/scan", data={
            "targets": "example.com", "manual_urls": "", "engines": ["crawl"],
        })
    assert captured_cfg["scan_content"] is False

    with patch("metascout.web.run_scan", side_effect=fake_run_scan):
        client.post("/scan", data={
            "targets": "example.com", "manual_urls": "", "engines": ["crawl"],
            "scan_content": "on", "content_categories": ["tc_kimlik", "signature"],
        })
    assert captured_cfg["scan_content"] is True
    assert captured_cfg["content_categories"] == ["tc_kimlik", "signature"]


def test_visual_signature_defaults_off_and_wires_when_enabled(tmp_path):
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()

    captured_cfg = {}

    def fake_run_scan(cfg, log=None):
        captured_cfg["visual_signature"] = cfg.visual_signature
        from metascout.metadata.analyzer import analyze
        return analyze([], targets=cfg.targets)

    with patch("metascout.web.run_scan", side_effect=fake_run_scan):
        client.post("/scan", data={
            "targets": "example.com", "manual_urls": "", "engines": ["crawl"],
            "scan_content": "on",
        })
    assert captured_cfg["visual_signature"] is False

    with patch("metascout.web.run_scan", side_effect=fake_run_scan):
        client.post("/scan", data={
            "targets": "example.com", "manual_urls": "", "engines": ["crawl"],
            "scan_content": "on", "visual_signature": "on",
        })
    assert captured_cfg["visual_signature"] is True


def test_local_scan_index_includes_nav_and_form_fields():
    app = create_app()
    client = app.test_client()
    html = client.get("/local-scan").data.decode()
    assert 'name="local_dir"' in html
    assert 'name="local_urls"' in html
    assert "Scan Existing Documents" in html


def test_local_scan_requires_a_source():
    app = create_app()
    client = app.test_client()
    resp = client.post("/local-scan", data={"local_dir": "", "local_urls": ""})
    assert resp.status_code == 400
    assert "directory" in resp.data.decode().lower() or "url" in resp.data.decode().lower()


def test_local_scan_rejects_both_sources_at_once(tmp_path):
    app = create_app()
    client = app.test_client()
    resp = client.post("/local-scan", data={
        "local_dir": str(tmp_path), "local_urls": "https://example.com/a.pdf",
    })
    assert resp.status_code == 400
    assert "only one" in resp.data.decode().lower()


def test_local_scan_rejects_nonexistent_directory():
    app = create_app()
    client = app.test_client()
    resp = client.post("/local-scan", data={"local_dir": "/no/such/directory/anywhere", "local_urls": ""})
    assert resp.status_code == 400
    assert "exist" in resp.data.decode().lower() or "readable" in resp.data.decode().lower()


def test_local_scan_directory_mode_calls_run_local_document_scan(tmp_path):
    app = create_app(output_dir=str(tmp_path / "out"))
    client = app.test_client()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    captured = {}

    def fake_run_local(directory, *, filetypes, scan_content, content_categories, visual_signature, log=None):
        captured["directory"] = directory
        captured["scan_content"] = scan_content
        captured["visual_signature"] = visual_signature
        from metascout.metadata.analyzer import analyze
        return analyze([], targets=[directory])

    with patch("metascout.web.run_local_document_scan", side_effect=fake_run_local):
        resp = client.post("/local-scan", data={
            "local_dir": str(docs_dir), "local_urls": "",
            "scan_content": "on", "visual_signature": "on",
        })

    assert resp.status_code == 200
    assert captured["directory"] == str(docs_dir)
    assert captured["scan_content"] is True
    assert captured["visual_signature"] is True


def test_local_scan_url_mode_calls_run_scan_with_no_discovery(tmp_path):
    app = create_app(output_dir=str(tmp_path / "out"))
    client = app.test_client()

    captured_cfg = {}

    def fake_run_scan(cfg, log=None):
        captured_cfg["targets"] = cfg.targets
        captured_cfg["manual_urls"] = cfg.manual_urls
        captured_cfg["engines"] = cfg.engines
        from metascout.metadata.analyzer import analyze
        return analyze([], targets=cfg.targets)

    with patch("metascout.web.run_scan", side_effect=fake_run_scan):
        resp = client.post("/local-scan", data={
            "local_dir": "", "local_urls": "https://example.com/a.pdf\nhttps://example.com/b.pdf",
        })

    assert resp.status_code == 200
    assert captured_cfg["engines"] == []
    assert captured_cfg["targets"] == ["example.com"]
    assert captured_cfg["manual_urls"] == ["https://example.com/a.pdf", "https://example.com/b.pdf"]


def test_scan_log_stream_returns_immediately_for_unknown_scan_id():
    app = create_app()
    client = app.test_client()
    resp = client.get("/scan-log/no-such-scan-id")
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
    assert resp.get_data() == b""  # generator returns on the first iteration, nothing buffered


def test_scan_log_stream_yields_pushed_messages_as_sse_events():
    app = create_app()
    client = app.test_client()
    web_module._register_scan_log("test-scan-1")
    web_module._push_scan_log("test-scan-1", "hello from the scan")

    resp = client.get("/scan-log/test-scan-1", buffered=False)
    try:
        chunk = next(iter(resp.response))
        assert b"hello from the scan" in chunk
        assert chunk.startswith(b"data: ")
    finally:
        resp.response.close()  # stop the (otherwise long-lived) generator so the test doesn't hang


def test_register_scan_log_evicts_oldest_entry_past_the_cap():
    for i in range(web_module._SCAN_LOG_LIMIT + 5):
        web_module._register_scan_log(f"eviction-test-{i}")
    with web_module._scan_logs_lock:
        assert len(web_module._scan_logs) <= web_module._SCAN_LOG_LIMIT
        assert "eviction-test-0" not in web_module._scan_logs
        assert f"eviction-test-{web_module._SCAN_LOG_LIMIT + 4}" in web_module._scan_logs


def test_scan_post_registers_and_pushes_to_scan_log(tmp_path):
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()

    def fake_run_scan(cfg, log=None):
        log("a log line during the scan")
        from metascout.metadata.analyzer import analyze
        return analyze([], targets=cfg.targets)

    with patch("metascout.web.run_scan", side_effect=fake_run_scan):
        client.post("/scan", data={"targets": "example.com", "manual_urls": "", "engines": ["crawl"], "scan_id": "post-test-1"})

    with web_module._scan_logs_lock:
        assert "a log line during the scan" in web_module._scan_logs.get("post-test-1", [])


def _run_scan_and_extract_run_id(client) -> str:
    import re
    with patch("metascout.web.run_scan") as mock_run_scan:
        from metascout.metadata.analyzer import analyze
        mock_run_scan.side_effect = lambda cfg, log=None: analyze([], targets=cfg.targets)
        resp = client.post("/scan", data={"targets": "example.com", "manual_urls": "", "engines": ["crawl"]})
    match = re.search(r'/download/([\w-]+)', resp.get_data(as_text=True))
    assert match, "expected a download link in the report HTML"
    return match.group(1)


def test_scan_report_includes_a_working_download_link(tmp_path):
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()
    run_id = _run_scan_and_extract_run_id(client)

    resp = client.get(f"/download/{run_id}")
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"

    import io
    import zipfile
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    names = zf.namelist()
    assert f"{run_id}/report.html" in names
    assert f"{run_id}/report.json" in names


def test_download_rejects_path_traversal_attempts(tmp_path):
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()
    for bad_id in ("..", ".", "..%2f..%2fetc", "a/b", "a%2Fb"):
        resp = client.get(f"/download/{bad_id}")
        assert resp.status_code == 404, f"expected 404 for {bad_id!r}, got {resp.status_code}"


def test_download_404s_for_unknown_run_id(tmp_path):
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()
    resp = client.get("/download/no-such-run-anywhere")
    assert resp.status_code == 404


def test_download_cannot_escape_output_dir_via_sibling_prefix(tmp_path):
    # A run directory name that happens to share output_dir's prefix
    # (e.g. output_dir="./metascout_output", a sibling "./metascout_output_evil")
    # must not be reachable through naive string-prefix comparisons.
    app = create_app(output_dir=str(tmp_path / "metascout_output"))
    client = app.test_client()
    (tmp_path / "metascout_output_evil").mkdir()
    (tmp_path / "metascout_output_evil" / "secret.txt").write_text("nope")
    resp = client.get("/download/../metascout_output_evil")
    assert resp.status_code == 404


def _write_run(output_dir, run_id, *, targets, documents=1, scanned_at="2026-01-01T10:00:00+00:00", html_body="report"):
    import json
    import os
    run_dir = os.path.join(output_dir, run_id)
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump({"targets": targets, "documents_discovered": documents, "scanned_at": scanned_at}, fh)
    with open(os.path.join(run_dir, "report.html"), "w", encoding="utf-8") as fh:
        fh.write(f"<html><body>{html_body}</body></html>")


def test_history_empty_shows_friendly_message(tmp_path):
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()
    html = client.get("/history").data.decode()
    assert "No scans yet" in html


def test_history_lists_runs_newest_first(tmp_path):
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()
    _write_run(str(tmp_path), "web-20260101-100000", targets=["a.example.com"])
    _write_run(str(tmp_path), "web-20260102-100000", targets=["b.example.com"])
    html = client.get("/history").data.decode()
    assert "web-20260101-100000" in html
    assert "web-20260102-100000" in html
    # newer run should appear first in the raw HTML
    assert html.index("web-20260102-100000") < html.index("web-20260101-100000")


def test_history_view_serves_stored_report_html(tmp_path):
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()
    _write_run(str(tmp_path), "web-20260101-100000", targets=["example.com"], html_body="unique marker 12345")
    resp = client.get("/history/web-20260101-100000")
    assert resp.status_code == 200
    assert "unique marker 12345" in resp.data.decode()


def test_history_view_404s_for_unknown_or_traversal_run_id(tmp_path):
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()
    assert client.get("/history/no-such-run").status_code == 404
    assert client.get("/history/../etc").status_code == 404


def test_history_escapes_target_values_to_prevent_xss(tmp_path):
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()
    _write_run(str(tmp_path), "web-20260101-100000", targets=["<script>alert(1)</script>"])
    html = client.get("/history").data.decode()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_history_skips_run_directories_without_report_json(tmp_path):
    import os
    app = create_app(output_dir=str(tmp_path))
    client = app.test_client()
    os.makedirs(str(tmp_path / "web-20260101-100000"))  # no report.json inside
    html = client.get("/history").data.decode()
    assert "No scans yet" in html
