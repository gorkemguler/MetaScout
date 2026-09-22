import json

from metascout.metadata.analyzer import analyze
from metascout.models import DocumentMetadata
from metascout.report import render_json_report


def test_json_report_records_where_an_archived_copy_came_from():
    snapshot = "https://web.archive.org/web/20200101000000id_/https://example.com/removed.pdf"
    docs = [
        DocumentMetadata(url="https://example.com/live.pdf", local_path="/tmp/live.pdf", filetype="pdf",
                         raw={"PDF:Author": "jdoe"}),
        DocumentMetadata(url="https://example.com/removed.pdf", local_path="/tmp/removed.pdf", filetype="pdf",
                         raw={"PDF:Author": "asmith"}, archive_url=snapshot),
    ]

    payload = json.loads(render_json_report(analyze(docs, targets=["example.com"])))

    by_url = {d["url"]: d for d in payload["documents"]}
    assert by_url["https://example.com/removed.pdf"]["archive_url"] == snapshot
    assert by_url["https://example.com/live.pdf"]["archive_url"] is None
