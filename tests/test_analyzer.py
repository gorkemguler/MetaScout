from metascout.metadata.analyzer import analyze
from metascout.models import DocumentMetadata


def test_analyze_extracts_username_email_software_and_paths():
    doc = DocumentMetadata(
        url="https://example.com/report.pdf",
        local_path="/tmp/report.pdf",
        filetype="pdf",
        raw={
            "PDF:Author": "jdoe",
            "PDF:Producer": "Microsoft Word: Windows PDF Library",
            "XMP-dc:Creator": "jdoe",
            "PDF:Company": "Acme Corp",
            "PDF:Comments": "contact jdoe@example.com or see C:\\Users\\jdoe\\Documents\\report.docx",
            "File:FileSize": 12345,
        },
    )

    findings = analyze([doc], targets=["example.com"])

    assert "jdoe" in findings.usernames
    assert "jdoe@example.com" in findings.emails
    assert any("Windows PDF Library" in s for s in findings.software)
    assert any(p.startswith("C:\\Users\\jdoe") for p in findings.internal_paths)
    assert "Windows" in "".join(findings.operating_systems.keys())


def test_analyze_records_document_errors():
    doc = DocumentMetadata(url="https://example.com/x.pdf", local_path="", filetype="pdf", error="404 not found")
    findings = analyze([doc], targets=["example.com"])
    assert findings.errors == ["https://example.com/x.pdf: 404 not found"]
    assert findings.usernames == {}


def test_analyze_counts_documents_per_target():
    docs = [
        DocumentMetadata(url="https://a.example.com/one.pdf", local_path="/tmp/one.pdf", filetype="pdf", raw={}),
        DocumentMetadata(url="https://example.org/two.pdf", local_path="/tmp/two.pdf", filetype="pdf", raw={}),
        DocumentMetadata(url="https://example.org/three.pdf", local_path="/tmp/three.pdf", filetype="pdf", raw={}),
        DocumentMetadata(url="https://unrelated.net/four.pdf", local_path="", filetype="pdf", error="timeout"),
    ]

    findings = analyze(docs, targets=["example.com", "example.org"])

    assert findings.documents_by_target == {"example.com": 1, "example.org": 2}
