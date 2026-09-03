from __future__ import annotations

# Finding-bucket categories present in report.json's "findings" object —
# see report/json_report.py. Kept as an explicit list (rather than just
# diffing whatever keys happen to be present) so a report from an older
# MetaScout version missing a newer category (e.g. "geolocation") still
# diffs cleanly against one that has it, instead of the extra key just
# being silently ignored.
FINDING_CATEGORIES = [
    "usernames", "emails", "software", "operating_systems",
    "internal_paths", "servers_and_printers", "geolocation",
]


def _diff_bucket(a: dict, b: dict) -> dict[str, list[str]]:
    """a, b are {value: {...}} dicts (one finding bucket from report.json).
    Returns the values only in b ("new") and only in a ("removed"), sorted.
    """
    a_keys, b_keys = set(a or {}), set(b or {})
    return {"new": sorted(b_keys - a_keys), "removed": sorted(a_keys - b_keys)}


def _content_finding_key(f: dict) -> tuple:
    # masked_value alone (not context, which can shift slightly run to run
    # for the same underlying hit due to surrounding-text truncation) is
    # the stable identity of a content-scan hit, scoped to its category and
    # source document so the same masked value in two different documents
    # still counts as two distinct findings.
    return (f.get("document_url"), f.get("category"), f.get("masked_value"))


def _diff_content_findings(a: list[dict], b: list[dict]) -> dict[str, list[dict]]:
    a_by_key = {_content_finding_key(f): f for f in (a or [])}
    b_by_key = {_content_finding_key(f): f for f in (b or [])}
    new_keys = set(b_by_key) - set(a_by_key)
    removed_keys = set(a_by_key) - set(b_by_key)
    return {
        "new": [b_by_key[k] for k in sorted(new_keys, key=str)],
        "removed": [a_by_key[k] for k in sorted(removed_keys, key=str)],
    }


def diff_reports(report_a: dict, report_b: dict) -> dict:
    """Compares two report.json payloads (parsed to dicts) and returns what
    changed between them: new/removed values per metadata finding category,
    new/removed discovered documents, and new/removed content-scan hits.

    `report_a` is treated as the earlier scan, `report_b` the later one —
    "new" means "in b but not a" throughout. Purely a data comparison, no
    filesystem/pipeline involvement, so it's the same function whether the
    two reports came from the CLI, the web UI, or a mix of both.
    """
    findings_a = report_a.get("findings", {})
    findings_b = report_b.get("findings", {})
    findings_diff = {
        cat: _diff_bucket(findings_a.get(cat, {}), findings_b.get(cat, {}))
        for cat in FINDING_CATEGORIES
    }

    docs_a = {d["url"] for d in report_a.get("documents", []) if d.get("url")}
    docs_b = {d["url"] for d in report_b.get("documents", []) if d.get("url")}
    documents_diff = {"new": sorted(docs_b - docs_a), "removed": sorted(docs_a - docs_b)}

    content_diff = _diff_content_findings(
        report_a.get("content_findings", []), report_b.get("content_findings", []),
    )

    return {"findings": findings_diff, "documents": documents_diff, "content_findings": content_diff}


def has_changes(diff: dict) -> bool:
    """True if diff_reports() found any difference at all — used to decide
    whether to show an "identical" callout instead of six empty sections."""
    if diff["documents"]["new"] or diff["documents"]["removed"]:
        return True
    if diff["content_findings"]["new"] or diff["content_findings"]["removed"]:
        return True
    return any(v["new"] or v["removed"] for v in diff["findings"].values())
