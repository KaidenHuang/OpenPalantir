"""格式转换器注册表 —— 新格式（图片/音频/视频）在此注册自己的提取函数

这里登记的是「支持的扩展名」的唯一事实源：① 的文件枚举（scanner）、③ 的
`is_supported`、`GET /api/sources/formats` 都读它，所以只登记真能提取的格式。
旧版 .xls 二进制格式不进注册表（否则会被当成支持格式放进清单），
由 extract_content 给出「另存为 xlsx」的可读错误。
"""
from .csv_converter import extract_csv
from .docx_converter import extract_docx
from .pdf_converter import extract_pdf
from .plain_converter import extract_md, extract_txt
from .pptx_converter import extract_pptx
from .xlsx_converter import extract_xlsx


_CONVERTERS = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".pptx": extract_pptx,
    ".md": extract_md,
    ".txt": extract_txt,
    ".xlsx": extract_xlsx,
    ".xlsm": extract_xlsx,
    ".csv": extract_csv,
    ".tsv": extract_csv,
}

# 认得但明确不支持的扩展名：给可读原因，不静默跳过
_LEGACY_HINTS = {
    ".xls": "旧版 .xls 二进制格式不支持，请先另存为 .xlsx",
}


def get_converter(ext: str):
    """按扩展名（含点、小写）取转换器；未注册返回 None"""
    return _CONVERTERS.get(ext.lower())


def supported_extensions() -> tuple:
    return tuple(sorted(_CONVERTERS))


def legacy_hint(ext: str) -> str:
    """明确不支持的扩展名给一句可读提示；未知扩展名返回空串"""
    return _LEGACY_HINTS.get(ext.lower(), "")
