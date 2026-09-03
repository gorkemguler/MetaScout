from metascout.diff import diff_reports, has_changes


def _report(*, documents=None, findings=None, content_findings=None):
    return {
        "documents": documents or [],
        "findings": findings or {},
        "content_findings": content_findings or [],
    }


def test_diff_reports_identical_reports_have_no_changes():
    r = _report(
        documents=[{"url": "https://example.com/a.pdf"}],
        findings={"usernames": {"jdoe": {"document_urls": ["https://example.com/a.pdf"]}}},
    )
    d = diff_reports(r, r)
    assert has_changes(d) is False
    assert d["documents"]["new"] == []
    assert d["findings"]["usernames"]["new"] == []


def test_diff_reports_new_document():
    a = _report(documents=[{"url": "https://example.com/a.pdf"}])
    b = _report(documents=[{"url": "https://example.com/a.pdf"}, {"url": "https://example.com/b.pdf"}])
    d = diff_reports(a, b)
    assert d["documents"]["new"] == ["https://example.com/b.pdf"]
    assert d["documents"]["removed"] == []
    assert has_changes(d) is True


def test_diff_reports_removed_document():
    a = _report(documents=[{"url": "https://example.com/a.pdf"}, {"url": "https://example.com/gone.pdf"}])
    b = _report(documents=[{"url": "https://example.com/a.pdf"}])
    d = diff_reports(a, b)
    assert d["documents"]["removed"] == ["https://example.com/gone.pdf"]
    assert d["documents"]["new"] == []


def test_diff_reports_finding_category_new_and_removed():
    a = _report(findings={"emails": {"old@example.com": {}, "shared@example.com": {}}})
    b = _report(findings={"emails": {"new@example.com": {}, "shared@example.com": {}}})
    d = diff_reports(a, b)
    assert d["findings"]["emails"]["new"] == ["new@example.com"]
    assert d["findings"]["emails"]["removed"] == ["old@example.com"]


def test_diff_reports_handles_missing_category_gracefully():
    # An older report.json might not have "geolocation" at all (added
    # later) — must not raise, and must be treated the same as "empty".
    a = _report(findings={"usernames": {}})
    b = _report(findings={"usernames": {}, "geolocation": {"41.0, 29.0": {}}})
    d = diff_reports(a, b)
    assert d["findings"]["geolocation"]["new"] == ["41.0, 29.0"]


def test_diff_reports_content_findings_scoped_by_document_and_category():
    # The same masked value in two different documents (or under two
    # different categories) must count as two distinct findings, not
    # collapse into one.
    a = _report(content_findings=[
        {"document_url": "https://example.com/a.pdf", "category": "email", "masked_value": "x@example.com"},
    ])
    b = _report(content_findings=[
        {"document_url": "https://example.com/a.pdf", "category": "email", "masked_value": "x@example.com"},
        {"document_url": "https://example.com/b.pdf", "category": "email", "masked_value": "x@example.com"},
    ])
    d = diff_reports(a, b)
    assert len(d["content_findings"]["new"]) == 1
    assert d["content_findings"]["new"][0]["document_url"] == "https://example.com/b.pdf"
    assert d["content_findings"]["removed"] == []


def test_diff_reports_content_findings_removed():
    a = _report(content_findings=[
        {"document_url": "https://example.com/a.pdf", "category": "secret:AWS Access Key ID", "masked_value": "AKIA****"},
    ])
    b = _report(content_findings=[])
    d = diff_reports(a, b)
    assert len(d["content_findings"]["removed"]) == 1
    assert d["content_findings"]["new"] == []


def test_has_changes_false_for_empty_reports():
    assert has_changes(diff_reports(_report(), _report())) is False
