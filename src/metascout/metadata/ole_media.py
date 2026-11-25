"""Pictures inside old binary Office files (.doc, .xls, .ppt).

These are OLE2 compound files. Unlike the ZIP-based formats they have no
media folder to unpack: a picture is a run of bytes somewhere inside a
stream ("Data" in Word, "Pictures" in PowerPoint, the workbook stream in
Excel), wrapped in drawing records. exiftool reads the document's own
properties and stops there, so a photo pasted into a 2005 Word file keeps
its GPS position and camera serial out of sight.

The pictures are found by their own structure rather than by parsing every
Office drawing record: a JPEG or PNG is followed segment by segment from
its signature, which both rules out chance matches and gives its length.
"""
from __future__ import annotations

import os
import struct

try:
    import olefile
except ImportError:  # a core dependency, but a checkout updated without reinstalling lacks it
    olefile = None

OLE_DOC_TYPES = {"doc", "dot", "xls", "xlt", "xla", "ppt", "pps", "pot"}

_JPEG_SOI = b"\xff\xd8\xff"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# JPEG segments that can carry metadata: APP1 (EXIF, XMP), APP13 (IPTC), COM.
_JPEG_METADATA_MARKERS = {0xE1, 0xED, 0xFE}
_PNG_METADATA_CHUNKS = {b"tEXt", b"iTXt", b"zTXt", b"eXIf"}
# Excel stores its pictures in MsoDrawingGroup records, cut into pieces of at
# most 8224 bytes that carry on in Continue records. Read as one run of bytes
# the workbook stream has a record header in the middle of every picture.
_BIFF_DRAWING_GROUP, _BIFF_CONTINUE = 0x00EB, 0x003C
_WORKBOOK_STREAMS = {"workbook", "book"}
_MAX_STREAM_BYTES = 200 * 1024 * 1024


def _jpeg(data: bytes, start: int, max_bytes: int) -> tuple[int, bool] | None:
    """(end offset, has metadata) of the JPEG at `start`, or None when the
    bytes after the signature don't form one. Walking the segments by their
    declared lengths steps over the thumbnail inside an EXIF block, which
    begins with a JPEG signature of its own."""
    pos, has_metadata = start + 2, False
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker == 0xFF:  # padding before a marker
            pos += 1
            continue
        if marker in (0x00, 0xD8) or 0xD0 <= marker <= 0xD9:
            return None  # none of these belongs between the signature and the image data
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        if length < 2:
            return None
        if marker == 0xDA:  # start of scan: compressed data runs to the end marker
            scan, limit = pos + 2 + length, start + max_bytes
            if scan > limit:
                return scan, False  # even its header is over the size cap
            # Everything worth reading sits before the scan, so a picture
            # that runs past the cap is cut there rather than dropped.
            end = data.find(b"\xff\xd9", scan, limit)
            return (end + 2 if end != -1 else min(len(data), limit)), has_metadata
        has_metadata = has_metadata or marker in _JPEG_METADATA_MARKERS
        pos += 2 + length
    return None


def _png(data: bytes, start: int) -> tuple[int, bool] | None:
    pos, has_metadata = start + len(_PNG_SIGNATURE), False
    while pos + 12 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        if not kind.isalpha():
            return None
        has_metadata = has_metadata or kind in _PNG_METADATA_CHUNKS
        pos += 12 + length
        if kind == b"IEND":
            return (pos, has_metadata) if pos <= len(data) else None
    return None


def carve_pictures(data: bytes, *, max_bytes: int, limit: int) -> list[tuple[str, bytes]]:
    """The JPEG and PNG pictures in a run of bytes, as (extension, bytes).
    Pictures with no metadata segment are left out: there is nothing in
    them to read."""
    found: list[tuple[str, bytes]] = []
    pos = 0
    while len(found) < limit:
        jpeg, png = data.find(_JPEG_SOI, pos), data.find(_PNG_SIGNATURE, pos)
        starts = [s for s in (jpeg, png) if s != -1]
        if not starts:
            break
        start = min(starts)
        ext, parsed = ("jpg", _jpeg(data, start, max_bytes)) if start == jpeg else ("png", _png(data, start))
        if parsed is None:
            pos = start + 1
            continue
        end, has_metadata = parsed
        if has_metadata and end - start <= max_bytes:
            found.append((ext, data[start:end]))
        pos = end
    return found


def _drawing_group(workbook: bytes) -> bytes:
    """The payload of an Excel workbook's drawing-group records, joined."""
    parts, pos, in_group = [], 0, False
    while pos + 4 <= len(workbook):
        record, size = struct.unpack_from("<HH", workbook, pos)
        payload = workbook[pos + 4:pos + 4 + size]
        if record == _BIFF_DRAWING_GROUP or (record == _BIFF_CONTINUE and in_group):
            parts.append(payload)
            in_group = True
        else:
            in_group = False
        pos += 4 + size
    return b"".join(parts)


def is_ole_file(path: str) -> bool:
    return olefile is not None and olefile.isOleFile(path)


def extract_ole_media(doc_path: str, dest_dir: str, *, max_files: int, max_bytes: int) -> dict[str, str]:
    """Write the pictures inside an OLE2 document into dest_dir.

    Returns {extracted path: member name}, the name being the stream the
    picture sat in and its position there ("Data#1.jpg"). A file that can't
    be read as OLE yields nothing: the document itself still counts.
    """
    extracted: dict[str, str] = {}
    if olefile is None:
        return extracted
    try:
        with olefile.OleFileIO(doc_path) as ole:
            for entry in ole.listdir(streams=True, storages=False):
                if len(extracted) >= max_files:
                    break
                if ole.get_size(entry) > _MAX_STREAM_BYTES:
                    continue
                data = ole.openstream(entry).read()
                if entry[-1].lower() in _WORKBOOK_STREAMS:
                    data = _drawing_group(data)
                stream = "/".join(entry)
                pictures = carve_pictures(data, max_bytes=max_bytes, limit=max_files - len(extracted))
                for n, (ext, picture) in enumerate(pictures, 1):
                    out_path = os.path.join(dest_dir, f"{len(extracted)}.{ext}")
                    with open(out_path, "wb") as fh:
                        fh.write(picture)
                    extracted[out_path] = f"{stream}#{n}.{ext}"
    except Exception:  # noqa: BLE001 - olefile raises plain OSError/IndexError/struct.error on damaged files
        pass
    return extracted
