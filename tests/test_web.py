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
    assert "hedef" in resp.data.decode().lower()


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
