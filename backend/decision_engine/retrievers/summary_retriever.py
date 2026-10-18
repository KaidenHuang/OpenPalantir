"""摘要检索 — 文档摘要树 / 数据库概要 JSON 的证据检索（唯一 module）

原 BaseRetriever(ABC) + Document/Database 两个同形态实现 + 0 调用的 GraphRetriever，
合并为本 module：打分/UUID 提取/glob 共享为函数，对外接口直接收关键词集合与领域标签
（取代已删除的 AnalyzedQuery 宽假契约）。embedding 不可用时按关键词重排。
"""
import json
import os
from glob import glob
from typing import List

from system.logger import logger
from decision_engine.contracts import RawEvidence
from decision_engine.retrievers.embedding_utils import hybrid_rank

DATA_SUMMARIES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "summaries")


def calc_score(text: str, keywords: set) -> float:
    """关键词命中率打分：命中数 / 关键词总数"""
    if not keywords:
        return 0.0
    text_lower = text.lower()
    matches = sum(1 for kw in keywords if kw.lower() in text_lower)
    return matches / len(keywords) if matches > 0 else 0.0


def extract_uuid_from_path(file_path: str, resource_type: str) -> str:
    """从 summaries 路径中截取 `data/summaries/{resource_type}/{uuid}/x.json` 的 uuid 段"""
    parts = file_path.replace("\\", "/").split("/")
    try:
        idx = parts.index(resource_type)
        return parts[idx + 1] if idx + 1 < len(parts) else ""
    except (ValueError, IndexError):
        return ""


def glob_summary_files(resource_dir: str) -> List[str]:
    """列出某资源类型目录下全部摘要 JSON"""
    summaries_dir = os.path.abspath(DATA_SUMMARIES_DIR)
    return glob(os.path.join(summaries_dir, resource_dir, "*", "*.json"))


# ── 文档摘要检索 ──────────────────────────────────────────────

def search_document_summaries(keywords: set) -> List[RawEvidence]:
    """检索文档摘要 DOC://*.json：关键词命中 + embedding 语义混合重排"""
    results: List[RawEvidence] = []
    for file_path in glob_summary_files("DOC"):
        try:
            results.extend(_search_document_file(file_path, keywords))
        except Exception as e:
            logger.warning(f"[retriever][document] error reading {file_path}: {e}")

    results = _hybrid_rerank(keywords, results)
    logger.info(f"[retriever][document] 文档摘要匹配到 {len(results)} 条相关内容")
    return results


def _hybrid_rerank(keywords: set, results: List[RawEvidence]) -> List[RawEvidence]:
    """关键词分 + embedding 语义分混合重排；embedding 不可用时按原分排序"""
    if not results:
        return results
    query_text = " ".join(sorted(keywords))

    def text_of(ev: RawEvidence) -> str:
        content = ev.content or {}
        return f"{content.get('title', '')} {content.get('doc_description') or content.get('summary', '')}"

    return hybrid_rank(query_text, results, text_of,
                       lambda ev: ev.relevance_score, top_k=20)


def _search_document_file(file_path: str, keywords: set) -> List[RawEvidence]:
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results: List[RawEvidence] = []
    doc_name = data.get("doc_name", os.path.basename(file_path))
    doc_desc = data.get("doc_description", "")

    source_uuid = extract_uuid_from_path(file_path, "DOC")

    # 从 JSON 文件名还原原始文档名（去掉 .json 后缀，保留 .txt 等原始扩展名）
    json_filename = os.path.basename(file_path)
    original_filename = json_filename[:-5] if json_filename.endswith(".json") else json_filename

    score = calc_score(doc_desc, keywords)
    if score > 0:
        doc_datasource = f"DOC://{source_uuid}/{original_filename}" if source_uuid else ""
        results.append(RawEvidence(
            source_type="document_summary",
            source_id=doc_name,
            content={"doc_name": doc_name, "doc_description": doc_desc},
            relevance_score=score,
            metadata={"doc_name": doc_name, "type": "doc_description",
                      "source_uuid": source_uuid, "datasource": doc_datasource},
        ))

    for node in data.get("structure", []):
        _walk_doc_nodes(node, doc_name, keywords, results, source_uuid=source_uuid,
                        original_filename=original_filename)

    return results


def _walk_doc_nodes(node: dict, doc_name: str, keywords: set, results: List[RawEvidence],
                    depth: int = 0, source_uuid: str = "", original_filename: str = ""):
    if depth > 10:
        return
    title = node.get("title", "")
    summary = node.get("summary", "")

    score = calc_score(summary, keywords)
    if score > 0:
        doc_datasource = f"DOC://{source_uuid}/{original_filename}" if source_uuid else ""
        results.append(RawEvidence(
            source_type="document_summary",
            source_id=f"{doc_name}/{title}",
            content={"title": title, "node_id": node.get("node_id", ""),
                     "line_num": node.get("line_num", ""), "summary": summary},
            relevance_score=score,
            metadata={"doc_name": doc_name, "title": title, "node_id": node.get("node_id", ""),
                      "source_uuid": source_uuid, "datasource": doc_datasource},
        ))

    for child in node.get("nodes", []):
        _walk_doc_nodes(child, doc_name, keywords, results, depth + 1,
                        source_uuid, original_filename)


# ── 数据库概要检索 ────────────────────────────────────────────

def search_database_summaries(keywords: set, domain: str = "") -> List[RawEvidence]:
    """检索数据库概要 DBS://*.json：关键词命中；domain 命中 business_domain 可提权"""
    results: List[RawEvidence] = []
    for file_path in glob_summary_files("DBS"):
        try:
            results.extend(_search_database_file(file_path, keywords, domain))
        except Exception as e:
            logger.warning(f"[retriever][database] error reading {file_path}: {e}")

    logger.info(f"[retriever][database] 数据库概要匹配到 {len(results)} 条相关内容")
    return results


def _search_database_file(file_path: str, keywords: set, domain: str) -> List[RawEvidence]:
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results: List[RawEvidence] = []
    business_domain = data.get("business_domain", "")
    db_name = data.get("db_name", "")

    source_uuid = extract_uuid_from_path(file_path, "DBS")

    if domain and business_domain and domain in business_domain:
        db_datasource = f"DBS://{source_uuid}/{db_name}" if source_uuid and db_name else ""
        results.append(RawEvidence(
            source_type="database_summary",
            source_id=db_name or os.path.basename(file_path),
            content={"db_name": db_name, "db_description": data.get("db_description", ""),
                     "business_domain": business_domain},
            relevance_score=0.8,
            metadata={"business_domain": business_domain, "source_uuid": source_uuid,
                      "db_name": db_name, "datasource": db_datasource},
        ))

    for node in data.get("structure", []):
        _walk_db_tables(node, keywords, results, source_uuid, db_name)

    return results


def _walk_db_tables(node: dict, keywords: set, results: List[RawEvidence],
                    source_uuid: str = "", db_name: str = ""):
    table_name = node.get("table_name", "")
    summary = node.get("summary", "")
    entity_type = node.get("entity_type", "")

    search_text = f"{table_name} {summary} {entity_type}"
    score = calc_score(search_text, keywords)
    if score > 0:
        table_datasource = f"DBS://{source_uuid}/{db_name}/{table_name}" if source_uuid and db_name else ""
        results.append(RawEvidence(
            source_type="database_summary",
            source_id=table_name,
            content={"table_name": table_name, "description": node.get("description", ""),
                     "summary": summary, "entity_type": entity_type,
                     "keys": node.get("keys", [])},
            relevance_score=score,
            metadata={"table": table_name, "entity_type": entity_type,
                      "source_uuid": source_uuid, "db_name": db_name,
                      "datasource": table_datasource},
        ))
