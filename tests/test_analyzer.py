from metascout.metadata.analyzer import analyze
from metascout.models import DocumentMetadata


def test_analyze_extracts_username_email_software_and_paths():
    doc = DocumentMetadata(
        url="https://example.com/report.pdf",
        local_path="/tmp/report.pdf",
        filetype="pdf",
        raw={
            "PDF:Author": "jdoe",
            "PDF:Producer": "Microsoft Word: Windows PDF Library",
            "XMP-dc:Creator": "jdoe",
            "PDF:Company": "Acme Corp",
            "PDF:Comments": "contact jdoe@example.com or see C:\\Users\\jdoe\\Documents\\report.docx",
            "File:FileSize": 12345,
        },
    )

    findings = analyze([doc], targets=["example.com"])

    assert "jdoe" in findings.usernames
    assert "jdoe@example.com" in findings.emails
    assert any("Windows PDF Library" in s for s in findings.software)
    assert any(p.startswith("C:\\Users\\jdoe") for p in findings.internal_paths)
    assert "Windows" in "".join(findings.operating_systems.keys())


def test_analyze_extracts_gps_geolocation_from_composite_tag():
    # Composite:GPSPosition is what exiftool_wrapper.py's `-c "%.6f"` flag
    # produces for a photo with embedded GPS EXIF (e.g. a phone photo pasted
    # into a Word doc) — real format verified live: "41.015137 N, 28.979530 E".
    doc = DocumentMetadata(
        url="https://example.com/report.docx",
        local_path="/tmp/report.docx",
        filetype="docx",
        raw={
            "Composite:GPSPosition": "41.015137 N, 28.979530 E",
            "GPS:GPSLatitude": "41.015137",
        },
    )

    findings = analyze([doc], targets=["example.com"])

    assert "41.015137 N, 28.979530 E" in findings.geolocation
    assert findings.geolocation["41.015137 N, 28.979530 E"].document_urls == ["https://example.com/report.docx"]


def test_analyze_geolocation_empty_when_no_gps_tag():
    doc = DocumentMetadata(
        url="https://example.com/report.pdf", local_path="/tmp/report.pdf", filetype="pdf",
        raw={"PDF:Author": "jdoe"},
    )
    findings = analyze([doc], targets=["example.com"])
    assert findings.geolocation == {}


def test_analyze_records_document_errors():
    doc = DocumentMetadata(url="https://example.com/x.pdf", local_path="", filetype="pdf", error="404 not found")
    findings = analyze([doc], targets=["example.com"])
    assert findings.errors == ["https://example.com/x.pdf: 404 not found"]
    assert findings.usernames == {}


def test_analyze_counts_documents_per_target():
    docs = [
        DocumentMetadata(url="https://a.example.com/one.pdf", local_path="/tmp/one.pdf", filetype="pdf", raw={}),
        DocumentMetadata(url="https://example.org/two.pdf", local_path="/tmp/two.pdf", filetype="pdf", raw={}),
        DocumentMetadata(url="https://example.org/three.pdf", local_path="/tmp/three.pdf", filetype="pdf", raw={}),
        DocumentMetadata(url="https://unrelated.net/four.pdf", local_path="", filetype="pdf", error="timeout"),
    ]

    findings = analyze(docs, targets=["example.com", "example.org"])

    assert findings.documents_by_target == {"example.com": 1, "example.org": 2}


def test_analyze_extracts_posix_paths_from_list_valued_xmp_tags():
    # exiftool -j emits multi-valued XMP (xmpMM:Ingredients / xmpMM:Manifest
    # stRef:filePath of an InDesign/Illustrator PDF) as JSON lists, with
    # spaces and non-ASCII characters in the path segments.
    placed = [
        "/Users/designer-01/Desktop/Client Archive/2025 Annual Report/cover bg.tif",
        "/Users/designer-01/Desktop/2025 Annual Report/ŞEHİR görsel.tif",
    ]
    doc = DocumentMetadata(
        url="https://example.com/annual.pdf",
        local_path="/tmp/annual.pdf",
        filetype="pdf",
        raw={
            "XMP-xmpMM:IngredientsFilePath": placed,
            "XMP-xmpMM:ManifestReferenceFilePath": placed + [placed[0]],
            "XMP-xmpMM:HistorySoftwareAgent": ["Adobe Illustrator 28.0 (Macintosh)"],
            "XMP-xmpTPg:SwatchColorantTint": [100.0, 50.0],
            "PostScript:For": ["Designer-01", ""],
        },
    )

    findings = analyze([doc], targets=["example.com"])

    assert set(findings.internal_paths) == set(placed)
    assert findings.internal_paths[placed[0]].field_name == "IngredientsFilePath"
    assert "designer-01" in findings.usernames
    assert findings.usernames["designer-01"].field_name == "home directory"
    assert "Designer-01" in findings.usernames
    assert "Adobe Illustrator 28.0 (Macintosh)" in findings.software


def test_analyze_posix_paths_ignore_urls_and_match_file_uris():
    doc = DocumentMetadata(
        url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf",
        raw={
            "XMP-xmpRights:WebStatement": "https://example.com/home/terms.html",
            "XMP-dc:Format": "application/pdf",
            "XMP-xmpMM:DerivedFromFilePath": "file:///Volumes/DesignShare/Projects/brochure.indd",
            "XMP-pdf:Keywords": "draft at /home/alice/work/draft v2.odt, final elsewhere",
        },
    )

    findings = analyze([doc], targets=["example.com"])

    assert set(findings.internal_paths) == {
        "/Volumes/DesignShare/Projects/brochure.indd",
        "/home/alice/work/draft v2.odt",
    }
    assert set(findings.usernames) == {"alice"}


def test_analyze_forward_slash_windows_paths_and_generic_profiles():
    doc = DocumentMetadata(
        url="https://example.com/a.docx", local_path="/tmp/a.docx", filetype="docx",
        raw={
            "XMP-xmpMM:DerivedFromFilePath": "file:///D:/Users/bsmith/Projects/plan.docx",
            "XMP-xmpMM:IngredientsFilePath": ["/Users/Shared/Stock/photo.jpg", "C:\\Users\\Public\\Pictures\\logo.png"],
        },
    )

    findings = analyze([doc], targets=["example.com"])

    assert "D:/Users/bsmith/Projects/plan.docx" in findings.internal_paths
    assert "/Users/Shared/Stock/photo.jpg" in findings.internal_paths
    assert set(findings.usernames) == {"bsmith"}


def test_analyze_ignores_scanners_own_download_location():
    # System:* describes the local downloaded copy — its path is the
    # *scanning* machine's, never a finding about the target.
    doc = DocumentMetadata(
        url="https://example.com/a.pdf", local_path="/Users/analyst/out/a.pdf", filetype="pdf",
        raw={
            "System:Directory": "/Users/analyst/metascout_output/downloads",
            "System:FileName": "abc_a.pdf",
            "PDF:Author": "jdoe",
        },
    )

    findings = analyze([doc], targets=["example.com"])

    assert findings.internal_paths == {}
    assert set(findings.usernames) == {"jdoe"}


def test_analyze_pdf_and_postscript_creator_is_software_not_username():
    # PDF Info /Creator and PostScript %%Creator name the producing app;
    # only XMP-dc:Creator is a person.
    doc = DocumentMetadata(
        url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf",
        raw={
            "PDF:Creator": "Adobe InDesign 20.4 (Macintosh)",
            "PostScript:Creator": "Adobe Illustrator(R) 24.0",
            "XMP-dc:Creator": ["Jane Author"],
        },
    )

    findings = analyze([doc], targets=["example.com"])

    assert set(findings.usernames) == {"Jane Author"}
    assert {"Adobe InDesign 20.4 (Macintosh)", "Adobe Illustrator(R) 24.0"} <= set(findings.software)


def test_analyze_reads_embedded_content_keys():
    # -G3:1 -ee keys ("Doc1:Group:Tag") and pictures pulled out of an
    # OOXML container ("<member>:Group:Tag") keep their field semantics.
    doc = DocumentMetadata(
        url="https://example.com/a.docx", local_path="/tmp/a.docx", filetype="docx",
        raw={
            "Doc1:XMP-xmpMM:DerivedFromFilePath": "/Volumes/DesignShare/Stock/city.psd",
            "Doc1:PDF:Creator": "Adobe Photoshop 25.0 (Windows)",
            "word/media/image1.jpeg:IFD0:Artist": "Jane Photographer",
            "word/media/image1.jpeg:XMP-photoshop:CaptionWriter": "Cap Writer",
            "word/media/image1.jpeg:Composite:GPSPosition": "41.015137 N, 28.979530 E",
            "XML:Manager": "Bob Manager",
            "XMP-meta:Initial-creator": "First Person",
        },
    )

    findings = analyze([doc], targets=["example.com"])

    assert "/Volumes/DesignShare/Stock/city.psd" in findings.internal_paths
    assert "Adobe Photoshop 25.0 (Windows)" in findings.software
    assert set(findings.usernames) == {"Jane Photographer", "Cap Writer", "Bob Manager", "First Person"}
    assert findings.usernames["Jane Photographer"].field_name == "Artist"
    assert "41.015137 N, 28.979530 E" in findings.geolocation


def test_analyze_skips_adobe_scratch_files_but_keeps_real_tmp_paths():
    doc = DocumentMetadata(
        url="https://example.com/a.pdf", local_path="/tmp/a.pdf", filetype="pdf",
        raw={"XMP-xmpMM:ManifestReferenceFilePath": [
            "/var/tmp/wv93Ri.tif", "/private/var/tmp/RgGVnC.tif", "/tmp/Budget Draft 2025.xlsx",
        ]},
    )

    findings = analyze([doc], targets=["example.com"])

    assert set(findings.internal_paths) == {"/tmp/Budget Draft 2025.xlsx"}


def test_analyze_internal_hosts_in_metadata_urls():
    doc = DocumentMetadata(
        url="https://example.com/a.docx", local_path="/tmp/a.docx", filetype="docx",
        raw={
            "XML:HyperlinkBase": "http://intranet.acme.local/docs/",
            "XMP-xmp:BaseURL": "http://10.20.30.40/share/",
            "XMP-xmpRights:WebStatement": "https://www.example.com/terms",
        },
    )

    findings = analyze([doc], targets=["example.com"])

    assert set(findings.servers_and_printers) == {"intranet.acme.local", "10.20.30.40"}


def test_analyze_extracts_classification_labels():
    doc = DocumentMetadata(
        url="https://example.gov/plan.docx", local_path="/tmp/a.docx", filetype="docx",
        raw={
            # Microsoft Purview / AIP writes the label plus bookkeeping siblings
            "XML:MSIP_Label_1111_Name": "Confidential - Internal",
            "XML:MSIP_Label_1111_SiteId": "2222-aaaa-bbbb",
            "XML:MSIP_Label_1111_Enabled": "true",
            "XML:Classification": "Hizmete Özel",
        },
    )

    findings = analyze([doc], targets=["example.gov"])

    assert set(findings.classification_labels) == {"Confidential - Internal", "Hizmete Özel"}
    assert findings.classification_labels["Confidential - Internal"].field_name == "MSIP_Label_1111_Name"
    assert sorted(findings.restricted_classification_labels) == ["Confidential - Internal", "Hizmete Özel"]


def test_analyze_parses_titus_label_blob():
    doc = DocumentMetadata(
        url="https://example.gov/a.pdf", local_path="/tmp/a.pdf", filetype="pdf",
        raw={"XMP-tmi:Metadata": "@NAMESPACE=http://www.titus.com/ns/nato @TRACKINGID=f2c66ddb-1c7d "
                                 "Ownership[0]='None (Public)' Classification='NATO RESTRICTED' "
                                 "Releasability= Only= Limited= AdministrativeMarkings= "},
    )

    findings = analyze([doc], targets=["example.gov"])

    # empty markings are skipped; the tracking id isn't a label
    assert set(findings.classification_labels) == {"Ownership: None (Public)", "Classification: NATO RESTRICTED"}
    assert findings.restricted_classification_labels == ["Classification: NATO RESTRICTED"]


def test_analyze_public_labels_are_not_treated_as_restricted():
    doc = DocumentMetadata(
        url="https://example.gov/a.pdf", local_path="/tmp/a.pdf", filetype="pdf",
        raw={"XML:Classification": "Public", "XML:MSIP_Label_9_Name": "Genel"},
    )

    findings = analyze([doc], targets=["example.gov"])

    assert set(findings.classification_labels) == {"Public", "Genel"}
    assert findings.restricted_classification_labels == []
