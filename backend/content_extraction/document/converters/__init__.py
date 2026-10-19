"""格式转换器注册表 —— 新格式（图片/PPT/音频/视频）在此注册自己的提取函数"""
from .docx_converter import extract_docx
from .pdf_converter import extract_pdf
from .plain_converter import extract_md, extract_txt


_CONVERTERS = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".md": extract_md,
    ".txt": extract_txt,
}


def get_converter(ext: str):
    """按扩展名（含点、小写）取转换器；未注册返回 None"""
    return _CONVERTERS.get(ext.lower())


def supported_extensions() -> tuple:
    return tuple(sorted(_CONVERTERS))
