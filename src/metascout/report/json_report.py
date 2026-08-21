from __future__ import annotations

import json

from ..models import Finding, ScanFindings


def _findings_dict(bucket: dict[str, Finding]) -> dict:
    return {
        value: {"document_urls": f.document_urls, "field_name": f.field_name}
        for value, f in sorted(bucket.items())
    }


def render_json_report(findings: ScanFindings) -> str:
    payload = {
        "targets": findings.targets,
        "scanned_at": findings.scanned_at.isoformat(),
        "documents_discovered": len(findings.documents),
        "documents_with_metadata": findings.documents_with_metadata,
        "documents_by_target": findings.documents_by_target,
        "documents": [
            {
                "url": d.url,
                "filetype": d.filetype,
                "error": d.error,
                "metadata": d.raw,
            }
            for d in findings.documents
        ],
        "findings": {
            "usernames": _findings_dict(findings.usernames),
            "emails": _findings_dict(findings.emails),
            "software": _findings_dict(findings.software),
            "operating_systems": _findings_dict(findings.operating_systems),
            "internal_paths": _findings_dict(findings.internal_paths),
            "servers_and_printers": _findings_dict(findings.servers_and_printers),
        },
        "errors": findings.errors,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
