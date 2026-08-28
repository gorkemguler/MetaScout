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
