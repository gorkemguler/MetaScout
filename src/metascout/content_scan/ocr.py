from __future__ import annotations

import io

try:
    from wand.image import Image as WandImage
    WAND_AVAILABLE = True
except ImportError:  # optional dependency, see pyproject.toml [ocr]
    WandImage = None  # type: ignore[assignment]
    WAND_AVAILABLE = False

try:
    import pytesseract
    from PIL import Image as PILImage
    PYTESSERACT_AVAILABLE = True
except ImportError:  # optional dependency, see pyproject.toml [ocr]
    pytesseract = None  # type: ignore[assignment]
    PILImage = None  # type: ignore[assignment]
    PYTESSERACT_AVAILABLE = False

OCR_AVAILABLE = WAND_AVAILABLE and PYTESSERACT_AVAILABLE

# A page whose pypdf-extracted text is shorter than this is treated as
# likely scanned/image-only and gets OCR'd instead. Real scanned pages
# extract to "" or a handful of stray characters (a stray watermark
# character, etc.); a genuinely tiny page of real text is rare enough that
# this threshold rarely misfires — confirmed live: a synthetic scanned page
# with three lines of real text (~90 chars) extracted to "" via pypdf, well
# under this threshold.
OCR_TEXT_THRESHOLD = 20


def ocr_pdf_page(local_path: str, page_number: int, *, resolution: int = 200) -> str:
    """Rasterizes one page of a PDF (0-indexed) via ImageMagick/Ghostscript
    (same technique as content_scan/visual_signature.py) and OCRs it with
    Tesseract. Returns "" on any failure — OCR is best-effort here, a
    single unreadable page shouldn't break extraction for the rest of the
    document.

    OCR text is inherently noisy (misread characters, dropped/added spaces
    — confirmed live: "jane.doe@example.com" came back as "jane.doe
    @example.com", enough to dodge the email regex) — treat OCR-sourced
    hits as lower-confidence than a real text layer's, and expect to miss
    some real matches, not just gain false ones.
    """
    if not OCR_AVAILABLE:
        return ""
    try:
        with WandImage(filename=f"{local_path}[{page_number}]", resolution=resolution) as wand_img:
            wand_img.format = "png"
            png_bytes = wand_img.make_blob()
        pil_img = PILImage.open(io.BytesIO(png_bytes))
        return pytesseract.image_to_string(pil_img)
    except Exception:
        return ""
