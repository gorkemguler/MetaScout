from __future__ import annotations

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:  # optional dependency, see pyproject.toml [content-scan]
    PdfReader = None  # type: ignore[assignment]
    PYPDF_AVAILABLE = False


def has_pdf_digital_signature(local_path: str) -> bool:
    """True if the PDF has an actual cryptographic signature field (AcroForm
    /Sig), not just the word "signature" somewhere in the text. Checked
    separately from the text-keyword scan because it also catches a
    scanned/image-only PDF with no extractable text at all.
    """
    if not PYPDF_AVAILABLE:
        return False
    try:
        reader = PdfReader(local_path)
        fields = reader.get_fields() or {}
        for f in fields.values():
            ft = f.get("/FT") if hasattr(f, "get") else None
            if ft == "/Sig":
                return True
        root = reader.trailer.get("/Root", {})
        acroform = root.get("/AcroForm") if hasattr(root, "get") else None
        if acroform is not None:
            sig_flags = acroform.get("/SigFlags") if hasattr(acroform, "get") else None
            if sig_flags:
                return True
    except Exception:
        return False
    return False
