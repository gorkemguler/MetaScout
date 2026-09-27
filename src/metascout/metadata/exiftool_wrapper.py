from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile

from ..models import DocumentMetadata, DownloadedDocument

_BATCH_SIZE = 40

# OOXML / ODF documents are ZIP containers whose pictures (word/media/,
# ppt/media/, Pictures/, ...) keep their own EXIF/XMP — GPS, camera serial,
# photographer, the Photoshop file path they were exported from. exiftool
# only reads the container's docProps/meta.xml, even with -ee, so those
# pictures are pulled out and run through exiftool separately.
_ZIP_DOC_TYPES = {
    "docx", "docm", "dotx", "xlsx", "xlsm", "pptx", "pptm", "ppsx",
    "odt", "ods", "odp", "odg",
}
_MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".webp"}
_MAX_MEDIA_PER_DOC = 50
_MAX_MEDIA_BYTES = 30 * 1024 * 1024
# Groups describing the extracted temp copy of a picture, not the picture.
_MEDIA_SKIP_GROUPS = {"System", "ExifTool"}

# ExifTool doesn't rewrite a PDF to remove metadata: it appends an
# incremental update whose trailer simply stops pointing at the old Info
# dictionary and XMP. The original bytes are still in the file, and exiftool
# honours its own deletion when reading, so a document "cleaned" this way
# looks empty to any scan. Undoing that update on a throwaway copy brings
# back what the document said before someone stripped it.
_EXIFTOOL_UPDATE_MARKER = b"%BeginExifToolUpdate"
# The update is appended, so the marker sits near the end of the file.
_TAIL_SCAN_BYTES = 2 * 1024 * 1024
_PREVIOUS_PREFIX = "PDF-previous"


def exiftool_available() -> bool:
    return shutil.which("exiftool") is not None


def split_tag_key(key: str) -> tuple[str, str]:
    """("XMP-dc", "Creator") for "XMP-dc:Creator", and likewise for the
    prefixed keys of embedded content ("Doc1:XMP-dc:Creator",
    "word/media/image1.jpeg:IFD0:Artist")."""
    prefix, _, tag = key.rpartition(":")
    return prefix.rpartition(":")[2], tag


def _run_exiftool_batch(paths: list[str], timeout: int) -> list[dict]:
    # -c "%.6f": print GPS coordinates as plain decimal degrees (e.g.
    # "41.015137 N, 28.979530 E" in Composite:GPSPosition) instead of
    # exiftool's default DMS string — only affects coordinate formatting,
    # every other tag stays in its normal human-readable form (unlike the
    # global -n flag, which would also turn OS/software enum tags numeric
    # and break the analyzer's string-matching logic for those).
    # -ee: also read documents embedded in the file — the placed JPEG/
    # JPEG2000 images and Illustrator data inside a PDF, each with its own
    # XMP (source file paths on a designer's Mac or a mounted file share).
    # -G3:1: -j silently drops every tag whose "Group:Tag" name repeats, so
    # with -ee all but the first embedded image would be lost. Family-3
    # grouping keeps the main document's keys as plain "Group:Tag" and
    # gives each embedded one a unique "Doc1:Group:Tag" key.
    cmd = ["exiftool", "-j", "-a", "-G3:1", "-ee", "-c", "%.6f", "-api", "largefilesupport=1", *paths]
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


def _extract_zip_media(doc_path: str, dest_dir: str) -> dict[str, str]:
    """Copy the pictures inside an OOXML/ODF container into dest_dir.

    Returns {extracted path: member name}. Members are written under
    generated names (never their in-archive path, so no path traversal), and
    count/size are capped against zip bombs.
    """
    extracted: dict[str, str] = {}
    try:
        with zipfile.ZipFile(doc_path) as zf:
            for info in zf.infolist():
                if len(extracted) >= _MAX_MEDIA_PER_DOC:
                    break
                ext = os.path.splitext(info.filename)[1].lower()
                if info.is_dir() or ext not in _MEDIA_EXTS or info.file_size > _MAX_MEDIA_BYTES:
                    continue
                with zf.open(info) as src:
                    data = src.read(_MAX_MEDIA_BYTES + 1)
                if len(data) > _MAX_MEDIA_BYTES:
                    continue
                out_path = os.path.join(dest_dir, f"{len(extracted)}{ext}")
                with open(out_path, "wb") as dst:
                    dst.write(data)
                extracted[out_path] = info.filename
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, RuntimeError, NotImplementedError):
        # RuntimeError: encrypted member; NotImplementedError: unsupported
        # compression — skip the pictures, the document itself still counts.
        pass
    return extracted


def _embedded_media_metadata(doc: DownloadedDocument, per_file_timeout: int) -> dict:
    """exiftool tags of every picture inside a ZIP-based document, keyed
    "<member name>:<Group>:<Tag>" (e.g. "word/media/image1.jpeg:IFD0:Artist")."""
    if doc.filetype.lower() not in _ZIP_DOC_TYPES or not zipfile.is_zipfile(doc.local_path):
        return {}
    merged: dict = {}
    with tempfile.TemporaryDirectory(prefix="metascout-media-") as tmp:
        media = _extract_zip_media(doc.local_path, tmp)
        paths = list(media)
        for i in range(0, len(paths), _BATCH_SIZE):
            batch = paths[i : i + _BATCH_SIZE]
            for record in _run_exiftool_batch(batch, per_file_timeout * len(batch)):
                member = media.get(record.pop("SourceFile", None))
                if member is None:
                    continue
                prefix = member.replace(":", "_")
                for key, value in record.items():
                    if split_tag_key(key)[0] in _MEDIA_SKIP_GROUPS:
                        continue
                    merged[f"{prefix}:{key}"] = value
    return merged


def _has_exiftool_update(path: str) -> bool:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > _TAIL_SCAN_BYTES:
                fh.seek(size - _TAIL_SCAN_BYTES)
            return _EXIFTOOL_UPDATE_MARKER in fh.read()
    except OSError:
        return False


def _recovered_pdf_metadata(doc: DownloadedDocument, current: dict, per_file_timeout: int) -> dict:
    """Metadata of the revision before someone stripped it with ExifTool,
    keyed "PDF-previous:<Group>:<Tag>". Empty when the file carries no such
    update, or when undoing it fails — the scan then just reports what the
    current revision has."""
    if doc.filetype.lower() != "pdf" or not _has_exiftool_update(doc.local_path):
        return {}

    with tempfile.TemporaryDirectory(prefix="metascout-pdf-") as tmp:
        copy_path = os.path.join(tmp, "previous.pdf")
        try:
            shutil.copyfile(doc.local_path, copy_path)
        except OSError:
            return {}
        # Undo only ExifTool's own update, and only on our copy — the
        # downloaded evidence file is never modified.
        try:
            proc = subprocess.run(
                ["exiftool", "-pdf-update:all=", "-overwrite_original", copy_path],
                capture_output=True, text=True, timeout=per_file_timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            return {}
        if proc.returncode != 0:
            return {}

        recovered = {}
        for record in _run_exiftool_batch([copy_path], per_file_timeout):
            record.pop("SourceFile", None)
            for key, value in record.items():
                if split_tag_key(key)[0] in _MEDIA_SKIP_GROUPS:
                    continue
                if current.get(key) == value:  # unchanged by the stripping
                    continue
                recovered[f"{_PREVIOUS_PREFIX}:{key}"] = value
        return recovered


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
            recovered = _recovered_pdf_metadata(doc, record, per_file_timeout)
            record.update(recovered)
            record.update(_embedded_media_metadata(doc, per_file_timeout))
            results.append(DocumentMetadata(
                url=doc.url, local_path=doc.local_path, filetype=doc.filetype,
                raw=record, archive_url=doc.archive_url, metadata_stripped=bool(recovered),
            ))
        for doc in batch:
            if doc.local_path not in seen_paths:
                results.append(
                    DocumentMetadata(
                        url=doc.url, local_path=doc.local_path, filetype=doc.filetype,
                        error="exiftool produced no output for this file", archive_url=doc.archive_url,
                    )
                )

    for doc in downloaded:
        if doc.error:
            results.append(DocumentMetadata(
                url=doc.url, local_path=doc.local_path, filetype=doc.filetype,
                error=doc.error, archive_url=doc.archive_url,
            ))

    return results
