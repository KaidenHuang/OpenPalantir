"""PDF 插图（pdf_images）单元测试 —— 配置挡位、面积过滤、占位/OCR、扫描件判定"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(BASE, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from content_extraction.document import pdf_images        # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def clean_env(monkeypatch):
    for key in ("DOC_IMAGE_MODE", "DOC_OCR_LANG", "DOC_IMAGES_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


# ── 配置 ────────────────────────────────────────────────────

def test_defaults(clean_env):
    settings = pdf_images.image_settings()
    assert settings.mode == "placeholder"
    assert settings.lang == "chi_sim+eng"
    assert settings.enabled is True


def test_ocr_mode_and_language_override(clean_env):
    clean_env.setenv("DOC_IMAGE_MODE", "OCR")
    clean_env.setenv("DOC_OCR_LANG", "eng")
    settings = pdf_images.image_settings()
    assert settings.mode == "ocr"
    assert settings.lang == "eng"


def test_images_disabled(clean_env):
    clean_env.setenv("DOC_IMAGES_ENABLED", "0")
    assert pdf_images.image_settings().enabled is False


def test_vision_mode_is_rejected(clean_env):
    clean_env.setenv("DOC_IMAGE_MODE", "vision")
    with pytest.raises(ValueError, match="尚未实现"):
        pdf_images.image_settings()


def test_unknown_mode_is_rejected(clean_env):
    clean_env.setenv("DOC_IMAGE_MODE", "describe")
    with pytest.raises(ValueError, match="取值无效"):
        pdf_images.image_settings()


# ── 单框替换 ────────────────────────────────────────────────

def _settings(mode="placeholder"):
    return pdf_images.ImageSettings(mode=mode, lang="eng", enabled=True)


def test_formula_box_is_dropped():
    assert pdf_images.image_replacement("formula", 0.5, "a.png", "b.png", _settings()) == ""


def test_tiny_picture_is_dropped():
    assert pdf_images.image_replacement("picture", 0.01, "a.png", "b.png", _settings()) == ""


def test_missing_file_is_dropped():
    assert pdf_images.image_replacement("picture", 0.4, None, None, _settings()) == ""


def test_placeholder_points_at_final_path():
    ref = pdf_images.image_replacement("picture", 0.4, "tmp/a.png", "final/a.png",
                                       _settings())
    assert ref == f"![]({pdf_images.public_ref('final/a.png')})"
    assert "tmp" not in ref


def test_ocr_text_replaces_placeholder(monkeypatch):
    monkeypatch.setattr(pdf_images, "ocr_available", lambda: True)
    monkeypatch.setattr(pdf_images, "ocr_image", lambda path, lang: "季度销售额 120")
    ref = pdf_images.image_replacement("picture", 0.4, "a.png", "b.png", _settings("ocr"))
    assert ref == "> 图内文字：季度销售额 120"


def test_ocr_empty_result_falls_back_to_placeholder(monkeypatch):
    monkeypatch.setattr(pdf_images, "ocr_available", lambda: True)
    monkeypatch.setattr(pdf_images, "ocr_image", lambda path, lang: "")
    ref = pdf_images.image_replacement("picture", 0.4, "a.png", "final/b.png", _settings("ocr"))
    assert ref.startswith("![](")


def test_ocr_without_tesseract_falls_back_to_placeholder(monkeypatch):
    monkeypatch.setattr(pdf_images, "ocr_available", lambda: False)
    ref = pdf_images.image_replacement("picture", 0.4, "a.png", "final/b.png", _settings("ocr"))
    assert ref.startswith("![](")


# ── OCR 文本清洗 ────────────────────────────────────────────

def test_ocr_image_collapses_whitespace_and_truncates(tmp_path, monkeypatch):
    from PIL import Image

    path = tmp_path / "a.png"
    Image.new("RGB", (20, 20), "white").save(path)

    import pytesseract
    long_text = "行一\n\n  行二\t" + "字" * (pdf_images.MAX_IMAGE_TEXT_CHARS + 50)
    monkeypatch.setattr(pytesseract, "image_to_string", lambda image, lang: long_text)

    text = pdf_images.ocr_image(str(path), "eng")
    assert "\n" not in text and "\t" not in text
    assert len(text) == pdf_images.MAX_IMAGE_TEXT_CHARS


def test_ocr_image_failure_returns_empty(tmp_path, monkeypatch):
    import pytesseract

    def boom(image, lang):
        raise RuntimeError("tesseract not found")

    monkeypatch.setattr(pytesseract, "image_to_string", boom)
    from PIL import Image
    path = tmp_path / "a.png"
    Image.new("RGB", (20, 20), "white").save(path)
    assert pdf_images.ocr_image(str(path), "eng") == ""


# ── 扫描件判定 ──────────────────────────────────────────────

def test_empty_text_is_scanned():
    assert pdf_images.is_scanned("   \n\n ", 3) is True


def test_low_chars_per_page_is_scanned():
    assert pdf_images.is_scanned("短" * 50, 3) is True


def test_normal_text_is_not_scanned():
    assert pdf_images.is_scanned("正文" * 500, 2) is False


def test_zero_page_count_is_not_scanned():
    assert pdf_images.is_scanned("", 0) is False


# ── 文件定位 ────────────────────────────────────────────────

def test_find_image_file_matches_box_suffix(tmp_path):
    (tmp_path / "report.pdf-0002-07.png").write_bytes(b"x")
    (tmp_path / "report.pdf-0002-17.png").write_bytes(b"x")
    found = pdf_images.find_image_file(str(tmp_path), 2, 7)
    assert found and os.path.basename(found) == "report.pdf-0002-07.png"


def test_find_image_file_returns_none_when_absent(tmp_path):
    assert pdf_images.find_image_file(str(tmp_path), 2, 7) is None
