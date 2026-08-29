from unittest.mock import MagicMock, patch

from metascout.content_scan import visual_signature as vs


def test_detect_visual_signature_returns_none_without_dependency(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    with patch.object(vs, "SIGNATURE_DETECT_AVAILABLE", False):
        assert vs.detect_visual_signature(str(p), "pdf") is None


def test_detect_visual_signature_returns_none_for_unsupported_filetype(tmp_path):
    p = tmp_path / "doc.docx"
    p.write_bytes(b"PK\x03\x04")
    with patch.object(vs, "SIGNATURE_DETECT_AVAILABLE", True):
        assert vs.detect_visual_signature(str(p), "docx") is None


def _mock_pipeline(*, judge_result: bool, masks=None):
    fake_loader = MagicMock()
    fake_loader.get_masks.return_value = masks if masks is not None else ["mask0"]
    fake_extractor = MagicMock()
    fake_extractor.extract.return_value = "labeled_mask"
    fake_cropper = MagicMock()
    fake_cropper.run.return_value = {"0": {"cropped_mask": "cm0"}}
    fake_judger = MagicMock()
    fake_judger.judge.return_value = judge_result
    return fake_loader, fake_extractor, fake_cropper, fake_judger


def test_detect_visual_signature_true_when_a_region_is_judged_signed(tmp_path):
    p = tmp_path / "signed.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    loader, extractor, cropper, judger = _mock_pipeline(judge_result=True)
    with patch.object(vs, "SIGNATURE_DETECT_AVAILABLE", True), \
            patch.object(vs, "Loader", return_value=loader), \
            patch.object(vs, "Extractor", return_value=extractor), \
            patch.object(vs, "Cropper", return_value=cropper), \
            patch.object(vs, "Judger", return_value=judger):
        assert vs.detect_visual_signature(str(p), "pdf") is True


def test_detect_visual_signature_false_when_no_region_is_signed(tmp_path):
    p = tmp_path / "unsigned.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    loader, extractor, cropper, judger = _mock_pipeline(judge_result=False)
    with patch.object(vs, "SIGNATURE_DETECT_AVAILABLE", True), \
            patch.object(vs, "Loader", return_value=loader), \
            patch.object(vs, "Extractor", return_value=extractor), \
            patch.object(vs, "Cropper", return_value=cropper), \
            patch.object(vs, "Judger", return_value=judger):
        assert vs.detect_visual_signature(str(p), "pdf") is False


def test_detect_visual_signature_returns_none_on_runtime_failure(tmp_path):
    # e.g. Ghostscript missing, corrupt file, etc. — degrade to "couldn't
    # confirm" rather than raising and aborting the whole content scan.
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"not a real pdf")
    loader = MagicMock()
    loader.get_masks.side_effect = RuntimeError("gs not found")
    with patch.object(vs, "SIGNATURE_DETECT_AVAILABLE", True), \
            patch.object(vs, "Loader", return_value=loader):
        assert vs.detect_visual_signature(str(p), "pdf") is None


def test_detect_visual_signature_accepts_image_filetypes(tmp_path):
    p = tmp_path / "scan.jpg"
    p.write_bytes(b"\xff\xd8\xff")
    loader, extractor, cropper, judger = _mock_pipeline(judge_result=True)
    with patch.object(vs, "SIGNATURE_DETECT_AVAILABLE", True), \
            patch.object(vs, "Loader", return_value=loader), \
            patch.object(vs, "Extractor", return_value=extractor), \
            patch.object(vs, "Cropper", return_value=cropper), \
            patch.object(vs, "Judger", return_value=judger):
        assert vs.detect_visual_signature(str(p), "jpg") is True
