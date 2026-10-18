"""
摘要生成与存放 —— PageIndex 分派 + 源文件内容指纹

摘要落在 data/summaries/DOC/{source_id}/{文件相对路径}.json，
JSON 里的 content_hash 是生成当时源文件的 MD5。
文档失效判定（内容是否变更、文件是否已删除）与自动刷新都以它为依据。
"""
import hashlib
import json
import os
from typing import Tuple

from system.logger import logger

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMMARY_ROOT = os.path.join(BACKEND_DIR, "data", "summaries")

EXTENSIONS = (".pdf", ".md", ".txt", ".docx")
DOC_SCHEME = "DOC://"


def datasource_for(source_id: str, file_path: str) -> str:
    """文档的来源 URI —— 图谱实体/边与 Wiki 页都以它标识产出来源"""
    return f"{DOC_SCHEME}{source_id}/{file_path}"


def parse_datasource(datasource: str) -> Tuple[str, str]:
    """DOC://{source_id}/{文件相对路径} → (source_id, file_path)；非文档来源返回空"""
    if not datasource.startswith(DOC_SCHEME):
        return "", ""
    source_id, _, file_path = datasource[len(DOC_SCHEME):].partition("/")
    return source_id, file_path


def datasource_from_summary_path(path: str) -> str:
    """摘要文件路径 → 对应文档的来源 URI"""
    norm = os.path.abspath(path).replace("\\", "/")
    root = os.path.join(SUMMARY_ROOT, "DOC").replace("\\", "/") + "/"
    if not norm.startswith(root):
        return ""
    source_id, _, rest = norm[len(root):].partition("/")
    if not rest:
        return ""
    return datasource_for(source_id, rest.removesuffix(".json"))


def is_supported(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in EXTENSIONS


def file_content_hash(path: str) -> str:
    """源文件内容指纹"""
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def summary_path(source_id: str, file_path: str) -> str:
    """某文档源下某文件的摘要 JSON 路径"""
    return os.path.join(SUMMARY_ROOT, "DOC", source_id, f"{file_path}.json")


def source_summary_dir(source_id: str) -> str:
    """某文档源的全部摘要所在目录"""
    return os.path.join(SUMMARY_ROOT, "DOC", source_id)


def stored_content_hash(path: str) -> str:
    """摘要文件中记录的源文件指纹；摘要不存在或损坏时为空"""
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("content_hash", "")
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"[summary] 摘要读取失败 {path}: {e}")
        return ""


def generate(full_path: str) -> dict:
    """按扩展名分派 PageIndex 生成摘要，并记录源文件指纹"""
    from pageindex import (
        generate_pageindex_docx,
        generate_pageindex_md,
        generate_pageindex_pdf,
        generate_pageindex_txt,
    )

    ext = os.path.splitext(full_path)[1].lower()
    generators = {
        ".pdf": generate_pageindex_pdf,
        ".md": generate_pageindex_md,
        ".txt": generate_pageindex_txt,
        ".docx": generate_pageindex_docx,
    }
    if ext not in generators:
        raise ValueError(f"不支持的文件类型: {ext}")

    result = generators[ext](full_path)
    result["content_hash"] = file_content_hash(full_path)
    return result


def save(source_id: str, file_path: str, data: dict) -> str:
    """写入摘要文件，返回其绝对路径"""
    path = summary_path(source_id, file_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"[summary] 摘要已保存: {path}")
    return path


def remove(source_id: str, file_path: str) -> bool:
    """删除摘要文件（源文件已不存在时的清理）"""
    path = summary_path(source_id, file_path)
    if not os.path.isfile(path):
        return False
    os.remove(path)
    logger.info(f"[summary] 摘要已删除: {path}")
    return True


def iter_doc_summaries() -> list:
    """遍历全部文档摘要文件（含源内子目录），供失效扫描与 Wiki 批量生成使用"""
    from glob import glob
    return sorted(glob(os.path.join(SUMMARY_ROOT, "DOC", "**", "*.json"), recursive=True))
