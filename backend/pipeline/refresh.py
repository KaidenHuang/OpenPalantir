"""
文档内容失效传播 —— 指纹比对、图谱回收、重跑生成与 Wiki 刷新

三条约定：
1. 摘要 JSON 里的 content_hash 是源文件指纹，比对它就能判定文档是否变更，不需要额外的失效状态表；
   Wiki 页/实体页各自的 source_hash 幂等，上游一变下游自动重生成。
2. 刷新顺序是「先生成、后回收」：LLM 环节失败时旧图谱与旧摘要保持完整，不会出现删完建不出来。
3. 回收按来源 URI 摘除实体/边上的佐证：被其他文档佐证的实体保留，只有再无来源可证的实体才删除，
   因此重跑一篇文档不会连带丢掉邻居文档贡献的图谱数据。
"""
import os
from typing import Any, Dict, List, Optional

from config.database import SessionLocal
from model_management.model_service import ModelService
from models.source import DocumentSource
from system.logger import logger

# 各阶段组件接口（阶段间只依赖组件服务，不越层摸内部实现）
from document_processing import summary_generator  # 阶段③文档侧 store（后续阶段替换为 summary_generation）


def resolve_file(base_path: str, file_path: str) -> str:
    """把源内相对路径解析为绝对路径，越界直接拒绝"""
    from utils.path_guard import safe_join

    return safe_join(base_path, file_path)


def stale_reason(source_id: str, file_path: str, full_path: str) -> str:
    """返回 ''（无需刷新）/ 'changed'（内容变更）/ 'removed'（源文件已删除）"""
    path = summary_generator.summary_path(source_id, file_path)
    stored = summary_generator.stored_content_hash(path)
    if not stored:
        return ""
    if not os.path.isfile(full_path):
        return "removed"
    if summary_generator.file_content_hash(full_path) != stored:
        return "changed"
    return ""


def recycle_document(datasource: str, keep_hash: str = None) -> Dict[str, int]:
    """回收某文档在图谱中的产出（边 + 无其他佐证的实体）

    keep_hash（代际回收）：保留本来源新代佐证（URI@keep_hash），
    摘除旧代与历史遗留纯 URI 条目——供「抽取先于回收」的刷新顺序使用。
    """
    from knowledge_graph.recycle import recycle_datasource
    recycled = recycle_datasource(datasource, keep_hash=keep_hash)
    logger.info(f"[refresh] 图谱回收 {datasource}: {recycled}")
    return recycled


def remove_document(source_id: str, file_path: str) -> Dict[str, Any]:
    """源文件已删除：回收图谱产出、删除摘要与对应 Wiki 页"""
    datasource = summary_generator.datasource_for(source_id, file_path)
    recycled = recycle_document(datasource)
    summary_generator.remove(source_id, file_path)

    from wiki.wiki_service import wiki_service
    removed_pages = wiki_service.remove_pages_by_datasource(datasource)
    wiki_service.prune_orphans()
    logger.info(f"[refresh] 文档删除已传播: {datasource}, 页面 {removed_pages}")
    return {"status": "removed", "datasource": datasource,
            "recycled": recycled, "removed_pages": removed_pages}


def refresh_document(source_id: str, file_path: str, *, force: bool = False,
                     domain: str = "general", parallelism: int = 8) -> Dict[str, Any]:
    """重跑一篇文档：摘要 → 抽取（新代佐证）→ 旧代回收 → Wiki 刷新

    回收后立于抽取：LLM/落库失败时旧图谱数据完好（失败即任务失败，
    下次成功刷新才摘除旧代），不再是「回收后抽取失败 → 图谱被清空」的丢数据顺序。
    代际佐证（URI@content_hash）保证抽取先写入的新代产出不被随后的回收误伤。
    """
    from wiki.wiki_service import wiki_service

    db = SessionLocal()
    try:
        from source_registry.document.registry import document_source_registry
        base_path = document_source_registry.root_path(db, source_id, quiet=True)
    finally:
        db.close()
    if not base_path:
        raise FileNotFoundError(f"文档源不存在或已删除: {source_id}")
    full_path = resolve_file(base_path, file_path)
    datasource = summary_generator.datasource_for(source_id, file_path)

    reason = stale_reason(source_id, file_path, full_path)
    if reason == "removed":
        return remove_document(source_id, file_path)
    if reason == "" and not force:
        return {"status": "skipped", "datasource": datasource, "reason": "未变更"}

    # 1) 先生成摘要 —— 失败即抛出，旧数据保持原样
    summary = summary_generator.generate(full_path)
    summary_path = summary_generator.save(source_id, file_path, summary)
    new_hash = summary.get("content_hash", "")

    # 2) 重新抽取（LLM）—— 新产出带新代佐证（URI@content_hash）落库，失败即抛，
    #    此时旧图谱数据未动
    extracted = _extract(summary_path, datasource, domain, parallelism,
                         evidence_hash=new_hash)

    # 3) 抽取成功后回收：只摘本来源旧代佐证，刚写入的新代佐证保留
    recycled = recycle_document(datasource, keep_hash=new_hash)

    # 4) Wiki 传播：本页重生成 + 主题/实体页按指纹重算 + 清理孤儿页
    document_page = wiki_service.generate_document_page(datasource)
    topic_pages = wiki_service.refresh_topics()
    entity_pages = wiki_service.generate_entity_pages()
    pruned = wiki_service.prune_orphans()

    result = {
        "status": "refreshed",
        "datasource": datasource,
        "reason": reason or "forced",
        "content_hash": summary.get("content_hash", ""),
        "recycled": recycled,
        "entity_count": extracted.get("entity_count", 0),
        "relationship_count": extracted.get("relationship_count", 0),
        "document_page": document_page.get("page_id") if document_page else None,
        "topic_pages": len(topic_pages),
        "entity_pages": len(entity_pages),
        "pruned_pages": pruned,
    }
    logger.info(f"[refresh] 文档刷新完成: {datasource}, 实体 {result['entity_count']}")
    return result


def scan_stale(limit: Optional[int] = None) -> List[Dict[str, str]]:
    """扫描全部已生成摘要的文档，返回需要刷新的条目（供文件监听使用）

    以摘要文件为索引，只关心「曾经处理过」的文件：新上传的文件仍需显式生成摘要。
    """
    items: List[Dict[str, str]] = []
    for summary_file in summary_generator.iter_doc_summaries():
        source_id, file_path = summary_generator.parse_datasource(
            summary_generator.datasource_from_summary_path(summary_file))
        if not source_id or not file_path:
            continue
        base_path = _source_base_path(source_id, quiet=True)
        if not base_path:
            continue
        full_path = resolve_file(base_path, file_path)
        reason = stale_reason(source_id, file_path, full_path)
        if reason:
            items.append({"source_id": source_id, "file_path": file_path,
                          "full_path": full_path, "reason": reason})
        if limit and len(items) >= limit:
            break
    return items


def _source_base_path(source_id: str, quiet: bool = False) -> str:
    """文档源的本地根路径；源不存在或已删除时返回空串"""
    from source_registry.document.registry import document_source_registry

    db = SessionLocal()
    try:
        try:
            source = document_source_registry.require_alive(db, source_id)
        except ValueError:
            if quiet:
                return ""
            raise
        if source.source_type != "local":
            if quiet:
                return ""
            raise ValueError(f"仅本地文档源支持自动刷新: {source_id}")
        return source.path
    finally:
        db.close()


def _extract(summary_path: str, datasource: str, domain: str,
             parallelism: int, evidence_hash: str = None) -> Dict[str, Any]:
    """按可用模型重新抽取实体关系（evidence_hash → 佐证代际标记）"""
    from source_management.source_service import SourceService

    db = SessionLocal()
    try:
        model_config = ModelService.get_available_model(db)
    finally:
        db.close()
    if not model_config:
        raise RuntimeError("没有可用的模型，无法重新抽取实体关系")

    service = SourceService(model_config)
    result = service.extract_from_summary(
        summary_path=summary_path, datasource=datasource,
        parallelism=parallelism, domain=domain, evidence_hash=evidence_hash,
    )

    # 零实体守卫：摘要结构存在却抽到 0 实体，几乎必然是 LLM 全部调用失败
    # （call_json 失败返回 None → enhancer 只能得到空结果，异常已被吞在客户端层）。
    # 静默成功 = 任务看着没事、图谱实际没有新产出 —— 按失败处理。
    # 注：本顺序下回收后置，此失败不会清掉旧图谱数据。
    entity_count = (result or {}).get("entity_count", 0)
    if entity_count == 0:
        raise RuntimeError(
            "重新抽取得到 0 个实体（大概率 LLM 不可用），刷新按失败处理；"
            "旧图谱产出未回收，请检查模型配置后重跑"
        )
    return result
