from __future__ import annotations

import re
from urllib.parse import urlparse

from ..models import DocumentMetadata, Finding, ScanFindings

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n]*")
UNC_PATH_RE = re.compile(r"\\\\[A-Za-z0-9_.-]+\\[^\\/:*?\"<>|\r\n]+(?:\\[^\\/:*?\"<>|\r\n]+)*")
USER_HOME_RE = re.compile(r"(?:C:\\Users\\|/Users/|/home/)([^\\/]+)", re.IGNORECASE)
OS_HINT_RE = re.compile(r"(Windows(?: NT)?[\w. ]*|Mac ?OS[\w. ]*|Macintosh|Linux[\w. ]*|Android[\w. ]*|iOS[\w. ]*)", re.IGNORECASE)
DUPLICATE_SUFFIX_RE = re.compile(r"\s*\(\d+\)$")

USERNAME_FIELDS = {"author", "creator", "lastmodifiedby", "lastauthor", "ownername", "owner"}
SOFTWARE_FIELDS = {"producer", "creatortool", "software", "application", "programname", "generator", "xcreatortool"}
PRINTER_HINT = "printer"
# exiftool's own composite tag combines lat+lon+direction into one clean
# string (e.g. "41.015137 N, 28.979530 E", given -c "%.6f" in the wrapper)
# whenever GPS EXIF data exists on an embedded photo — a phone photo pasted
# into a Word doc is the classic real-world source of this.
GPS_POSITION_FIELD = "gpsposition"

GENERIC_VALUES = {"", "unknown", "administrator", "user", "n/a", "-", "none", "guest", "root"}


def _add(bucket: dict[str, Finding], value: str, doc_url: str, field_name: str = "") -> None:
    value = value.strip()
    if not value:
        return
    entry = bucket.get(value)
    if entry is None:
        entry = Finding(value=value, field_name=field_name)
        bucket[value] = entry
    if doc_url not in entry.document_urls:
        entry.document_urls.append(doc_url)


def _base_host(target: str) -> str:
    host = target.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    return host.lower()


def _target_for_url(url: str, targets: list[str]) -> str | None:
    host = urlparse(url).netloc.split("@")[-1].split(":", 1)[0].lower()
    if not host:
        return None
    for target in targets:
        base = _base_host(target)
        if host == base or host.endswith(f".{base}"):
            return target
    return None


def analyze(documents: list[DocumentMetadata], targets: list[str]) -> ScanFindings:
    findings = ScanFindings(targets=targets)
    findings.documents = documents
    findings.documents_by_target = {t: 0 for t in targets}
    for doc in documents:
        if doc.error:
            continue
        matched = _target_for_url(doc.url, targets)
        if matched:
            findings.documents_by_target[matched] += 1

    for doc in documents:
        if doc.error:
            findings.errors.append(f"{doc.url}: {doc.error}")
        if not doc.raw:
            continue

        for tag_key, value in doc.raw.items():
            if not isinstance(value, str) or not value.strip():
                continue

            _, _, tag_name = tag_key.partition(":")
            tag_name_clean = DUPLICATE_SUFFIX_RE.sub("", tag_name).lower()

            for m in EMAIL_RE.findall(value):
                _add(findings.emails, m.lower(), doc.url, tag_name)

            for m in UNC_PATH_RE.findall(value):
                _add(findings.servers_and_printers, m, doc.url, tag_name)
                _add(findings.internal_paths, m, doc.url, tag_name)

            for m in WINDOWS_PATH_RE.findall(value):
                _add(findings.internal_paths, m, doc.url, tag_name)

            user_match = USER_HOME_RE.search(value)
            if user_match:
                candidate = user_match.group(1).strip()
                if candidate.lower() not in GENERIC_VALUES:
                    _add(findings.usernames, candidate, doc.url, "home directory")

            os_match = OS_HINT_RE.search(value)
            if os_match:
                _add(findings.operating_systems, os_match.group(1).strip(), doc.url, tag_name)

            if tag_name_clean in USERNAME_FIELDS and value.strip().lower() not in GENERIC_VALUES:
                _add(findings.usernames, value.strip(), doc.url, tag_name)

            if tag_name_clean in SOFTWARE_FIELDS and value.strip().lower() not in GENERIC_VALUES:
                _add(findings.software, value.strip(), doc.url, tag_name)

            if PRINTER_HINT in tag_name_clean:
                _add(findings.servers_and_printers, value.strip(), doc.url, tag_name)

            if tag_name_clean == GPS_POSITION_FIELD:
                _add(findings.geolocation, value.strip(), doc.url, tag_name)

    return findings
