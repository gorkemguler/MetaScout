from __future__ import annotations

import json
import shutil
import subprocess

from ..models import DocumentMetadata, DownloadedDocument

_BATCH_SIZE = 40


def exiftool_available() -> bool:
    return shutil.which("exiftool") is not None


def _run_exiftool_batch(paths: list[str], timeout: int) -> list[dict]:
    # -c "%.6f": print GPS coordinates as plain decimal degrees (e.g.
    # "41.015137 N, 28.979530 E" in Composite:GPSPosition) instead of
    # exiftool's default DMS string — only affects coordinate formatting,
    # every other tag stays in its normal human-readable form (unlike the
    # global -n flag, which would also turn OS/software enum tags numeric
    # and break the analyzer's string-matching logic for those).
    cmd = ["exiftool", "-j", "-a", "-G1", "-c", "%.6f", "-api", "largefilesupport=1", *paths]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return []
    if not proc.stdout:
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []


def extract_metadata(
    downloaded: list[DownloadedDocument],
    *,
    per_file_timeout: int = 20,
) -> list[DocumentMetadata]:
    """Run ExifTool over successfully downloaded files and map results back to URLs.

    Requires the `exiftool` binary to be installed and on PATH
    (macOS: `brew install exiftool`, Debian/Ubuntu: `apt install libimage-exiftool-perl`).
    """
    if not exiftool_available():
        raise RuntimeError(
            "exiftool binary not found on PATH. Install it first, e.g. "
            "`brew install exiftool` (macOS) or `apt install libimage-exiftool-perl` (Debian/Ubuntu)."
        )

    ok_docs = [d for d in downloaded if d.local_path and not d.error]
    path_to_doc = {d.local_path: d for d in ok_docs}
    results: list[DocumentMetadata] = []

    for i in range(0, len(ok_docs), _BATCH_SIZE):
        batch = ok_docs[i : i + _BATCH_SIZE]
        timeout = per_file_timeout * len(batch)
        records = _run_exiftool_batch([d.local_path for d in batch], timeout)
        seen_paths = set()
        for record in records:
            source_file = record.pop("SourceFile", None)
            doc = path_to_doc.get(source_file)
            if doc is None:
                continue
            seen_paths.add(doc.local_path)
            results.append(DocumentMetadata(url=doc.url, local_path=doc.local_path, filetype=doc.filetype, raw=record))
        for doc in batch:
            if doc.local_path not in seen_paths:
                results.append(
                    DocumentMetadata(
                        url=doc.url, local_path=doc.local_path, filetype=doc.filetype,
                        error="exiftool produced no output for this file",
                    )
                )

    for doc in downloaded:
        if doc.error:
            results.append(DocumentMetadata(url=doc.url, local_path=doc.local_path, filetype=doc.filetype, error=doc.error))

    return results
