import zipfile
from unittest.mock import MagicMock, patch

import pytest

from metascout.content_scan import missing_dependencies, scan_document
from metascout.content_scan import pii_patterns as pii
from metascout.content_scan import signature as sig
from metascout.content_scan import text_extract as te

# A checksum-valid TR national ID number, generated to satisfy the real
# algorithm rather than picked at random — see _valid_tc_kimlik.
VALID_TC = "10000000078"
# A well-known Visa test PAN that passes Luhn (used ubiquitously in payment
# test suites — not a real card number).
VALID_CARD = "4111111111111111"
# A real, checksum-valid IBAN shape (mod-97 == 1).
VALID_IBAN = "TR330006100519786457841326"


# ---- validators -----------------------------------------------------------

def test_valid_tc_kimlik_accepts_checksum_valid_number():
    assert pii._valid_tc_kimlik(VALID_TC)


def test_valid_tc_kimlik_rejects_wrong_checksum():
    assert not pii._valid_tc_kimlik("10000000079")


def test_valid_tc_kimlik_rejects_leading_zero():
    assert not pii._valid_tc_kimlik("01234567890")


def test_valid_luhn_accepts_known_test_card():
    assert pii._valid_luhn(VALID_CARD)


def test_valid_luhn_rejects_bad_checksum():
    assert not pii._valid_luhn("4111111111111112")


def test_valid_iban_accepts_checksum_valid_iban():
    assert pii._valid_iban(VALID_IBAN)


def test_valid_iban_rejects_bad_checksum():
    assert not pii._valid_iban("TR330006100519786457841327")


# ---- finders ----------------------------------------------------------------

def test_find_tc_kimlik_filters_out_non_checksum_matches():
    text = f"Kimlik No: {VALID_TC}, sipariş no: 12345678901"
    matches = pii.find_tc_kimlik(text)
    assert [m.raw for m in matches] == [VALID_TC]
    # masked, not shown raw
    assert matches[0].masked == "100******78"


def test_find_credit_cards_masks_to_last_four():
    matches = pii.find_credit_cards(f"Card: {VALID_CARD}")
    assert matches[0].raw == VALID_CARD
    assert matches[0].masked == "*" * 12 + "1111"


def test_find_ibans_masks_middle():
    matches = pii.find_ibans(VALID_IBAN)
    assert matches[0].masked.startswith("TR33")
    assert matches[0].masked.endswith("1326")
    assert "*" in matches[0].masked


def test_find_emails():
    matches = pii.find_emails("Reach me at jane.doe@example.com please")
    assert [m.raw for m in matches] == ["jane.doe@example.com"]


@pytest.mark.skipif(not pii.PHONENUMBERS_AVAILABLE, reason="phonenumbers extra not installed")
def test_find_phones_detects_international_and_local_tr_numbers():
    text = "Call +1 650-253-0000 or locally 0532 123 45 67"
    matches = pii.find_phones(text)
    e164s = {m.masked for m in matches}
    assert "+16502530000" in e164s
    assert "+905321234567" in e164s


def test_find_dob_hints():
    matches = pii.find_dob_hints("Date of Birth: 05/03/1990")
    assert [m.raw for m in matches] == ["05/03/1990"]


def test_find_address_hints():
    matches = pii.find_address_hints("Ships to 123 Main Street, next town")
    assert matches and "Main Street" in matches[0].raw


def test_find_signature_keywords_matches_turkish_dotted_capital_i():
    # Regression: Python's str.lower() maps Turkish "İ" (U+0130) to "i̇"
    # (i + combining dot, U+0307), not plain "i" — so "İmzalayan" would
    # never match the "imzalayan" keyword without the explicit normalize.
    matches = pii.find_signature_keywords("İmzalayan: Ahmet Yılmaz")
    assert "imzalayan" in {m.masked for m in matches}


def test_find_signature_keywords_english():
    matches = pii.find_signature_keywords("This document was digitally signed.")
    assert "digitally signed" in {m.masked for m in matches}


# ---- secret/credential detection --------------------------------------------

def test_mask_middle_does_not_leak_raw_value_when_keep_end_is_zero():
    # Regression: s[-0:] is the whole string in Python (no negative zero),
    # so masking with keep_end=0 used to silently append the raw secret
    # back onto the end of what was supposed to be the masked value.
    masked = pii._mask_middle("AKIAIOSFODNN7EXAMPLE", 4, 0)
    assert masked == "AKIA****************"
    assert "IOSFODNN7EXAMPLE" not in masked


def test_find_secrets_aws_access_key():
    matches = pii.find_secrets("export AWS_KEY=AKIAIOSFODNN7EXAMPLE")
    assert len(matches) == 1
    assert matches[0].category == "secret:AWS Access Key ID"
    assert matches[0].masked == "AKIA****************"
    assert "IOSFODNN7EXAMPLE" not in matches[0].masked


def test_find_secrets_google_api_key():
    key = "AIza" + "Sy0abcdefghijklmnopqrstuvwxyz012345"[:35]
    matches = pii.find_secrets(f"key = {key}")
    assert len(matches) == 1
    assert matches[0].category == "secret:Google API Key"
    assert key not in matches[0].masked


def test_find_secrets_github_pat():
    matches = pii.find_secrets("token: ghp_1234567890abcdefghijklmnopqrstuvwxyz")
    assert matches[0].category == "secret:GitHub Personal Access Token"


def test_find_secrets_private_key_block_never_shows_raw_content():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    matches = pii.find_secrets(text)
    assert len(matches) == 1
    assert matches[0].category == "secret:Private Key Block"
    assert "contents not shown" in matches[0].masked
    assert "MIIEpAIBAAKCAQEA" not in matches[0].masked


def test_find_secrets_db_connection_string_masks_password_only():
    matches = pii.find_secrets("DB_URL=postgres://admin:SuperSecret123@db.internal.example.com:5432/prod")
    assert len(matches) == 1
    masked = matches[0].masked
    assert "SuperSecret123" not in masked
    assert "admin" in masked  # username isn't secret, kept for context
    assert "db.internal.example.com" in masked


def test_find_secrets_jwt():
    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    matches = pii.find_secrets(f"Authorization: Bearer {token}")
    assert matches[0].category == "secret:JWT"
    assert token not in matches[0].masked


def test_find_secrets_no_false_positive_on_ordinary_text():
    assert pii.find_secrets("This is just a normal sentence about a report, nothing secret here.") == []


def test_scan_document_includes_secrets_only_when_requested(tmp_path):
    from metascout.content_scan import scan_document as scan_doc
    p = tmp_path / "notes.txt"
    p.write_text("irrelevant")
    text = "AWS key: AKIAIOSFODNN7EXAMPLE"
    with patch("metascout.content_scan.extract_text", return_value=text), \
            patch("metascout.content_scan.has_pdf_digital_signature", return_value=False):
        no_secrets = scan_doc(str(p), "txt", categories={"tc_kimlik"})
        with_secrets = scan_doc(str(p), "txt", categories={"secrets"})
    assert no_secrets == []
    assert len(with_secrets) == 1
    assert with_secrets[0].category == "secret:AWS Access Key ID"


# ---- text extraction --------------------------------------------------------

def _write_zip(path, files: dict):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def test_extract_text_docx(tmp_path):
    p = tmp_path / "doc.docx"
    _write_zip(p, {
        "word/document.xml": (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>hello world</w:t></w:r></w:p></w:body></w:document>'
        ),
    })
    assert "hello world" in te.extract_text(str(p), "docx")


def test_extract_text_xlsx(tmp_path):
    p = tmp_path / "sheet.xlsx"
    _write_zip(p, {
        "xl/sharedStrings.xml": (
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<si><t>Ad Soyad</t></si></sst>'
        ),
        "xl/worksheets/sheet1.xml": (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData><row><c><v>{VALID_TC}</v></c></row></sheetData></worksheet>'
        ),
    })
    text = te.extract_text(str(p), "xlsx")
    assert "Ad Soyad" in text
    assert VALID_TC in text


def test_extract_text_pptx(tmp_path):
    p = tmp_path / "slides.pptx"
    _write_zip(p, {
        "ppt/slides/slide1.xml": (
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>slide text</a:t></a:r>'
            '</a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
        ),
    })
    assert "slide text" in te.extract_text(str(p), "pptx")


def test_extract_text_odt(tmp_path):
    p = tmp_path / "doc.odt"
    _write_zip(p, {
        "content.xml": (
            '<office:document-content '
            'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            '<office:body><office:text><text:p>odt text</text:p></office:text>'
            '</office:body></office:document-content>'
        ),
    })
    assert "odt text" in te.extract_text(str(p), "odt")


def test_extract_text_legacy_binary_format_returns_empty(tmp_path):
    p = tmp_path / "old.doc"
    p.write_bytes(b"not a real ole file")
    assert te.extract_text(str(p), "doc") == ""


def test_extract_text_corrupt_zip_degrades_to_empty_string(tmp_path):
    p = tmp_path / "broken.docx"
    p.write_bytes(b"not a zip file at all")
    assert te.extract_text(str(p), "docx") == ""


def test_extract_text_pdf_without_pypdf_returns_empty(tmp_path):
    p = tmp_path / "some.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    with patch.object(te, "PYPDF_AVAILABLE", False):
        assert te.extract_text(str(p), "pdf") == ""


def test_extract_text_pdf_uses_pypdf_when_available(tmp_path):
    p = tmp_path / "some.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    fake_page = MagicMock()
    fake_page.extract_text.return_value = f"Kimlik: {VALID_TC}"
    fake_reader = MagicMock()
    fake_reader.is_encrypted = False
    fake_reader.pages = [fake_page]
    with patch.object(te, "PYPDF_AVAILABLE", True), patch.object(te, "PdfReader", return_value=fake_reader):
        text = te.extract_text(str(p), "pdf")
    assert VALID_TC in text


# ---- signature structural check ---------------------------------------------

def test_has_pdf_digital_signature_true_when_sig_field_present(tmp_path):
    p = tmp_path / "signed.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    fake_reader = MagicMock()
    fake_reader.get_fields.return_value = {"sig1": {"/FT": "/Sig"}}
    with patch.object(sig, "PYPDF_AVAILABLE", True), patch.object(sig, "PdfReader", return_value=fake_reader):
        assert sig.has_pdf_digital_signature(str(p)) is True


def test_has_pdf_digital_signature_false_when_no_sig_field(tmp_path):
    p = tmp_path / "unsigned.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    fake_reader = MagicMock()
    fake_reader.get_fields.return_value = {}
    fake_reader.trailer = {"/Root": {}}
    with patch.object(sig, "PYPDF_AVAILABLE", True), patch.object(sig, "PdfReader", return_value=fake_reader):
        assert sig.has_pdf_digital_signature(str(p)) is False


def test_has_pdf_digital_signature_false_without_pypdf(tmp_path):
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    with patch.object(sig, "PYPDF_AVAILABLE", False):
        assert sig.has_pdf_digital_signature(str(p)) is False


# ---- orchestrator: scan_document ---------------------------------------------

def test_scan_document_only_runs_requested_categories(tmp_path):
    p = tmp_path / "doc.txt"
    p.write_text("irrelevant")
    text = f"Kimlik {VALID_TC} email jane@example.com card {VALID_CARD}"
    with patch("metascout.content_scan.extract_text", return_value=text), \
            patch("metascout.content_scan.has_pdf_digital_signature", return_value=False):
        hits = scan_document(str(p), "pdf", categories={"tc_kimlik"})
    categories_found = {h.category for h in hits}
    assert categories_found == {"tc_kimlik"}


def test_scan_document_masks_values_and_never_leaks_raw_tc_kimlik(tmp_path):
    p = tmp_path / "doc.txt"
    p.write_text("irrelevant")
    text = f"Kimlik {VALID_TC}"
    with patch("metascout.content_scan.extract_text", return_value=text), \
            patch("metascout.content_scan.has_pdf_digital_signature", return_value=False):
        hits = scan_document(str(p), "pdf", categories={"tc_kimlik"})
    assert len(hits) == 1
    assert VALID_TC not in hits[0].masked_value
    assert VALID_TC not in hits[0].context


def test_scan_document_checks_pdf_signature_structure_even_with_no_text(tmp_path):
    p = tmp_path / "scanned.pdf"
    p.write_text("irrelevant")
    with patch("metascout.content_scan.extract_text", return_value=""), \
            patch("metascout.content_scan.has_pdf_digital_signature", return_value=True):
        hits = scan_document(str(p), "pdf", categories={"signature"})
    assert len(hits) == 1
    assert hits[0].category == "signature"
    assert "digitally signed" in hits[0].masked_value


def test_scan_document_no_hits_when_text_empty_and_not_pdf(tmp_path):
    p = tmp_path / "doc.docx"
    p.write_text("irrelevant")
    with patch("metascout.content_scan.extract_text", return_value=""):
        hits = scan_document(str(p), "docx", categories=set(["tc_kimlik", "signature"]))
    assert hits == []


def test_missing_dependencies_lists_pypdf_when_unavailable():
    with patch("metascout.content_scan.PYPDF_AVAILABLE", False), \
            patch("metascout.content_scan.PHONENUMBERS_AVAILABLE", True):
        missing = missing_dependencies({"tc_kimlik"})
    assert any("pypdf" in m for m in missing)
    assert not any("phonenumbers" in m for m in missing)


def test_missing_dependencies_lists_phonenumbers_only_when_email_phone_requested():
    with patch("metascout.content_scan.PYPDF_AVAILABLE", True), \
            patch("metascout.content_scan.PHONENUMBERS_AVAILABLE", False):
        assert not missing_dependencies({"tc_kimlik"})
        missing = missing_dependencies({"email_phone"})
    assert any("phonenumbers" in m for m in missing)
