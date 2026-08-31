from unittest.mock import patch

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
