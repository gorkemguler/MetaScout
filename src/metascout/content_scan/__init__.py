from __future__ import annotations

from . import pii_patterns as pii
from .signature import PYPDF_AVAILABLE, has_pdf_digital_signature
from .text_extract import extract_text
from .visual_signature import SIGNATURE_DETECT_AVAILABLE, detect_visual_signature
from ..models import ContentFinding

PHONENUMBERS_AVAILABLE = pii.PHONENUMBERS_AVAILABLE

# Toggle groups exposed to the CLI/web UI (--content-categories). Each maps
# to one or more of the fine-grained pii_patterns detectors; ContentFinding
# itself always carries the fine-grained category (email/phone/tc_kimlik/...)
# regardless of which group turned it on, so the report can group precisely.
ALL_CATEGORIES = ["tc_kimlik", "email_phone", "iban_card", "address_dob", "signature", "secrets"]

_CONTEXT_RADIUS = 30


def missing_dependencies(categories: set[str], *, visual_signature: bool = False) -> list[str]:
    """Optional dependencies not installed that would improve coverage for
    the requested categories — used to log one clear warning instead of
    silently under-reporting."""
    missing = []
    if not PYPDF_AVAILABLE:
        missing.append("pypdf (PDF text extraction + PDF digital-signature check)")
    if "email_phone" in categories and not PHONENUMBERS_AVAILABLE:
        missing.append("phonenumbers (phone number detection)")
    if visual_signature and not SIGNATURE_DETECT_AVAILABLE:
        missing.append(
            "signature-detect (visual signature detection — also needs ImageMagick "
            "and Ghostscript installed system-wide, not just the pip package)"
        )
    return missing


def _context(text: str, start: int, end: int, masked: str) -> str:
    lo = max(0, start - _CONTEXT_RADIUS)
    hi = min(len(text), end + _CONTEXT_RADIUS)
    before = text[lo:start].replace("\n", " ").strip()
    after = text[end:hi].replace("\n", " ").strip()
    snippet = f"…{before} [{masked}] {after}…"
    return " ".join(snippet.split())


def scan_document(local_path: str, filetype: str, *, categories: set[str]) -> list[ContentFinding]:
    """Best-effort scan of one downloaded document's body text for personal
    data (PII) and signature hints. Opt-in (see ScanConfig.scan_content) and
    heuristic by nature — every hit here needs a human to verify it, not a
    confirmed leak the way a metadata-tag finding is.

    `document_url` on the returned findings is left blank; the caller (see
    pipeline.py) fills it in, since this function only knows the local file.
    """
    findings: list[ContentFinding] = []
    text = extract_text(local_path, filetype)

    if not text:
        # No extractable text (missing dependency, scanned/image-only PDF,
        # unsupported legacy format, ...) — a PDF can still be structurally
        # signed even with no extractable text, so that check runs anyway.
        if "signature" in categories and filetype.lower() == "pdf" and has_pdf_digital_signature(local_path):
            findings.append(ContentFinding(
                document_url="", category="signature",
                masked_value="digitally signed (PDF /Sig field)", context="",
            ))
        return findings

    matches: list[pii.RawMatch] = []
    if "tc_kimlik" in categories:
        matches += pii.find_tc_kimlik(text)
    if "email_phone" in categories:
        matches += pii.find_emails(text)
        matches += pii.find_phones(text)
    if "iban_card" in categories:
        matches += pii.find_ibans(text)
        matches += pii.find_credit_cards(text)
    if "address_dob" in categories:
        matches += pii.find_dob_hints(text)
        matches += pii.find_address_hints(text)
    if "secrets" in categories:
        matches += pii.find_secrets(text)

    for m in matches:
        findings.append(ContentFinding(
            document_url="", category=m.category, masked_value=m.masked,
            context=_context(text, m.start, m.end, m.masked),
        ))

    if "signature" in categories:
        for m in pii.find_signature_keywords(text):
            findings.append(ContentFinding(
                document_url="", category="signature",
                masked_value=f'keyword: "{m.masked}"',
                context=_context(text, m.start, m.end, m.masked),
            ))
        if filetype.lower() == "pdf" and has_pdf_digital_signature(local_path):
            findings.append(ContentFinding(
                document_url="", category="signature",
                masked_value="digitally signed (PDF /Sig field)", context="",
            ))

    return findings


__all__ = [
    "scan_document", "missing_dependencies", "ALL_CATEGORIES",
    "PYPDF_AVAILABLE", "PHONENUMBERS_AVAILABLE",
    "SIGNATURE_DETECT_AVAILABLE", "detect_visual_signature",
]
