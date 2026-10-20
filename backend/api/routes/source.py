"""文档源路由 —— HTTP 层薄壳，数据访问在 source_registry，产物读取在 summary_generation"""
import json
import os
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from config.database import get_db
from summary_generation.document import store as summary_generator
from model_management.model_service import ModelService
from source_registry.document.registry import document_source_registry
from source_registry.document.scanner import browse_directory, list_supported_files
from system.logger import logger
from task_management.handlers import (DocumentBatchExtractHandler,
                                      DocumentBatchSummaryHandler,
                                      DocumentRefreshHandler,
                                      DocumentSummaryHandler)

router = APIRouter()


def _source_dict(s) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "path": s.path,
        "source_type": s.source_type,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "is_deleted": s.is_deleted,
        "deleted_at": s.deleted_at.isoformat() if s.deleted_at else None,
    }


def _bind_output_check() -> None:
    """删除判定需要在启动时注入（产出目录是否有内容）"""
    document_source_registry.bind_output_check(
        lambda source_id: (os.path.isdir(summary_generator.source_summary_dir(source_id))
                           and bool(os.listdir(summary_generator.source_summary_dir(source_id))))
    )


_bind_output_check()


@router.post("/sources")
def create_source(data: dict = Body(...), db: Session = Depends(get_db)):
    """创建文档源（本地路径或S3 URI）"""
    try:
        try:
            source = document_source_registry.create(
                db, data.get("name", ""), data.get("path", ""),
                data.get("source_type", "local"))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"status": "success", "source": _source_dict(source)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建文档源失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sources")
def list_sources(include_deleted: bool = False, db: Session = Depends(get_db)):
    """列出所有文档源"""
    try:
        sources = document_source_registry.list(db, include_deleted=include_deleted)
        return {"status": "success", "sources": [_source_dict(s) for s in sources]}
    except Exception as e:
        logger.error(f"获取文档源列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sources/formats")
def list_document_formats():
    """文档侧可解析的扩展名 —— 取自内容提取注册表，前端与外部脚本据此筛选文件"""
    try:
        from content_extraction.document.converters import supported_extensions

        return {"status": "success", "formats": list(supported_extensions())}
    except Exception as e:
        logger.error(f"获取支持的文件类型失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, db: Session = Depends(get_db)):
    """删除文档源。无提取数据时直接删除，有数据时标记删除"""
    try:
        deleted = document_source_registry.delete(db, source_id)
        return {"status": "success", "result": True, "deleted": deleted}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"删除文档源失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sources/{source_id}/restore")
def restore_source(source_id: str, db: Session = Depends(get_db)):
    """恢复已删除的文档源"""
    try:
        document_source_registry.restore(db, source_id)
        return {"status": "success", "result": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"恢复文档源失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sources/{source_id}/browse")
def browse_source(source_id: str, prefix: str = "", db: Session = Depends(get_db)):
    """浏览文档源目录（列出文件+子目录）"""
    try:
        source = document_source_registry.require_alive(db, source_id)
        if source.source_type != "local":
            raise HTTPException(status_code=400, detail="仅支持本地文件系统浏览")
        try:
            result = browse_directory(source.path, prefix)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except NotADirectoryError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"status": "success", "source_id": source_id, **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"浏览文档源失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


def _validated_files(data: dict) -> Optional[List[str]]:
    """批量 payload 的 files 校验：None/缺省 = 全源；空数组 = 400 拒绝（防误提交全空任务）"""
    files = data.get("files")
    if files is None:
        return None
    if not isinstance(files, list) or any(not isinstance(f, str) or not f.strip() for f in files):
        raise HTTPException(status_code=400, detail="files 必须为非空字符串数组，或省略该字段表示全源")
    if not files:
        raise HTTPException(status_code=400, detail="files 不能为空数组；省略该字段表示全源处理")
    return [f.replace("\\", "/").strip() for f in files]


def _require_model(db: Session) -> dict:
    """LLM 环节前置检查：批量任务应在提交而非执行 5 分钟后才发现模型不可用"""
    model_config = ModelService.get_available_model(db)
    if not model_config:
        raise HTTPException(status_code=503, detail="没有可用的模型，请先在模型管理中启用一个模型")
    return model_config


@router.post("/sources/{source_id}/summarize")
def summarize_file(source_id: str, data: dict = Body(...), db: Session = Depends(get_db)):
    """为源中的某个文件生成概要（通过异步任务执行）"""
    try:
        file_path = data.get("file", "").strip()
        if not file_path:
            raise HTTPException(status_code=400, detail="file is required")

        source = document_source_registry.require(db, source_id)
        try:
            full_path = document_source_registry.resolve_file(source.path, file_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        if not os.path.isfile(full_path):
            raise HTTPException(status_code=400, detail="文件不存在")
        if not summary_generator.is_supported(full_path):
            ext = os.path.splitext(full_path)[1].lower()
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

        payload = {"source_id": source_id, "file_path": file_path, "full_path": full_path}
        from task_management.task_manager import task_manager
        task_id = task_manager.create_task(DocumentSummaryHandler.TASK_TYPE, payload)
        logger.info(f"概要生成任务已创建: task_id={task_id}, source_id={source_id}, file={file_path}")
        return {"task_id": task_id, "message": "概要生成任务已提交"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"提交概要生成任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sources/{source_id}/summarize-batch")
def summarize_batch(source_id: str, data: dict = Body(...), db: Session = Depends(get_db)):
    """批量生成摘要（异步任务）：files 缺省=全源递归枚举；条目可为目录（后端展开）"""
    try:
        files = _validated_files(data)
        document_source_registry.require(db, source_id)
        _require_model(db)
        # label：前端对勾选语义的描述（如目录路径 / 已选 N 项），任务列表数据源标签优先展示它
        label = data.get("label")
        payload = {
            "source_id": source_id,
            "files": files,
            "force": bool(data.get("force", False)),
            "concurrency": data.get("concurrency"),
            "batch_label": label.strip() if isinstance(label, str) and label.strip() else None,
        }
        from task_management.task_manager import task_manager
        task_id = task_manager.create_task(DocumentBatchSummaryHandler.TASK_TYPE, payload)
        logger.info(f"批量摘要任务已创建: task_id={task_id}, source_id={source_id}, "
                    f"files={len(files) if files else '全源'}")
        return {"task_id": task_id, "message": "批量摘要任务已提交"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"提交批量摘要任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sources/{source_id}/refresh")
def refresh_file(source_id: str, data: dict = Body(...), db: Session = Depends(get_db)):
    """重跑一篇文档：摘要 → 图谱回收 → 重新抽取 → Wiki 刷新（异步任务）"""
    try:
        file_path = data.get("file", "").strip()
        if not file_path:
            raise HTTPException(status_code=400, detail="file is required")

        document_source_registry.require(db, source_id)
        payload = {
            "source_id": source_id,
            "file_path": file_path,
            "force": bool(data.get("force", False)),
            "domain": data.get("domain"),
            "parallelism": data.get("parallelism"),
        }
        from task_management.task_manager import task_manager
        task_id = task_manager.create_task(DocumentRefreshHandler.TASK_TYPE, payload)
        logger.info(f"文档刷新任务已创建: task_id={task_id}, source_id={source_id}, file={file_path}")
        return {"task_id": task_id, "message": "文档刷新任务已提交"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"提交文档刷新任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sources/{source_id}/stale")
def list_stale_files(source_id: str, db: Session = Depends(get_db)):
    """列出该源中内容已变更或已删除的文档（供前端提示重新生成）"""
    from pipeline.refresh import scan_stale

    try:
        document_source_registry.require(db, source_id)
        stale = [item for item in scan_stale() if item["source_id"] == source_id]
        return {"status": "success", "source_id": source_id, "stale": stale}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"扫描失效文档失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sources/{source_id}/summary")
def get_summary(source_id: str, file: str, db: Session = Depends(get_db)):
    """获取已生成的概要内容"""
    try:
        try:
            summary_abs_path = summary_generator.summary_path(source_id, file)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not os.path.isfile(summary_abs_path):
            raise HTTPException(status_code=404, detail="概要不存在，请先生成")

        with open(summary_abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"status": "success", "summary": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取概要失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sources/{source_id}/extract")
def extract_from_summary(source_id: str, data: dict = Body(...), db: Session = Depends(get_db)):
    """从已生成的概要中提取实体和关系（异步任务执行；单文件即批量任务的特例 files=[file]）"""
    try:
        file_path = data.get("file", "").strip()
        if not file_path:
            raise HTTPException(status_code=400, detail="file is required")

        document_source_registry.require(db, source_id)
        try:
            summary_abs_path = summary_generator.summary_path(source_id, file_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not os.path.isfile(summary_abs_path):
            raise HTTPException(status_code=404, detail="概要不存在，请先生成概要")
        _require_model(db)

        payload = {
            "source_id": source_id,
            "files": [file_path],
            "domain": data.get("domain"),
            "parallelism": data.get("parallelism"),
        }
        from task_management.task_manager import task_manager
        task_id = task_manager.create_task(DocumentBatchExtractHandler.TASK_TYPE, payload)
        logger.info(f"实体提取任务已创建: task_id={task_id}, source_id={source_id}, file={file_path}")
        return {"task_id": task_id, "message": "实体提取任务已提交"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"提交实体提取任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sources/{source_id}/extract-batch")
def extract_batch(source_id: str, data: dict = Body(...), db: Session = Depends(get_db)):
    """批量从摘要提取实体关系（异步任务）：缺摘要的文件记 failure 继续，整批结果含成败清单"""
    try:
        files = _validated_files(data)
        document_source_registry.require(db, source_id)
        _require_model(db)
        label = data.get("label")
        payload = {
            "source_id": source_id,
            "files": files,
            "domain": data.get("domain"),
            "parallelism": data.get("parallelism"),
            "concurrency": data.get("concurrency"),
            "batch_label": label.strip() if isinstance(label, str) and label.strip() else None,
        }
        from task_management.task_manager import task_manager
        task_id = task_manager.create_task(DocumentBatchExtractHandler.TASK_TYPE, payload)
        logger.info(f"批量实体提取任务已创建: task_id={task_id}, source_id={source_id}, "
                    f"files={len(files) if files else '全源'}")
        return {"task_id": task_id, "message": "批量实体提取任务已提交"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"提交批量实体提取任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sources/{source_id}/inventory")
def source_inventory(source_id: str, db: Session = Depends(get_db)):
    """源内可处理文件的状态清单：是否已生成摘要、已抽取实体数（批量操作面板用）"""
    try:
        source = document_source_registry.require_alive(db, source_id)
        if source.source_type != "local":
            raise HTTPException(status_code=400, detail="仅本地文档源支持文件状态清单")

        files = list_supported_files(source.path)
        extracted_counts = {}
        try:
            from knowledge_graph.entity_repository import entity_repo
            extracted_counts = entity_repo.count_entities_by_datasource_prefix(f"DOC://{source_id}/")
        except Exception as e:
            logger.warning(f"[inventory] 实体计数查询失败（按 0 展示）: {e}")

        items = []
        for rel in files:
            try:
                has_summary = os.path.isfile(summary_generator.summary_path(source_id, rel))
            except ValueError:
                has_summary = False
            datasource = summary_generator.datasource_for(source_id, rel)
            items.append({
                "path": rel,
                "has_summary": has_summary,
                "extracted_count": extracted_counts.get(datasource, 0),
            })
        return {"status": "success", "source_id": source_id, "files": items}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"获取文件状态清单失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sources/{source_id}/entities")
def get_source_entities(source_id: str, file: str, db: Session = Depends(get_db)):
    """从知识库和图谱中获取已提取的实体和关系"""
    from knowledge_graph.entity_repository import entity_repo
    from knowledge_graph.relationship_repository import rel_repo

    try:
        datasource = summary_generator.datasource_for(source_id, file)
        entities = entity_repo.get_entities_by_datasource(datasource)

        entity_ids = {e.get("entity_id") for e in entities if e.get("entity_id")}
        all_rels = rel_repo.list_relationships(limit=1000)
        relationships = [
            r for r in all_rels
            if r.get("subject_id") in entity_ids or r.get("object_id") in entity_ids
        ]
        return {"status": "success", "entities": entities, "relationships": relationships}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实体列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
