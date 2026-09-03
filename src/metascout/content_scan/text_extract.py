from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile

from .ocr import OCR_AVAILABLE, OCR_TEXT_THRESHOLD, ocr_pdf_page

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:  # optional dependency, see pyproject.toml [content-scan]
    PdfReader = None  # type: ignore[assignment]
    PYPDF_AVAILABLE = False


def extract_text(local_path: str, filetype: str) -> str:
    """Best-effort plain-text extraction from a downloaded document, for
    content scanning. Returns "" for anything it can't handle — a missing
    optional dependency, a legacy binary Office format (.doc/.xls/.ppt),
    an encrypted/corrupt file, etc. — rather than raising, since content
    scanning is inherently best-effort and one unreadable file shouldn't
    abort the rest of the scan.
    """
    ft = filetype.lower().lstrip(".")
    try:
        if ft == "pdf":
            return _extract_pdf(local_path)
        if ft == "docx":
            return _zip_xml_text(local_path, ["word/document.xml"])
        if ft == "xlsx":
            return _extract_xlsx(local_path)
        if ft == "pptx":
            return _extract_pptx(local_path)
        if ft in ("odt", "ods", "odp"):
            return _zip_xml_text(local_path, ["content.xml"])
    except Exception:
        return ""
    # .doc/.xls/.ppt (legacy binary Office formats) and anything else:
    # not supported without extra heavyweight dependencies (e.g. olefile).
    return ""


def _extract_pdf(local_path: str) -> str:
    if not PYPDF_AVAILABLE:
        return ""
    reader = PdfReader(local_path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return ""
    parts = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        # A short/empty extraction usually means a scanned, image-only page
        # (no text layer at all) rather than a genuinely near-blank one —
        # confirmed live: a real 3-line scanned page extracted to "" via
        # pypdf. OCR it as a fallback, but only if the optional [ocr] extra
        # (+ Tesseract/ImageMagick/Ghostscript installed system-wide) is
        # actually available; otherwise this page just contributes nothing,
        # same as before OCR support existed.
        if len(text.strip()) < OCR_TEXT_THRESHOLD and OCR_AVAILABLE:
            text = (text + "\n" + ocr_pdf_page(local_path, i)).strip()
        parts.append(text)
    return "\n".join(parts)


def _zip_xml_text(local_path: str, members: list[str]) -> str:
    parts: list[str] = []
    with zipfile.ZipFile(local_path) as zf:
        names = set(zf.namelist())
        for member in members:
            if member not in names:
                continue
            try:
                root = ET.fromstring(zf.read(member))
            except ET.ParseError:
                continue
            parts.extend(t for t in root.itertext() if t and t.strip())
    return " ".join(parts)


def _extract_xlsx(local_path: str) -> str:
    with zipfile.ZipFile(local_path) as zf:
        members = [
            n for n in zf.namelist()
            if n == "xl/sharedStrings.xml" or (n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
        ]
    return _zip_xml_text(local_path, members)


def _extract_pptx(local_path: str) -> str:
    with zipfile.ZipFile(local_path) as zf:
        members = sorted(n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
    return _zip_xml_text(local_path, members)
