from __future__ import annotations

import warnings

try:
    from signature_detect.cropper import Cropper
    from signature_detect.extractor import Extractor
    from signature_detect.judger import Judger
    from signature_detect.loader import Loader
    SIGNATURE_DETECT_AVAILABLE = True
except ImportError:  # optional dependency, see pyproject.toml [visual-signature]
    Cropper = Extractor = Judger = Loader = None  # type: ignore[assignment]
    SIGNATURE_DETECT_AVAILABLE = False

_SUPPORTED_FILETYPES = {"pdf", "jpg", "jpeg", "png", "tif", "tiff"}


def detect_visual_signature(local_path: str, filetype: str) -> bool | None:
    """Runs the `signature-detect` (EnzoSeason) heuristic image pipeline:
    rasterize -> brightness-threshold mask -> connected-component extraction
    -> crop -> aspect-ratio/pixel-density judgement, to flag pages that
    contain a handwritten-signature-*shaped* ink blob — unlike
    has_pdf_digital_signature() and the text keyword scan, this looks at
    actual pixels, so it can catch a scanned page with a wet signature and
    no text layer or "/Sig" field at all.

    This is opt-in on TWO independent levels, deliberately: (1) the Python
    package (`pip install 'metascout[visual-signature]'`), and (2) the
    ScanConfig.visual_signature flag — installing the extra does not turn
    this on by itself. Reasons to keep it optional even once installed:

    - It needs ImageMagick *and* Ghostscript installed system-wide (Wand
      shells out to ImageMagick, which itself delegates PDF rasterization
      to Ghostscript) — a real, non-trivial native install on top of
      exiftool, not just a pip package.
    - The upstream project has been unmaintained since 2022 and already
      triggers a scikit-image FutureWarning on current versions — genuine
      bit-rot risk, suppressed here rather than surfaced per-call.
    - Detection is heuristic and parameter-sensitive (default aspect-ratio
      window rejects very wide/flat signatures) — false negatives on real
      signatures are plausible depending on scan quality and signature
      style; treat a `False`/`None` result as "couldn't confirm," not
      "definitely no signature."

    Returns True if a signature-shaped region was found on any page, False
    if the pipeline ran cleanly but found nothing, or None if it couldn't
    run at all (package not installed, unsupported filetype, or a runtime
    failure — e.g. Ghostscript missing, a corrupt/encrypted file).
    """
    if not SIGNATURE_DETECT_AVAILABLE:
        return None
    if filetype.lower().lstrip(".") not in _SUPPORTED_FILETYPES:
        return None

    try:
        loader = Loader()
        extractor = Extractor()
        cropper = Cropper()
        judger = Judger()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            masks = loader.get_masks(local_path)
            for mask in masks:
                labeled_mask = extractor.extract(mask)
                results = cropper.run(labeled_mask)
                if any(judger.judge(region["cropped_mask"]) for region in results.values()):
                    return True
        return False
    except Exception:
        return None
