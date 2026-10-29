"""PDF 插图 —— 落盘、占位 / OCR 两挡文本化、扫描件判定与整页 OCR

图片与摘要同根同键存放（`data/summaries/images/{source_id}/{相对路径}.images/`），
但不混进 `DOC/{source_id}/` 目录树：源「有产出」判定只数摘要目录，图片放平级
子树才不会在源文件删净后让该源看起来「还有产出」。

layout(GNN) 路径不支持 `image_size_limit`，这里按 bbox 面积占比自己做小图标过滤；
单文件图片个数不设上限。
"""
import io
import os
import shutil
from dataclasses import dataclass
from typing import List, Optional

from system.logger import logger

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IMAGE_DPI = 150
IMAGE_SIZE_LIMIT = 0.05       # 小于页面面积 5% 的图视为图标，不渲染
MAX_IMAGE_TEXT_CHARS = 500    # 单图 OCR/描述文本上限
SCAN_DPI = 200
SCAN_CHARS_PER_PAGE = 30      # 字符/页均值低于此值视为扫描件

MODE_PLACEHOLDER = "placeholder"
MODE_OCR = "ocr"

SCAN_ERROR = (
    "PDF 无法提取出文本（疑似扫描件）。"
    "安装 Tesseract + chi_sim 语言包后重试（插图内文字另需 DOC_IMAGE_MODE=ocr），"
    "或改用文字版 PDF"
)

_ocr_available_cache: Optional[bool] = None


@dataclass(frozen=True)
class ImageSettings:
    mode: str
    lang: str
    enabled: bool


def image_settings() -> ImageSettings:
    """读取 DOC_IMAGE_MODE / DOC_OCR_LANG / DOC_IMAGES_ENABLED（唯一入口）"""
    mode = (os.getenv("DOC_IMAGE_MODE") or MODE_PLACEHOLDER).strip().lower()
    if mode == "vision":
        raise ValueError("DOC_IMAGE_MODE=vision 尚未实现，请使用 placeholder 或 ocr")
    if mode not in (MODE_PLACEHOLDER, MODE_OCR):
        raise ValueError(f"DOC_IMAGE_MODE 取值无效: {mode}（可选 placeholder / ocr）")
    lang = (os.getenv("DOC_OCR_LANG") or "chi_sim+eng").strip() or "chi_sim+eng"
    raw_enabled = (os.getenv("DOC_IMAGES_ENABLED") or "1").strip().lower()
    enabled = raw_enabled not in ("0", "false", "no", "off")
    return ImageSettings(mode=mode, lang=lang, enabled=enabled)


def ocr_available() -> bool:
    """tesseract 可执行文件是否可用（结果缓存；测试可 monkeypatch）"""
    global _ocr_available_cache
    if _ocr_available_cache is None:
        _ocr_available_cache = shutil.which("tesseract") is not None
    return _ocr_available_cache


def ocr_image(path: str, lang: str) -> str:
    """单图 OCR → 一行文本；失败返回空串（调用方回退占位）"""
    try:
        import pytesseract
        from PIL import Image

        with Image.open(path) as image:
            text = pytesseract.image_to_string(image, lang=lang)
    except Exception as exc:
        logger.warning(f"[pdf_images] 图片 OCR 失败 {path}: {exc}")
        return ""
    return " ".join(text.split())[:MAX_IMAGE_TEXT_CHARS]


def ocr_pdf_pages(doc, lang: str) -> List[str]:
    """扫描件整页 OCR：逐页渲染成图片后识别，返回每页文本（失败页为空串）"""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(f"OCR 依赖不可用: {exc}") from exc

    texts: List[str] = []
    for page in doc:
        try:
            pix = page.get_pixmap(dpi=SCAN_DPI)
            with Image.open(io.BytesIO(pix.tobytes("png"))) as image:
                texts.append(pytesseract.image_to_string(image, lang=lang).strip())
        except Exception as exc:
            logger.warning(f"[pdf_images] 第 {page.number + 1} 页 OCR 失败: {exc}")
            texts.append("")
    return texts


def is_scanned(full_text: str, page_count: int) -> bool:
    """全文为空或字符/页均值过低 → 视为扫描件"""
    if page_count <= 0:
        return False
    if not full_text.strip():
        return True
    return len(full_text) / page_count < SCAN_CHARS_PER_PAGE


def area_ratio(box, page_layout) -> float:
    """表格/图片框面积占页面面积的比例"""
    page_area = max(page_layout.width * page_layout.height, 1.0)
    box_area = max((box.x1 - box.x0) * (box.y1 - box.y0), 0.0)
    return box_area / page_area


def find_image_file(tmp_dir: str, page_number: int, box_index: int) -> Optional[str]:
    """按库生成的命名后缀定位图片文件（文件名由 utils.md_path 做过 basename）"""
    if not os.path.isdir(tmp_dir):
        return None
    suffix = f"-{page_number:04d}-{box_index:02d}.png"
    for name in sorted(os.listdir(tmp_dir)):
        if name.endswith(suffix):
            return os.path.join(tmp_dir, name)
    return None


def public_ref(path: str) -> str:
    """图片在 Markdown 里的引用：优先给相对 backend 的 POSIX 路径，跨盘符退回绝对路径"""
    try:
        rel = os.path.relpath(path, BACKEND_DIR)
    except ValueError:      # Windows 跨盘符无法求相对路径
        return os.path.abspath(path).replace("\\", "/")
    rel = rel.replace("\\", "/")
    return path.replace("\\", "/") if rel.startswith("../") else rel


def image_replacement(box_class: str, ratio: float, image_file: Optional[str],
                      final_file: Optional[str], settings: ImageSettings) -> str:
    """一个图片框在 Markdown 里的替换文本；空串表示丢弃该引用

    OCR 读 tmp 里的原图，占位引用指向 rename 之后的最终路径。
    """
    if box_class == "formula":
        return ""
    if ratio < IMAGE_SIZE_LIMIT or not image_file or not final_file:
        return ""
    if settings.mode == MODE_OCR and ocr_available():
        text = ocr_image(image_file, settings.lang)
        if text:
            return f"> 图内文字：{text}"
    return f"![]({public_ref(final_file)})"
