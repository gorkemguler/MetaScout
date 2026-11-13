import asyncio
import json
import sys
import threading
from unittest.mock import patch

import pytest

pytest.importorskip("mcp.server.mcpserver", reason="needs the [mcp] extra")

from mcp import Client, StdioServerParameters  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from metascout.mcp_server import (  # noqa: E402
    build_server, document_detail, documents_page, findings_overview, findings_page, scans_diff, summarize,
)
from metascout.metadata.analyzer import analyze  # noqa: E402
from metascout.models import DocumentMetadata  # noqa: E402

A, B, OLD, GONE = ("https://example.com/a.pdf", "https://example.com/b.pdf", "http://example.com/old.doc",
                   "https://example.com/gone.pdf")


def _doc(url, **over):
    return {"url": url, "filetype": url.rsplit(".", 1)[-1], "local_path": "", "error": None, "archive_url": None,
            "metadata_stripped": False, "metadata": {}, **over}


def _payload():
    return {
        "targets": ["example.com"], "scanned_at": "2026-01-15T09:30:00+00:00",
        "documents_discovered": 4, "documents_with_metadata": 3,
        "documents": [
            _doc(A, metadata={"PDF:Author": "jdoe", "PDF:Producer": "Word 16", "XMP:History": [{"action": "saved"}]}),
            _doc(B, metadata_stripped=True, metadata={"PDF-previous:PDF:Author": "asmith"}),
            _doc(OLD, archive_url="https://web.archive.org/web/2012id_/http://example.com/old.doc"),
            _doc(GONE, error="404"),
        ],
        "findings": {
            "usernames": {"asmith": {"document_urls": [B], "field_name": "Author"},
                          "jdoe": {"document_urls": [A, B, OLD], "field_name": "Author"}},
            "software": {"Word 16": {"document_urls": [A], "field_name": "Producer"}},
            "internal_paths": {"/Volumes/FS01/Dept/plan.indd": {"document_urls": [OLD], "field_name": "FilePath"}},
        },
        "content_findings": [{"document_url": A, "category": "email", "masked_value": "j***@example.com",
                              "context": "contact j***@example.com for"}],
        "critical_files": [{"url": "https://example.com/.env", "filetype": "env", "source": "crawl",
                            "size_bytes": 120, "error": None},
                           {"url": "https://example.com/dump.sql", "filetype": "sql", "source": "wayback",
                            "size_bytes": 0, "error": "404"}],
        "errors": [],
    }


# --- shaping a report for a model: counts, pages, clipped values ---

def test_summary_counts_what_a_scan_found():
    s = summarize(_payload())

    assert s["documents"] == {"discovered": 4, "analysed": 3, "failed": 1, "from_web_archive": 1, "metadata_stripped": 1}
    assert s["findings"]["usernames"] == 2 and s["findings"]["emails"] == 0
    assert s["content_findings"] == {"email": 1}
    assert s["critical_files"] == 1  # the one that could not be fetched is not an exposure


def test_findings_come_most_widespread_first_and_in_pages():
    first = findings_page(_payload(), "usernames", limit=1)

    assert first["total"] == 2 and first["next_offset"] == 1
    assert first["items"] == [{"value": "jdoe", "field": "Author", "documents": 3, "example_urls": [A, B, OLD]}]
    second = findings_page(_payload(), "usernames", limit=1, offset=1)
    assert second["items"][0]["value"] == "asmith" and second["next_offset"] is None


def test_findings_can_be_searched():
    hits = findings_page(_payload(), "usernames", search="SMITH")
    assert [i["value"] for i in hits["items"]] == ["asmith"]
    assert findings_page(_payload(), "critical_files", search=".env")["total"] == 1


def test_unknown_category_names_the_valid_ones():
    with pytest.raises(ToolError, match="internal_paths"):
        findings_page(_payload(), "passwords")


def test_overview_lists_only_categories_with_findings():
    overview = findings_overview(_payload())

    assert set(overview["top_values"]) == {"usernames", "software", "internal_paths", "content_findings", "critical_files"}
    assert overview["summary"]["targets"] == ["example.com"]


def test_a_long_value_is_clipped_not_dumped():
    payload = _payload()
    payload["findings"]["internal_paths"] = {"/srv/" + "x" * 5000: {"document_urls": [A], "field_name": "FilePath"}}

    [item] = findings_page(payload, "internal_paths")["items"]

    assert len(item["value"]) < 400 and "more characters" in item["value"]


def test_document_detail_ties_findings_to_the_tags_behind_them():
    detail = document_detail(_payload(), A)

    assert detail["findings"] == {"usernames": ["jdoe"], "software": ["Word 16"]}
    assert detail["metadata"]["PDF:Author"] == "jdoe"
    assert detail["metadata"]["XMP:History"] == '[{"action": "saved"}]'  # nested tags arrive as text
    assert detail["content_findings"][0]["value"] == "j***@example.com"
    assert document_detail(_payload(), B)["metadata_stripped"] is True


def test_document_can_be_named_by_a_unique_ending():
    assert document_detail(_payload(), "old.doc")["url"] == OLD
    with pytest.raises(ToolError, match="matches 3 documents"):
        document_detail(_payload(), ".pdf")
    with pytest.raises(ToolError, match="No document"):
        document_detail(_payload(), "https://example.com/missing.pdf")


def test_document_with_hundreds_of_tags_is_capped():
    payload = _payload()
    payload["documents"][0]["metadata"] = {f"XMP:Tag{n:03d}": n for n in range(400)}

    detail = document_detail(payload, A)

    assert len(detail["metadata"]) == 150 and "250 more tags" in detail["metadata_note"]


def test_documents_can_be_filtered_by_what_happened_to_them():
    assert documents_page(_payload())["total"] == 4
    assert [d["url"] for d in documents_page(_payload(), only="failed")["items"]] == [GONE]
    assert [d["url"] for d in documents_page(_payload(), only="from_web_archive")["items"]] == [OLD]
    assert [d["url"] for d in documents_page(_payload(), only="metadata_stripped")["items"]] == [B]
    with pytest.raises(ToolError):
        documents_page(_payload(), only="deleted")


def test_diff_keeps_counts_when_lists_are_cut():
    later = _payload()
    later["findings"]["usernames"] = {f"user{n:02d}": {"document_urls": [A], "field_name": "Author"} for n in range(30)}

    diff = scans_diff(_payload(), later, limit=5)

    names = diff["findings"]["usernames"]
    assert names["new_count"] == 30 and len(names["new"]) == 5
    assert names["removed"] == ["asmith", "jdoe"]
    assert "software" not in diff["findings"]  # unchanged categories are left out


# --- the server, through a real MCP client ---

def _session(server, calls):
    """Runs `calls(client)` inside one client session and returns its result."""
    async def go():
        async with Client(server) as client:
            return await calls(client)
    return asyncio.run(go())


async def _tool(client, name, **arguments):
    result = await client.call_tool(name, arguments)
    if result.is_error:
        raise AssertionError(result.content[0].text)
    return result.structured_content


async def _tool_error(client, name, **arguments):
    result = await client.call_tool(name, arguments)
    assert result.is_error, result.structured_content
    return result.content[0].text


def _findings(cfg, log=None):
    log and log("downloading 1 document")
    doc = DocumentMetadata(url=A, local_path="/tmp/a.pdf", filetype="pdf", raw={"PDF:Author": "jdoe"})
    return analyze([doc], targets=cfg.targets)


def test_server_offers_the_scan_tools_but_no_local_file_access_by_default(tmp_path):
    async def calls(client):
        return {t.name for t in (await client.list_tools()).tools}

    assert _session(build_server(output_dir=str(tmp_path)), calls) == {
        "start_scan", "inspect_document", "scan_status", "list_scans", "get_findings", "list_documents",
        "get_document", "compare_scans",
    }
    with_dir = build_server(output_dir=str(tmp_path), allow_dirs=[str(tmp_path)])
    assert "scan_local_directory" in _session(with_dir, calls)


def test_a_scan_runs_in_the_background_and_its_findings_can_be_read(tmp_path):
    seen = {}

    def fake_scan(cfg, log=None):
        seen["cfg"] = cfg
        return _findings(cfg, log)

    async def calls(client):
        started = await _tool(client, "start_scan", targets=["example.com"], max_docs=5, subdomains=True)
        status = await _tool(client, "scan_status", run_id=started["run_id"], wait_seconds=10)
        overview = await _tool(client, "get_findings", run_id=started["run_id"])
        names = await _tool(client, "get_findings", run_id=started["run_id"], category="usernames")
        doc = await _tool(client, "get_document", run_id=started["run_id"], url="a.pdf")
        listed = await _tool(client, "list_scans")
        return started, status, overview, names, doc, listed

    with patch("metascout.mcp_server.run_scan", side_effect=fake_scan):
        started, status, overview, names, doc, listed = _session(build_server(output_dir=str(tmp_path)), calls)

    assert started["run_id"].startswith("mcp-") and started["status"] in ("queued", "running")
    assert seen["cfg"].max_docs == 5 and seen["cfg"].include_subdomains is True
    assert seen["cfg"].output_dir == str(tmp_path / started["run_id"])  # each run has its own directory
    assert status["status"] == "done" and status["log"] == ["downloading 1 document"]
    assert status["summary"]["findings"]["usernames"] == 1
    assert (tmp_path / started["run_id"] / "report.html").is_file() and status["files"]["report_html"].endswith("report.html")
    assert overview["top_values"]["usernames"][0]["value"] == "jdoe"
    assert names["items"][0]["example_urls"] == [A]
    assert doc["metadata"] == {"PDF:Author": "jdoe"}
    assert [s["run_id"] for s in listed["scans"]] == [started["run_id"]]


def test_runs_written_by_the_cli_or_web_ui_are_readable_too(tmp_path):
    for run_id in ("web-20260101-120000", "scan-20260102-120000"):
        (tmp_path / run_id).mkdir()
        (tmp_path / run_id / "report.json").write_text(json.dumps(_payload()), encoding="utf-8")
    (tmp_path / "not-a-run").mkdir()

    async def calls(client):
        return (await _tool(client, "list_scans"),
                await _tool(client, "scan_status", run_id="web-20260101-120000"),
                await _tool(client, "list_documents", run_id="web-20260101-120000", only="failed"),
                await _tool(client, "compare_scans", earlier="web-20260101-120000", later="scan-20260102-120000"))

    listed, status, failed, diff = _session(build_server(output_dir=str(tmp_path)), calls)

    assert {s["run_id"] for s in listed["scans"]} == {"web-20260101-120000", "scan-20260102-120000"}
    assert listed["scans"][0]["findings"] == 4 and listed["scans"][0]["documents"] == 4
    assert status["status"] == "done" and status["summary"]["documents"]["discovered"] == 4
    assert failed["items"] == [{"url": GONE, "filetype": "pdf", "error": "404"}]
    assert diff["documents"] == {"new_count": 0, "removed_count": 0, "new": [], "removed": []}


@pytest.mark.parametrize("run_id", ["../secrets", "/etc", "..", "a/b", ""])
def test_a_run_id_cannot_point_outside_the_output_directory(tmp_path, run_id):
    (tmp_path.parent / "secrets").mkdir(exist_ok=True)
    (tmp_path.parent / "secrets" / "report.json").write_text(json.dumps(_payload()), encoding="utf-8")

    async def calls(client):
        return await _tool_error(client, "get_findings", run_id=run_id)

    assert "not a run id" in _session(build_server(output_dir=str(tmp_path)), calls)


def test_findings_of_a_scan_still_running_say_to_wait(tmp_path):
    release = threading.Event()

    def slow_scan(cfg, log=None):
        release.wait(10)
        return _findings(cfg)

    async def calls(client):
        started = await _tool(client, "start_scan", targets=["example.com"])
        early = await _tool_error(client, "get_findings", run_id=started["run_id"])
        status = await _tool(client, "scan_status", run_id=started["run_id"])
        release.set()
        done = await _tool(client, "scan_status", run_id=started["run_id"], wait_seconds=10)
        return early, status, done

    with patch("metascout.mcp_server.run_scan", side_effect=slow_scan):
        early, status, done = _session(build_server(output_dir=str(tmp_path)), calls)

    assert "still" in early and "scan_status" in early
    assert status["status"] in ("queued", "running") and "hint" in status
    assert done["status"] == "done"


def test_a_failed_scan_reports_why(tmp_path):
    async def calls(client):
        started = await _tool(client, "start_scan", targets=["example.com"])
        status = await _tool(client, "scan_status", run_id=started["run_id"], wait_seconds=10)
        return status, await _tool_error(client, "get_findings", run_id=started["run_id"])

    with patch("metascout.mcp_server.run_scan", side_effect=RuntimeError("exiftool not found on PATH")):
        status, error = _session(build_server(output_dir=str(tmp_path)), calls)

    assert status["status"] == "error" and "exiftool" in status["error"]
    assert "exiftool" in error


def test_start_scan_needs_a_target_and_known_engines(tmp_path):
    async def calls(client):
        return (await _tool_error(client, "start_scan"),
                await _tool_error(client, "start_scan", targets=["example.com"], engines=["crawl", "shodan"]))

    no_target, bad_engine = _session(build_server(output_dir=str(tmp_path)), calls)

    assert "at least one target" in no_target
    assert "shodan" in bad_engine and "wayback" in bad_engine


def test_inspect_document_answers_in_one_call_without_discovery(tmp_path):
    seen = {}

    def fake_scan(cfg, log=None):
        seen["cfg"] = cfg
        return _findings(cfg)

    async def calls(client):
        return (await _tool(client, "inspect_document", url=A),
                await _tool_error(client, "inspect_document", url="a.pdf"))

    with patch("metascout.mcp_server.run_scan", side_effect=fake_scan):
        result, not_a_url = _session(build_server(output_dir=str(tmp_path)), calls)

    assert seen["cfg"].engines == [] and seen["cfg"].manual_urls == [A] and seen["cfg"].targets == ["example.com"]
    assert result["document"]["findings"] == {"usernames": ["jdoe"]}
    assert "not a full URL" in not_a_url


def test_inspect_document_reports_a_document_that_could_not_be_fetched(tmp_path):
    def fake_scan(cfg, log=None):
        return analyze([DocumentMetadata(url=A, local_path="", filetype="pdf", error="HTTP 404")], targets=cfg.targets)

    async def calls(client):
        return await _tool(client, "inspect_document", url=A)

    with patch("metascout.mcp_server.run_scan", side_effect=fake_scan):
        result = _session(build_server(output_dir=str(tmp_path)), calls)

    assert result["document"]["error"] == "HTTP 404" and result["document"]["findings"] == {}


def test_a_full_queue_is_refused_in_terms_the_assistant_can_act_on(tmp_path):
    from metascout.jobs import JobStore

    release = threading.Event()

    def slow_scan(cfg, log=None):
        release.wait(10)
        return _findings(cfg)

    async def calls(client):
        await _tool(client, "start_scan", targets=["example.com"])
        refused = await _tool_error(client, "start_scan", targets=["example.org"])
        release.set()
        return refused

    store = JobStore(output_dir=str(tmp_path), max_workers=1, max_pending=1, run_prefix="mcp")
    with patch("metascout.mcp_server.run_scan", side_effect=slow_scan):
        refused = _session(build_server(output_dir=str(tmp_path), store=store), calls)
    store.shutdown()

    assert "Too many scans" in refused and "scan_status" in refused


def test_local_scan_only_reads_allowed_directories(tmp_path):
    allowed = tmp_path / "to-publish"
    (allowed / "q3").mkdir(parents=True)
    outside = tmp_path / "private"
    outside.mkdir()
    (allowed / "escape").symlink_to(outside)
    seen = []

    def fake_local_scan(directory, **options):
        seen.append(directory)
        return analyze([], targets=[directory])

    async def calls(client):
        started = await _tool(client, "scan_local_directory", directory=str(allowed / "q3"))
        await _tool(client, "scan_status", run_id=started["run_id"], wait_seconds=10)
        return [await _tool_error(client, "scan_local_directory", directory=str(d))
                for d in (outside, allowed / "escape", tmp_path, allowed / ".." / "private")]

    server = build_server(output_dir=str(tmp_path / "out"), allow_dirs=[str(allowed)])
    with patch("metascout.mcp_server.run_local_document_scan", side_effect=fake_local_scan):
        refusals = _session(server, calls)

    assert seen == [str((allowed / "q3").resolve())]
    assert all("outside the allowed directories" in r for r in refusals)


def test_assessment_prompt_names_the_domain(tmp_path):
    async def calls(client):
        prompt = await client.get_prompt("assess_metadata_exposure", {"domain": "example.com"})
        return prompt.messages[0].content.text

    text = _session(build_server(output_dir=str(tmp_path)), calls)

    assert 'start_scan(targets=["example.com"]' in text


def test_the_command_speaks_mcp_over_stdio(tmp_path):
    """`metascout mcp` as a client launches it: a clean protocol stream on
    stdout, and the output directory it was given."""
    (tmp_path / "web-20260101-120000").mkdir()
    (tmp_path / "web-20260101-120000" / "report.json").write_text(json.dumps(_payload()), encoding="utf-8")
    command = StdioServerParameters(command=sys.executable,
                                    args=["-m", "metascout.cli", "mcp", "--output-dir", str(tmp_path)])

    async def go():
        async with Client(command) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            return tools, await _tool(client, "list_scans")

    tools, listed = asyncio.run(go())

    assert "start_scan" in tools and "scan_local_directory" not in tools
    assert listed["output_dir"] == str(tmp_path.resolve())
    assert [s["run_id"] for s in listed["scans"]] == ["web-20260101-120000"]
