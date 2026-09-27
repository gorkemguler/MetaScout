import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from metascout.metadata import exiftool_wrapper as ew
from metascout.models import DiscoverySource, DownloadedDocument


def _docx_with_media(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("docProps/core.xml", "<x/>")
        for name, data in members.items():
            zf.writestr(name, data)


def test_split_tag_key_handles_plain_and_prefixed_keys():
    assert ew.split_tag_key("XMP-dc:Creator") == ("XMP-dc", "Creator")
    assert ew.split_tag_key("Doc3:XMP-xmpMM:DerivedFromFilePath") == ("XMP-xmpMM", "DerivedFromFilePath")
    assert ew.split_tag_key("word/media/image1.jpeg:IFD0:Artist") == ("IFD0", "Artist")


def test_exiftool_reads_embedded_documents_with_unique_keys():
    with patch.object(ew.subprocess, "run") as run:
        run.return_value.stdout = "[]"
        ew._run_exiftool_batch(["/tmp/a.pdf"], timeout=5)
    cmd = run.call_args.args[0]
    assert "-ee" in cmd
    assert "-G3:1" in cmd


def test_extract_zip_media_only_takes_pictures_under_generated_names(tmp_path):
    doc = tmp_path / "a.docx"
    _docx_with_media(doc, {
        "word/media/image1.jpeg": b"jpegdata",
        "word/media/../../evil.png": b"pngdata",
        "word/document.xml": b"<w/>",
    })
    out = tmp_path / "out"
    out.mkdir()

    extracted = ew._extract_zip_media(str(doc), str(out))

    assert sorted(extracted.values()) == ["word/media/../../evil.png", "word/media/image1.jpeg"]
    assert all(p.startswith(str(out)) for p in extracted)
    assert not (tmp_path / "evil.png").exists()


def test_extract_zip_media_caps_member_size(tmp_path, monkeypatch):
    monkeypatch.setattr(ew, "_MAX_MEDIA_BYTES", 4)
    doc = tmp_path / "a.docx"
    _docx_with_media(doc, {"word/media/big.jpg": b"123456789", "word/media/ok.jpg": b"123"})
    out = tmp_path / "out"
    out.mkdir()

    assert list(ew._extract_zip_media(str(doc), str(out)).values()) == ["word/media/ok.jpg"]


def test_extract_metadata_merges_office_picture_tags(tmp_path):
    doc_path = tmp_path / "a.docx"
    _docx_with_media(doc_path, {"word/media/image1.jpeg": b"jpegdata"})
    doc = DownloadedDocument(
        url="https://example.com/a.docx", local_path=str(doc_path), filetype="docx",
        source=DiscoverySource.CRAWL,
    )

    def fake_batch(paths, timeout):
        if paths == [str(doc_path)]:
            return [{"SourceFile": str(doc_path), "XML:LastModifiedBy": "asmith"}]
        return [{
            "SourceFile": paths[0],
            "System:Directory": "/private/var/folders/xx/T/metascout-media-1",
            "IFD0:Artist": "Jane Photographer",
            "Composite:GPSPosition": "41.015137 N, 28.979530 E",
        }]

    with patch.object(ew, "exiftool_available", return_value=True), \
         patch.object(ew, "_run_exiftool_batch", side_effect=fake_batch):
        [meta] = ew.extract_metadata([doc])

    assert meta.raw == {
        "XML:LastModifiedBy": "asmith",
        "word/media/image1.jpeg:IFD0:Artist": "Jane Photographer",
        "word/media/image1.jpeg:Composite:GPSPosition": "41.015137 N, 28.979530 E",
    }


def test_extract_metadata_does_not_open_pdfs_as_zip(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    doc = DownloadedDocument(url="https://example.com/a.pdf", local_path=str(pdf), filetype="pdf",
                             source=DiscoverySource.CRAWL)
    calls = []

    def fake_batch(paths, timeout):
        calls.append(paths)
        return [{"SourceFile": str(pdf), "PDF:Author": "jdoe"}]

    with patch.object(ew, "exiftool_available", return_value=True), \
         patch.object(ew, "_run_exiftool_batch", side_effect=fake_batch):
        [meta] = ew.extract_metadata([doc])

    assert calls == [[str(pdf)]]
    assert meta.raw == {"PDF:Author": "jdoe"}


def test_extract_metadata_keeps_the_archive_url_of_a_document(tmp_path):
    pdf = tmp_path / "removed.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    snapshot = "https://web.archive.org/web/20200101000000id_/https://example.com/removed.pdf"
    doc = DownloadedDocument(
        url="https://example.com/removed.pdf", local_path=str(pdf), filetype="pdf",
        source=DiscoverySource.WAYBACK, archive_url=snapshot,
    )

    with patch.object(ew, "exiftool_available", return_value=True), \
         patch.object(ew, "_run_exiftool_batch", return_value=[{"SourceFile": str(pdf), "PDF:Author": "jdoe"}]):
        [meta] = ew.extract_metadata([doc])

    assert meta.archive_url == snapshot


def _pdf_with_exiftool_update(path, size_prefix=b"%PDF-1.7\n" + b"x" * 100):
    path.write_bytes(size_prefix + b"trailer<</Info 38 0 R>>\n%%EOF" + ew._EXIFTOOL_UPDATE_MARKER + b"\ntrailer<</Root 1 0 R>>\n%%EOF")


def test_has_exiftool_update_detects_a_stripped_pdf(tmp_path):
    stripped = tmp_path / "stripped.pdf"
    _pdf_with_exiftool_update(stripped)
    plain = tmp_path / "plain.pdf"
    plain.write_bytes(b"%PDF-1.7\ntrailer<</Info 38 0 R>>\n%%EOF")

    assert ew._has_exiftool_update(str(stripped)) is True
    assert ew._has_exiftool_update(str(plain)) is False
    assert ew._has_exiftool_update(str(tmp_path / "missing.pdf")) is False


def test_extract_metadata_recovers_metadata_stripped_with_exiftool(tmp_path):
    pdf = tmp_path / "cleaned.pdf"
    _pdf_with_exiftool_update(pdf)
    doc = DownloadedDocument(url="https://example.gov/a.pdf", local_path=str(pdf), filetype="pdf",
                             source=DiscoverySource.MANUAL)
    reverted = {}

    def fake_batch(paths, timeout):
        if paths == [str(pdf)]:  # the stripped file itself has nothing left
            return [{"SourceFile": str(pdf), "PDF:PageCount": 5}]
        return [{"SourceFile": paths[0], "PDF:PageCount": 5, "PDF:Author": "Jane Doe",
                 "XMP-dc:Creator": "Jane Doe", "System:Directory": "/tmp/metascout-pdf-1"}]

    def fake_run(cmd, **kwargs):
        reverted["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch.object(ew, "exiftool_available", return_value=True), \
         patch.object(ew, "_run_exiftool_batch", side_effect=fake_batch), \
         patch.object(ew.subprocess, "run", side_effect=fake_run):
        [meta] = ew.extract_metadata([doc])

    assert "-pdf-update:all=" in reverted["cmd"]
    # the copy is reverted, never the downloaded evidence file
    assert str(pdf) not in reverted["cmd"]
    assert meta.metadata_stripped is True
    assert meta.raw["PDF-previous:PDF:Author"] == "Jane Doe"
    assert meta.raw["PDF-previous:XMP-dc:Creator"] == "Jane Doe"
    # unchanged tags aren't duplicated, and the temp copy's own paths are dropped
    assert "PDF-previous:PDF:PageCount" not in meta.raw
    assert not any("System" in k for k in meta.raw)


def test_extract_metadata_leaves_ordinary_pdfs_alone(tmp_path):
    pdf = tmp_path / "plain.pdf"
    pdf.write_bytes(b"%PDF-1.7\ntrailer<</Info 38 0 R>>\n%%EOF")
    doc = DownloadedDocument(url="https://example.gov/a.pdf", local_path=str(pdf), filetype="pdf",
                             source=DiscoverySource.MANUAL)

    with patch.object(ew, "exiftool_available", return_value=True), \
         patch.object(ew, "_run_exiftool_batch", return_value=[{"SourceFile": str(pdf), "PDF:Author": "jdoe"}]), \
         patch.object(ew.subprocess, "run") as run:
        [meta] = ew.extract_metadata([doc])

    run.assert_not_called()
    assert meta.metadata_stripped is False
    assert meta.raw == {"PDF:Author": "jdoe"}
