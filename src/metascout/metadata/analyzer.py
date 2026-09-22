from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urlparse

from ..content_scan.pii_patterns import find_internal_hosts
from ..models import DocumentMetadata, Finding, ScanFindings
from .exiftool_wrapper import split_tag_key

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Drive-letter paths with either separator ("C:\\Users\\…" or the "C:/Users/…"
# form found in file:/// URIs); the lookbehind keeps "https://" from matching.
WINDOWS_PATH_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?:[^\\/:*?\"<>|\r\n]+[\\/])*[^\\/:*?\"<>|\r\n]*")
UNC_PATH_RE = re.compile(r"\\\\[A-Za-z0-9_.-]+\\[^\\/:*?\"<>|\r\n]+(?:\\[^\\/:*?\"<>|\r\n]+)*")
# A POSIX path only counts when it starts a value/token (or follows "file://"),
# so the path part of a URL ("https://x.com/home/…") never matches.
_POSIX_START = r"(?:^|(?<=[\s\"'(<>\[=,;])|(?<=file://))"
# macOS/Linux absolute paths under well-known top-level dirs — e.g. the
# stRef:filePath of an InDesign/Illustrator PDF's xmpMM:Ingredients /
# xmpMM:Manifest entries, which record where every placed image lived on the
# designer's machine ("/Users/<account>/Desktop/<project>/<file>.tif").
# Segments may hold spaces, but ", " and ";" end the path when it's embedded
# in free text ("saved to /home/a/x.odt, then …").
POSIX_PATH_RE = re.compile(
    _POSIX_START
    + r"/(?:Users|home|Volumes|private|tmp|var|mnt|media|srv|opt|root|net|Network)"
    r"(?:/(?:[^/\x00\r\n\"<>|*?,;]|,(?!\s))+)+"
)
# mkstemp-style scratch files ("/var/tmp/wv93Ri.tif") that Adobe apps record
# in xmpMM:Manifest for every temporary rendition — dozens per PDF, random
# names, nothing about the target in them.
SCRATCH_FILE_RE = re.compile(r"/(?:private/)?var/tmp/[A-Za-z0-9]{6}(?:\.\w+)?")
USER_HOME_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]|"
    + _POSIX_START
    + r"/(?:Users|home)/)([^\\/:*?\"<>|\r\n]+)",
    re.IGNORECASE,
)
OS_HINT_RE = re.compile(r"(Windows(?: NT)?[\w. ]*|Mac ?OS[\w. ]*|Macintosh|Linux[\w. ]*|Android[\w. ]*|iOS[\w. ]*)", re.IGNORECASE)
DUPLICATE_SUFFIX_RE = re.compile(r"\s*\(\d+\)$")

# Fields naming a person/account. "for" is the PostScript %%For DSC comment —
# Illustrator/EPS files write the OS account name of whoever made the file
# into it; artist/by-line/captionwriter come from embedded photos, manager
# from Office docProps, initial-creator from ODF meta.xml.
USERNAME_FIELDS = {
    "author", "creator", "lastmodifiedby", "lastauthor", "ownername", "owner", "for",
    "artist", "by-line", "captionwriter", "contributor", "manager", "initial-creator",
}
# Groups whose "Creator" is the producing application (PDF Info /Creator,
# PostScript %%Creator), not a person like XMP-dc:Creator.
APP_CREATOR_GROUPS = {"PDF", "PostScript"}
SOFTWARE_FIELDS = {
    "producer", "creatortool", "software", "application", "programname", "generator", "xcreatortool",
    "historysoftwareagent",
}
# Fields holding a data-classification / sensitivity marking. Microsoft
# Purview (AIP) writes "MSIP_Label_<guid>_Name" custom properties, TITUS
# writes an XMP blob (see TITUS_PAIR_RE), and plenty of organizations just
# add a "Classification" document property of their own.
CLASSIFICATION_FIELDS = {
    "classification", "securityclassification", "dataclassification", "docclassification",
    "sensitivity", "sensitivitylabel", "confidentiality", "gizlilik", "gizlilikderecesi",
}
TITUS_GROUP = "XMP-tmi"
TITUS_PAIR_RE = re.compile(r"([A-Za-z][A-Za-z0-9_]*)(?:\[\d+\])?='([^']*)'")
# Labels that say a document was not meant to be public (TR + EN + NATO).
RESTRICTED_LABEL_RE = re.compile(
    r"confidential|restricted|secret|internal|private|classified|nato\s|"
    r"gizli|özel|hizmete|kişiye|tasnifli",
    re.IGNORECASE,
)
PRINTER_HINT = "printer"
# exiftool's own composite tag combines lat+lon+direction into one clean
# string (e.g. "41.015137 N, 28.979530 E", given -c "%.6f" in the wrapper)
# whenever GPS EXIF data exists on an embedded photo — a phone photo pasted
# into a Word doc is the classic real-world source of this.
GPS_POSITION_FIELD = "gpsposition"

# exiftool groups that describe the scanner's own downloaded copy, not the
# document — System:Directory is the local download dir, so scanning it would
# report the *scanning* machine's home dir/account as a finding.
LOCAL_COPY_GROUPS = {"System", "ExifTool"}

GENERIC_VALUES = {"", "unknown", "administrator", "user", "n/a", "-", "none", "guest", "root"}
# Built-in profile dirs ("/Users/Shared", "C:\\Users\\Public") — not a person.
GENERIC_HOME_DIRS = GENERIC_VALUES | {"shared", "public", "default", "default user", "all users"}


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


def _string_values(value) -> Iterator[str]:
    """Yield every non-empty string inside an exiftool JSON value.

    exiftool -j emits a multi-valued tag — an XMP bag/seq such as the
    xmpMM:Ingredients / xmpMM:Manifest file paths, several dc:creator
    authors, the PostScript %%For account — as a JSON list rather than a
    string (and nested dicts under -struct), so scanning only `str` values
    silently skipped all of them.
    """
    if isinstance(value, str):
        if value.strip():
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from _string_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _string_values(item)


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


def _field_kind(group: str, tag_name_clean: str) -> str | None:
    if tag_name_clean == "creator" and group in APP_CREATOR_GROUPS:
        return "software"
    if tag_name_clean in USERNAME_FIELDS:
        return "username"
    if tag_name_clean in SOFTWARE_FIELDS:
        return "software"
    if group == TITUS_GROUP:
        return "classification_blob"
    # "MSIP_Label_<guid>_Name" carries the human-readable label; the sibling
    # _SiteId/_Enabled/_SetDate properties are bookkeeping.
    if tag_name_clean in CLASSIFICATION_FIELDS or (
        tag_name_clean.startswith("msip_label") and tag_name_clean.endswith("_name")
    ):
        return "classification"
    return None


def _scan_value(
    findings: ScanFindings, value: str, doc_url: str, tag_name: str, tag_name_clean: str, kind: str | None,
) -> None:
    for m in EMAIL_RE.findall(value):
        _add(findings.emails, m.lower(), doc_url, tag_name)

    for m in UNC_PATH_RE.findall(value):
        _add(findings.servers_and_printers, m, doc_url, tag_name)
        _add(findings.internal_paths, m, doc_url, tag_name)

    for m in WINDOWS_PATH_RE.findall(value):
        _add(findings.internal_paths, m, doc_url, tag_name)

    for m in POSIX_PATH_RE.findall(value):
        path = m.rstrip(" \t.,;:")
        if not SCRATCH_FILE_RE.fullmatch(path):
            _add(findings.internal_paths, path, doc_url, tag_name)

    # Intranet hostnames / private IPs, e.g. an Office HyperlinkBase of
    # "http://intranet.corp.local/docs/" — same detector as the content scan.
    for m in find_internal_hosts(value):
        _add(findings.servers_and_printers, m.raw, doc_url, tag_name)

    for user_match in USER_HOME_RE.finditer(value):
        candidate = user_match.group(1).strip()
        if candidate.lower() not in GENERIC_HOME_DIRS:
            _add(findings.usernames, candidate, doc_url, "home directory")

    os_match = OS_HINT_RE.search(value)
    if os_match:
        _add(findings.operating_systems, os_match.group(1).strip(), doc_url, tag_name)

    if kind == "username" and value.strip().lower() not in GENERIC_VALUES:
        _add(findings.usernames, value.strip(), doc_url, tag_name)

    if kind == "software" and value.strip().lower() not in GENERIC_VALUES:
        _add(findings.software, value.strip(), doc_url, tag_name)

    if PRINTER_HINT in tag_name_clean:
        _add(findings.servers_and_printers, value.strip(), doc_url, tag_name)

    if tag_name_clean == GPS_POSITION_FIELD:
        _add(findings.geolocation, value.strip(), doc_url, tag_name)

    if kind == "classification" and value.strip().lower() not in GENERIC_VALUES:
        _add(findings.classification_labels, value.strip(), doc_url, tag_name)

    # A TITUS blob packs several markings into one value:
    # "... Ownership[0]='None (Public)' Classification='NATO RESTRICTED' ..."
    if kind == "classification_blob" or "titus.com/ns" in value:
        for key, label in TITUS_PAIR_RE.findall(value):
            if label.strip():
                _add(findings.classification_labels, f"{key}: {label.strip()}", doc_url, tag_name)


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

        for tag_key, raw_value in doc.raw.items():
            group, tag_name = split_tag_key(tag_key)
            if group in LOCAL_COPY_GROUPS:
                continue
            tag_name_clean = DUPLICATE_SUFFIX_RE.sub("", tag_name).lower()
            kind = _field_kind(group, tag_name_clean)
            for value in _string_values(raw_value):
                _scan_value(findings, value, doc.url, tag_name, tag_name_clean, kind)

    return findings
