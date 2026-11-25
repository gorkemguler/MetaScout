import base64
import struct
import subprocess
from unittest.mock import patch

import pytest

from metascout.metadata import exiftool_wrapper as ew
from metascout.metadata.analyzer import analyze
from metascout.metadata.ole_media import _drawing_group, carve_pictures, extract_ole_media, is_ole_file
from metascout.models import DiscoverySource, DownloadedDocument

# A real, decodable 1x1 JPEG with no metadata.
TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDACgcHiMeGSgjISMtKygwPGRBPDc3PHtYXUlkkYCZlo+AjIqgtObDoKrarYqMyP/L2u71////"
    "m8H////6/+b9//j/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAAAP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AP//Z"
)
FREE, END, FATSECT, NOSTREAM = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF


def _segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def _jpeg(exif: bytes = b"", *, scan: bytes = b"\x12\x34\x56") -> bytes:
    """A JPEG as far as its structure goes: signature, segments, scan, end."""
    app1 = _segment(0xE1, b"Exif\x00\x00" + exif) if exif else b""
    return b"\xff\xd8" + _segment(0xE0, b"JFIF\x00") + app1 + _segment(0xDB, b"\x00" * 65) \
        + _segment(0xDA, b"\x01\x01\x00\x00\x3f\x00") + scan + b"\xff\xd9"


def _png(*chunks: tuple[bytes, bytes]) -> bytes:
    body = b"".join(struct.pack(">I", len(data)) + kind + data + b"\x00\x00\x00\x00" for kind, data in chunks)
    return b"\x89PNG\r\n\x1a\n" + body


def _ole_file(streams: dict[str, bytes]) -> bytes:
    """A minimal OLE2 compound file (version 3, 512-byte sectors) holding the
    given streams. Each must be at least 4096 bytes: smaller ones would live
    in the mini stream, which this writer doesn't build."""
    assert all(len(data) >= 4096 for data in streams.values())
    names = sorted(streams, key=lambda n: (len(n), n.upper()))

    def sectors_for(size: int) -> int:
        return -(-size // 512)

    starts, next_sector = {}, 0
    for name in names:
        starts[name] = next_sector
        next_sector += sectors_for(len(streams[name]))
    dir_start, dir_sectors = next_sector, sectors_for((len(names) + 1) * 128)
    used = dir_start + dir_sectors
    fat_sectors = 1
    while fat_sectors * 128 < used + fat_sectors:
        fat_sectors += 1
    fat_start = used

    fat = []
    for name in names:
        count = sectors_for(len(streams[name]))
        fat += [starts[name] + i + 1 for i in range(count - 1)] + [END]
    fat += [dir_start + i + 1 for i in range(dir_sectors - 1)] + [END]
    fat += [FATSECT] * fat_sectors
    fat += [FREE] * (fat_sectors * 128 - len(fat))

    def entry(name: str, kind: int, *, right=NOSTREAM, child=NOSTREAM, start=END, size=0) -> bytes:
        raw = (name + "\x00").encode("utf-16-le")
        return raw.ljust(64, b"\x00") + struct.pack("<HBBIII", len(raw), kind, 1, NOSTREAM, right, child) \
            + b"\x00" * 36 + struct.pack("<IQ", start, size)

    directory = entry("Root Entry", 5, child=1 if names else NOSTREAM)
    for i, name in enumerate(names, 1):
        directory += entry(name, 2, right=i + 1 if i < len(names) else NOSTREAM,
                           start=starts[name], size=len(streams[name]))
    directory = directory.ljust(dir_sectors * 512, b"\x00")

    header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16 \
        + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\x00" * 6 \
        + struct.pack("<IIIIIIIII", 0, fat_sectors, dir_start, 0, 4096, END, 0, END, 0) \
        + struct.pack("<109I", *([fat_start + i for i in range(fat_sectors)] + [FREE] * (109 - fat_sectors)))
    body = b"".join(streams[name].ljust(sectors_for(len(streams[name])) * 512, b"\x00") for name in names)
    return header + body + directory + struct.pack(f"<{len(fat)}I", *fat)


def _doc(path, streams):
    path.write_bytes(_ole_file(streams))
    return DownloadedDocument(url=f"https://example.com/{path.name}", local_path=str(path),
                              filetype=path.suffix[1:], source=DiscoverySource.CRAWL)


# --- finding a picture in a run of bytes ---

def test_a_jpeg_is_carved_whole_from_between_other_bytes():
    picture = _jpeg(b"GPS and camera data")

    assert carve_pictures(b"\x00" * 500 + picture + b"trailing record", max_bytes=10**6, limit=10) == [("jpg", picture)]


def test_the_thumbnail_inside_an_exif_block_does_not_cut_the_picture_short():
    thumbnail = _jpeg(scan=b"\x01\x02")  # a complete JPEG, signature and end marker included
    picture = _jpeg(b"before" + thumbnail + b"after: the part that would be lost")

    assert carve_pictures(picture, max_bytes=10**6, limit=10) == [("jpg", picture)]


def test_pictures_without_metadata_are_not_worth_extracting():
    assert carve_pictures(TINY_JPEG + _jpeg(), max_bytes=10**6, limit=10) == []
    assert carve_pictures(_png((b"IHDR", b"\x00" * 13), (b"IDAT", b"xx"), (b"IEND", b"")), max_bytes=10**6, limit=10) == []


def test_a_png_with_text_chunks_is_carved_up_to_its_end_chunk():
    picture = _png((b"IHDR", b"\x00" * 13), (b"tEXt", b"Author\x00jdoe"), (b"IDAT", b"xx"), (b"IEND", b""))

    assert carve_pictures(b"junk" + picture + b"more junk", max_bytes=10**6, limit=10) == [("png", picture)]


def test_bytes_that_only_look_like_a_signature_are_passed_over():
    picture = _jpeg(b"real")
    noise = b"\xff\xd8\xff\x00not a segment" + b"\xff\xd8\xff\xe1\x00\x01" + b"\x89PNG\r\n\x1a\n\x00\x00\x00\x01\x01\x02\x03\x04"

    assert carve_pictures(noise + picture, max_bytes=10**6, limit=10) == [("jpg", picture)]


def test_carving_respects_the_count_and_size_limits():
    small, big = _jpeg(b"a"), _jpeg(b"b" * 5000)

    assert carve_pictures(small * 5, max_bytes=10**6, limit=2) == [("jpg", small)] * 2
    assert carve_pictures(big + small, max_bytes=1000, limit=10) == [("jpg", small)]


# --- inside an OLE2 file ---

def test_pictures_are_named_after_the_stream_they_sit_in(tmp_path):
    first, second = _jpeg(b"first"), _jpeg(b"second")
    doc = tmp_path / "report.doc"
    doc.write_bytes(_ole_file({"WordDocument": b"\x00" * 4096,
                               "Data": b"\x00" * 3000 + first + b"\x00" * 2000 + second + b"\x00" * 4000}))
    out = tmp_path / "out"
    out.mkdir()

    extracted = extract_ole_media(str(doc), str(out), max_files=50, max_bytes=10**6)

    assert is_ole_file(str(doc))
    assert sorted(extracted.values()) == ["Data#1.jpg", "Data#2.jpg"]
    by_name = {name: open(path, "rb").read() for path, name in extracted.items()}
    assert by_name == {"Data#1.jpg": first, "Data#2.jpg": second}
    assert all(path.startswith(str(out)) for path in extracted)


def test_excel_pictures_are_joined_across_continue_records(tmp_path):
    picture = _jpeg(b"x" * 20000)  # larger than one 8224-byte record
    pieces = [picture[i:i + 8224] for i in range(0, len(picture), 8224)]
    records = struct.pack("<HH", 0x0809, 4) + b"\x00\x06\x05\x00"            # BOF
    records += struct.pack("<HH", 0x00EB, len(pieces[0])) + pieces[0]          # MsoDrawingGroup
    for piece in pieces[1:]:
        records += struct.pack("<HH", 0x003C, len(piece)) + piece              # Continue
    records += struct.pack("<HH", 0x00FC, 8) + b"\x00" * 8                     # an unrelated record ...
    records += struct.pack("<HH", 0x003C, 4) + b"\xff\xd8\xff\xe1"             # ... and its own Continue
    assert _drawing_group(records) == picture

    doc = tmp_path / "prices.xls"
    doc.write_bytes(_ole_file({"Workbook": records.ljust(24576, b"\x00")}))
    out = tmp_path / "out"
    out.mkdir()

    [(path, name)] = extract_ole_media(str(doc), str(out), max_files=50, max_bytes=10**6).items()

    assert name == "Workbook#1.jpg" and open(path, "rb").read() == picture


def test_a_file_that_is_not_ole_yields_nothing(tmp_path):
    rtf = tmp_path / "letter.doc"
    rtf.write_bytes(b"{\\rtf1 " + _jpeg(b"exif") + b"}")
    damaged = tmp_path / "damaged.doc"
    damaged.write_bytes(_ole_file({"Data": b"\x00" * 4096})[:700])

    assert not is_ole_file(str(rtf))
    assert extract_ole_media(str(rtf), str(tmp_path), max_files=50, max_bytes=10**6) == {}
    assert extract_ole_media(str(damaged), str(tmp_path), max_files=50, max_bytes=10**6) == {}


def test_extract_metadata_merges_tags_of_pictures_in_a_binary_office_file(tmp_path):
    doc = _doc(tmp_path / "minutes.doc", {"Data": b"\x00" * 4096 + _jpeg(b"exif")})

    def fake_batch(paths, timeout):
        if paths == [doc.local_path]:
            return [{"SourceFile": doc.local_path, "FlashPix:LastModifiedBy": "asmith"}]
        return [{"SourceFile": paths[0], "System:Directory": "/tmp/metascout-media-1",
                 "IFD0:Artist": "Jane Photographer", "Composite:GPSPosition": "41.015137 N, 28.979530 E"}]

    with patch.object(ew, "exiftool_available", return_value=True), \
         patch.object(ew, "_run_exiftool_batch", side_effect=fake_batch):
        [meta] = ew.extract_metadata([doc])

    assert meta.raw == {
        "FlashPix:LastModifiedBy": "asmith",
        "Data#1.jpg:IFD0:Artist": "Jane Photographer",
        "Data#1.jpg:Composite:GPSPosition": "41.015137 N, 28.979530 E",
    }


@pytest.mark.skipif(not ew.exiftool_available(), reason="needs exiftool")
def test_a_photo_in_an_old_word_file_gives_up_its_location(tmp_path):
    """End to end with the real exiftool: a geotagged photo placed in a .doc."""
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(TINY_JPEG)
    subprocess.run(["exiftool", "-q", "-overwrite_original", "-Artist=Jane Photographer", "-Model=EOS 5D Mark IV",
                    "-GPSLatitude=41.015137", "-GPSLatitudeRef=N", "-GPSLongitude=28.979530", "-GPSLongitudeRef=E",
                    str(photo)], check=True, capture_output=True)
    doc = _doc(tmp_path / "site-visit.doc", {"WordDocument": b"\x00" * 4096,
                                             "Data": b"\x00" * 5000 + photo.read_bytes() + b"\x00" * 100})

    findings = analyze(ew.extract_metadata([doc]), targets=["example.com"])

    assert list(findings.geolocation) == ["41.015137 N, 28.979530 E"]
    assert findings.geolocation["41.015137 N, 28.979530 E"].document_urls == ["https://example.com/site-visit.doc"]
    assert "Jane Photographer" in findings.usernames
