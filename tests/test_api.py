import threading
import time
from unittest.mock import patch

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from metascout.api import create_app  # noqa: E402
from metascout.metadata.analyzer import analyze  # noqa: E402
from metascout.models import ContentFinding, CriticalFile, DiscoverySource, DocumentMetadata  # noqa: E402


def _client(tmp_path, **kwargs) -> TestClient:
    app = create_app(output_dir=str(tmp_path), **kwargs)
    return TestClient(app)


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/v1/scans/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach a terminal status within {timeout}s")


def test_health_endpoint(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["active_jobs"] == 0


def test_create_scan_requires_target_or_manual_urls(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/v1/scans", json={})
    assert resp.status_code == 422


def test_create_scan_returns_202_with_job_id_and_links(tmp_path):
    client = _client(tmp_path)
    with patch("metascout.api.app.run_scan", return_value=analyze([], targets=["example.com"])):
        resp = client.post("/v1/scans", json={"targets": ["example.com"]})
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["job_id"]
    assert body["links"]["self"].endswith(f"/v1/scans/{body['job_id']}")
    assert body["links"]["report_json"].endswith("/report.json")


def test_create_scan_derives_target_from_manual_urls_when_targets_empty(tmp_path):
    client = _client(tmp_path)
    captured = {}

    def fake_run_scan(cfg, log=None):
        captured["targets"] = cfg.targets
        captured["manual_urls"] = cfg.manual_urls
        return analyze([], targets=cfg.targets)

    with patch("metascout.api.app.run_scan", side_effect=fake_run_scan):
        resp = client.post("/v1/scans", json={"manual_urls": ["https://example.com/a.pdf"]})
        job_id = resp.json()["job_id"]
        _wait_for_job(client, job_id)

    assert captured["targets"] == ["example.com"]
    assert captured["manual_urls"] == ["https://example.com/a.pdf"]


def test_scan_job_lifecycle_reaches_done_with_summary(tmp_path):
    client = _client(tmp_path)
    doc = DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf", raw={"PDF:Author": "jdoe"})
    fake_findings = analyze([doc], targets=["example.com"])

    with patch("metascout.api.app.run_scan", return_value=fake_findings):
        resp = client.post("/v1/scans", json={"targets": ["example.com"]})
        job_id = resp.json()["job_id"]
        final = _wait_for_job(client, job_id)

    assert final["status"] == "done"
    assert final["kind"] == "scan"
    assert final["summary"]["documents_discovered"] == 1
    assert final["error"] is None
    assert final["started_at"] is not None
    assert final["finished_at"] is not None


def test_scan_job_error_status_when_pipeline_raises(tmp_path):
    client = _client(tmp_path)
    with patch("metascout.api.app.run_scan", side_effect=RuntimeError("exiftool not found on PATH.")):
        resp = client.post("/v1/scans", json={"targets": ["example.com"]})
        job_id = resp.json()["job_id"]
        final = _wait_for_job(client, job_id)

    assert final["status"] == "error"
    assert "exiftool not found" in final["error"]
    assert final["summary"] is None


def test_get_unknown_job_returns_404(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/v1/scans/does-not-exist")
    assert resp.status_code == 404


def test_report_json_and_html_return_409_before_job_is_done(tmp_path):
    client = _client(tmp_path)
    started = threading.Event()

    def slow_run_scan(cfg, log=None):
        started.set()
        time.sleep(0.3)
        return analyze([], targets=cfg.targets)

    with patch("metascout.api.app.run_scan", side_effect=slow_run_scan):
        resp = client.post("/v1/scans", json={"targets": ["example.com"]})
        job_id = resp.json()["job_id"]
        started.wait(timeout=2)

        r_json = client.get(f"/v1/scans/{job_id}/report.json")
        r_html = client.get(f"/v1/scans/{job_id}/report.html")
        r_zip = client.get(f"/v1/scans/{job_id}/download")

        assert r_json.status_code == 409
        assert r_html.status_code == 409
        assert r_zip.status_code == 409
        assert r_json.json()["detail"]["status"] in ("queued", "running")

        _wait_for_job(client, job_id)


def test_report_json_and_html_available_once_done(tmp_path):
    client = _client(tmp_path)
    doc = DocumentMetadata(url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf", raw={"PDF:Author": "jdoe"})
    fake_findings = analyze([doc], targets=["example.com"])

    with patch("metascout.api.app.run_scan", return_value=fake_findings):
        resp = client.post("/v1/scans", json={"targets": ["example.com"], "report_lang": "tr"})
        job_id = resp.json()["job_id"]
        _wait_for_job(client, job_id)

    r_json = client.get(f"/v1/scans/{job_id}/report.json")
    assert r_json.status_code == 200
    payload = r_json.json()
    assert payload["targets"] == ["example.com"]

    r_html = client.get(f"/v1/scans/{job_id}/report.html")
    assert r_html.status_code == 200
    assert '<html lang="tr">' in r_html.text  # report_lang was honored

    r_zip = client.get(f"/v1/scans/{job_id}/download")
    assert r_zip.status_code == 200
    assert r_zip.headers["content-type"] == "application/zip"
    assert len(r_zip.content) > 0


def test_job_log_endpoint_returns_pushed_log_lines(tmp_path):
    client = _client(tmp_path)

    def fake_run_scan(cfg, log=None):
        log("discovering ...")
        log("done")
        return analyze([], targets=cfg.targets)

    with patch("metascout.api.app.run_scan", side_effect=fake_run_scan):
        resp = client.post("/v1/scans", json={"targets": ["example.com"]})
        job_id = resp.json()["job_id"]
        _wait_for_job(client, job_id)

    r = client.get(f"/v1/scans/{job_id}/log")
    assert r.status_code == 200
    assert "discovering ..." in r.json()["lines"]
    assert "done" in r.json()["lines"]


def test_list_jobs_returns_newest_first(tmp_path):
    client = _client(tmp_path)
    with patch("metascout.api.app.run_scan", return_value=analyze([], targets=["a.com"])):
        r1 = client.post("/v1/scans", json={"targets": ["a.com"]})
        _wait_for_job(client, r1.json()["job_id"])
        r2 = client.post("/v1/scans", json={"targets": ["b.com"]})
        _wait_for_job(client, r2.json()["job_id"])

    jobs = client.get("/v1/scans").json()
    assert len(jobs) == 2
    assert jobs[0]["job_id"] == r2.json()["job_id"]  # newest first
    assert jobs[1]["job_id"] == r1.json()["job_id"]


def test_local_scan_requires_exactly_one_source(tmp_path):
    client = _client(tmp_path)
    assert client.post("/v1/local-scans", json={}).status_code == 422
    assert client.post("/v1/local-scans", json={"directory": "/tmp", "urls": ["https://example.com/a.pdf"]}).status_code == 422


def test_local_scan_directory_mode_calls_run_local_document_scan(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    client = _client(tmp_path / "out")

    captured = {}

    def fake_run_local(directory, *, filetypes, scan_content, content_categories, visual_signature, critical_files, critical_file_types, log=None):
        captured["directory"] = directory
        captured["critical_files"] = critical_files
        return analyze([], targets=[directory])

    with patch("metascout.api.app.run_local_document_scan", side_effect=fake_run_local):
        resp = client.post("/v1/local-scans", json={"directory": str(docs_dir), "critical_files": True})
        assert resp.status_code == 202
        _wait_for_job(client, resp.json()["job_id"])

    assert captured["directory"] == str(docs_dir)
    assert captured["critical_files"] is True


def test_local_scan_rejects_nonexistent_directory(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/v1/local-scans", json={"directory": "/no/such/directory/anywhere"})
    assert resp.status_code == 422


def test_local_scan_url_mode_calls_run_scan_with_no_discovery(tmp_path):
    client = _client(tmp_path)
    captured = {}

    def fake_run_scan(cfg, log=None):
        captured["targets"] = cfg.targets
        captured["engines"] = cfg.engines
        return analyze([], targets=cfg.targets)

    with patch("metascout.api.app.run_scan", side_effect=fake_run_scan):
        resp = client.post("/v1/local-scans", json={"urls": ["https://example.com/a.pdf", "https://example.com/b.pdf"]})
        _wait_for_job(client, resp.json()["job_id"])

    assert captured["engines"] == []
    assert captured["targets"] == ["example.com"]


def test_critical_files_and_content_categories_wired_through_scan_request(tmp_path):
    client = _client(tmp_path)
    captured = {}

    def fake_run_scan(cfg, log=None):
        captured["critical_files"] = cfg.critical_files
        captured["critical_file_types"] = cfg.critical_file_types
        captured["content_categories"] = cfg.content_categories
        return analyze([], targets=cfg.targets)

    with patch("metascout.api.app.run_scan", side_effect=fake_run_scan):
        resp = client.post("/v1/scans", json={
            "targets": ["example.com"],
            "scan_content": True, "content_categories": ["secrets", "infra"],
            "critical_files": True, "critical_file_types": ["env", "log"],
        })
        _wait_for_job(client, resp.json()["job_id"])

    assert captured["critical_files"] is True
    assert captured["critical_file_types"] == ["env", "log"]
    assert captured["content_categories"] == ["secrets", "infra"]


def test_engines_default_to_default_engines_when_omitted(tmp_path):
    client = _client(tmp_path)
    captured = {}

    def fake_run_scan(cfg, log=None):
        captured["engines"] = cfg.engines
        return analyze([], targets=cfg.targets)

    with patch("metascout.api.app.run_scan", side_effect=fake_run_scan), \
         patch.dict("os.environ", {}, clear=False):
        resp = client.post("/v1/scans", json={"targets": ["example.com"]})
        _wait_for_job(client, resp.json()["job_id"])

    assert captured["engines"] == ["crawl", "sitemap", "wayback", "ddgs"]


def test_engines_explicit_list_overrides_default(tmp_path):
    client = _client(tmp_path)
    captured = {}

    def fake_run_scan(cfg, log=None):
        captured["engines"] = cfg.engines
        return analyze([], targets=cfg.targets)

    with patch("metascout.api.app.run_scan", side_effect=fake_run_scan):
        resp = client.post("/v1/scans", json={"targets": ["example.com"], "engines": ["crawl"]})
        _wait_for_job(client, resp.json()["job_id"])

    assert captured["engines"] == ["crawl"]


def test_summary_reflects_critical_files_and_content_findings(tmp_path):
    client = _client(tmp_path)
    findings = analyze([], targets=["example.com"])
    findings.critical_files = [CriticalFile(url="https://example.com/.env", filetype="env", source=DiscoverySource.CRAWL)]
    findings.content_findings = [ContentFinding(document_url="https://example.com/.env", category="secret:AWS Access Key ID", masked_value="AKIA****")]

    with patch("metascout.api.app.run_scan", return_value=findings):
        resp = client.post("/v1/scans", json={"targets": ["example.com"]})
        final = _wait_for_job(client, resp.json()["job_id"])

    assert final["summary"]["critical_files"] == 1
    assert final["summary"]["content_findings"] == 1


def test_job_queue_cap_returns_429_once_max_pending_reached(tmp_path):
    # No built-in auth on this service — max_pending bounds how many jobs an
    # unauthenticated caller can pile up in memory in a submit loop.
    app = create_app(output_dir=str(tmp_path), max_workers=1, max_pending=2)
    client = TestClient(app)

    started = threading.Event()
    release = threading.Event()

    def slow_run_scan(cfg, log=None):
        started.set()
        release.wait(timeout=5)
        return analyze([], targets=cfg.targets)

    with patch("metascout.api.app.run_scan", side_effect=slow_run_scan):
        r1 = client.post("/v1/scans", json={"targets": ["a.com"]})
        started.wait(timeout=2)  # r1 now occupies the single worker (status=running)
        r2 = client.post("/v1/scans", json={"targets": ["b.com"]})  # queued: pending count now 2
        r3 = client.post("/v1/scans", json={"targets": ["c.com"]})  # pending already at the cap

        assert r1.status_code == 202
        assert r2.status_code == 202
        assert r3.status_code == 429
        assert "max-pending" in r3.json()["detail"] or "limit" in r3.json()["detail"]

        release.set()
        _wait_for_job(client, r1.json()["job_id"])
        _wait_for_job(client, r2.json()["job_id"])
