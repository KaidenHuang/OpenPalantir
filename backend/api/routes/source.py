import os
import json
import uuid
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from fastapi import APIRouter, HTTPException, Body, Depends
from sqlalchemy.orm import Session
from config.database import get_db
from models.source import DocumentSource
from model_management.model_service import ModelService
from system.logger import logger
router = APIRouter()


@router.post("/sources")
async def create_source(data: dict = Body(...), db: Session = Depends(get_db)):
    """创建文档源（本地路径或S3 URI）"""
    try:
        name = data.get("name", "").strip()
        path = data.get("path", "").strip()
        source_type = data.get("source_type", "local")

        if not name or not path:
            raise HTTPException(status_code=400, detail="name and path are required")

        if source_type == "local":
            if not os.path.exists(path):
                raise HTTPException(status_code=400, detail=f"路径不存在: {path}")
        elif source_type == "s3":
            if not path.startswith("s3://"):
                raise HTTPException(status_code=400, detail="S3路径必须以 s3:// 开头")
        else:
            raise HTTPException(status_code=400, detail="不支持的source_type，仅支持 local 或 s3")

        source = DocumentSource(
            name=name,
            path=path,
            source_type=source_type,
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        logger.info(f"创建文档源成功: id={source.id}, name={source.name}, path={source.path}")
        return {
            "status": "success",
            "source": {
                "id": source.id,
                "name": source.name,
                "path": source.path,
                "source_type": source.source_type,
                "created_at": source.created_at.isoformat() if source.created_at else None,
                "is_deleted": source.is_deleted,
                "deleted_at": source.deleted_at.isoformat() if source.deleted_at else None,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建文档源失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources")
async def list_sources(include_deleted: bool = False, db: Session = Depends(get_db)):
    """列出所有文档源"""
    try:
        query = db.query(DocumentSource)
        if not include_deleted:
            query = query.filter(DocumentSource.is_deleted == False)
        sources = query.order_by(DocumentSource.created_at.desc()).all()
        return {
            "status": "success",
            "sources": [
                {
                    "id": s.id,
                    "name": s.name,
                    "path": s.path,
                    "source_type": s.source_type,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "is_deleted": s.is_deleted,
                    "deleted_at": s.deleted_at.isoformat() if s.deleted_at else None,
                }
                for s in sources
            ]
        }
    except Exception as e:
        logger.error(f"获取文档源列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, db: Session = Depends(get_db)):
    """删除文档源。无提取数据时直接删除，有数据时标记删除"""
    try:
        from datetime import datetime
        import os
        source = db.query(DocumentSource).filter(
            DocumentSource.id == source_id,
            DocumentSource.is_deleted == False
        ).first()
        if not source:
            raise HTTPException(status_code=404, detail="文档源不存在")

        # 检查是否有已提取的概要或实体数据
        summary_dir = os.path.join("data", "summaries", "DOC", source_id)
        has_data = os.path.isdir(summary_dir) and bool(os.listdir(summary_dir))

        if not has_data:
            # 无数据，直接硬删除
            db.delete(source)
            db.commit()
            logger.info(f"直接删除文档源成功（无数据）: id={source_id}")
            return {"status": "success", "result": True, "deleted": True}
        else:
            # 有数据，标记删除
            source.is_deleted = True
            source.deleted_at = datetime.now()
            db.commit()
            logger.info(f"软删除文档源成功: id={source_id}")
            return {"status": "success", "result": True, "deleted": False}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文档源失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources/{source_id}/restore")
async def restore_source(source_id: str, db: Session = Depends(get_db)):
    """恢复已删除的文档源"""
    try:
        source = db.query(DocumentSource).filter(
            DocumentSource.id == source_id,
            DocumentSource.is_deleted == True
        ).first()
        if not source:
            raise HTTPException(status_code=404, detail="已删除的文档源不存在")

        source.is_deleted = False
        source.deleted_at = None
        db.commit()

        logger.info(f"恢复文档源成功: id={source_id}")
        return {"status": "success", "result": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复文档源失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/{source_id}/browse")
async def browse_source(source_id: str, prefix: str = "", db: Session = Depends(get_db)):
    """浏览文档源目录（列出文件+子目录）"""
    try:
        source = db.query(DocumentSource).filter(DocumentSource.id == source_id).first()
        if not source:
            raise HTTPException(status_code=404, detail="文档源不存在")

        if source.source_type != "local":
            raise HTTPException(status_code=400, detail="仅支持本地文件系统浏览")

        base_path = os.path.normpath(source.path)
        current_path = os.path.normpath(os.path.join(base_path, prefix)) if prefix else base_path

        if not current_path.startswith(base_path):
            raise HTTPException(status_code=400, detail="路径越界")

        if not os.path.exists(current_path):
            raise HTTPException(status_code=404, detail=f"路径不存在: {current_path}")

        if os.path.isfile(current_path):
            raise HTTPException(status_code=400, detail="路径是文件而非目录")

        entries = []
        for entry in os.scandir(current_path):
            if entry.is_dir():
                entries.append({
                    "name": entry.name,
                    "type": "dir",
                    "path": os.path.relpath(entry.path, base_path).replace("\\", "/"),
                })
            elif entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                entries.append({
                    "name": entry.name,
                    "type": "file",
                    "path": os.path.relpath(entry.path, base_path).replace("\\", "/"),
                    "size": entry.stat().st_size,
                    "ext": ext,
                })

        entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))

        return {
            "status": "success",
            "source_id": source_id,
            "base_path": base_path,
            "current_path": os.path.relpath(current_path, base_path).replace("\\", "/") or "",
            "entries": entries,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"浏览文档源失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources/{source_id}/summarize")
async def summarize_file(source_id: str, data: dict = Body(...), db: Session = Depends(get_db)):
    """为源中的某个文件生成 PageIndex 概要（通过异步任务执行）"""
    from task_management.task_manager import task_manager

    try:
        file_path = data.get("file", "").strip()
        if not file_path:
            raise HTTPException(status_code=400, detail="file is required")

        source = db.query(DocumentSource).filter(DocumentSource.id == source_id).first()
        if not source:
            raise HTTPException(status_code=404, detail="文档源不存在")

        full_path = os.path.normpath(os.path.join(source.path, file_path))
        if not full_path.startswith(os.path.normpath(source.path)):
            raise HTTPException(status_code=400, detail="路径越界")

        if not os.path.isfile(full_path):
            raise HTTPException(status_code=400, detail="文件不存在")

        ext = os.path.splitext(full_path)[1].lower()
        if ext not in (".pdf", ".md", ".txt"):
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

        payload = {
            "source_id": source_id,
            "file_path": file_path,
            "full_path": full_path,
        }
        task_id = task_manager.create_task("document_generate_summary", payload)

        logger.info(f"概要生成任务已创建: task_id={task_id}, source_id={source_id}, file={file_path}")

        return {
            "task_id": task_id,
            "message": "概要生成任务已提交",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交概要生成任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/{source_id}/summary")
async def get_summary(source_id: str, file: str, db: Session = Depends(get_db)):
    """获取已生成的概要内容"""
    try:
        summary_rel_path = file + ".json"
        summary_abs_path = os.path.join("data", "summaries", "DOC", source_id, summary_rel_path)

        if not os.path.isfile(summary_abs_path):
            raise HTTPException(status_code=404, detail="概要不存在，请先生成")

        with open(summary_abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return {"status": "success", "summary": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取概要失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def _iter_segments(node, max_chunk: int = 20000):
    """从 PageIndex 树节点逐个 yield (title, text) 元组，超长段按句子边界切分"""
    if isinstance(node, dict):
        title = node.get("title", "")
        if "text" in node and node["text"]:
            seg = node["text"].strip()
            if seg:
                if len(seg) <= max_chunk:
                    yield (title, seg)
                else:
                    for i, part in enumerate(_split_text(seg, max_chunk)):
                        yield (f"{title}(切{i+1})", part)
        for key, val in node.items():
            if isinstance(val, (dict, list)):
                yield from _iter_segments(val, max_chunk)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_segments(item, max_chunk)


def _split_text(text: str, max_chunk: int):
    """按句子边界切分长文本，每块不超过 max_chunk 字符"""
    import re
    sentences = re.split(r'(?<=[。！？\n])', text)
    current = ""
    for s in sentences:
        if not s.strip():
            continue
        if len(current) + len(s) <= max_chunk:
            current += s
        else:
            if current:
                yield current
            if len(s) > max_chunk:
                for i in range(0, len(s), max_chunk):
                    yield s[i:i + max_chunk]
            else:
                current = s
    if current:
        yield current


def _merge_segments_iter(segments, max_chunk: int = 20000, min_size: int = 1000):
    """将不足 min_size 的段合并为大块并逐个 yield，合并后总长度不超过 max_chunk"""
    buffer = ""
    buffer_titles = []
    chunk_index = 0

    for title, seg in segments:
        if len(seg) >= min_size:
            if buffer:
                if len(buffer) + len(seg) <= max_chunk:
                    chunk_index += 1
                    titles = buffer_titles + [title]
                    logger.info(f"合并块 {chunk_index}: {' + '.join(titles)} (总长: {len(buffer + seg)})")
                    yield buffer + seg
                else:
                    chunk_index += 1
                    if buffer_titles:
                        logger.info(f"合并块 {chunk_index}: {' + '.join(buffer_titles)} (总长: {len(buffer)})")
                    else:
                        logger.info(f"合并块 {chunk_index}: (总长: {len(buffer)})")
                    yield buffer
                    chunk_index += 1
                    logger.info(f"合并块 {chunk_index}: {title} (总长: {len(seg)})")
                    yield seg
                buffer = ""
                buffer_titles = []
            else:
                chunk_index += 1
                logger.info(f"合并块 {chunk_index}: {title} (总长: {len(seg)})")
                yield seg
        else:
            if len(buffer) + len(seg) > max_chunk:
                chunk_index += 1
                if buffer_titles:
                    logger.info(f"合并块 {chunk_index}: {' + '.join(buffer_titles)} (总长: {len(buffer)})")
                else:
                    logger.info(f"合并块 {chunk_index}: (总长: {len(buffer)})")
                yield buffer
                buffer = seg
                buffer_titles = [title] if title else []
            else:
                buffer += seg
                if title and (not buffer_titles or buffer_titles[-1] != title):
                    buffer_titles.append(title)
    if buffer:
        chunk_index += 1
        if buffer_titles:
            logger.info(f"合并块 {chunk_index}: {' + '.join(buffer_titles)} (总长: {len(buffer)})")
        else:
            logger.info(f"合并块 {chunk_index}: (总长: {len(buffer)})")
        yield buffer


@router.post("/sources/{source_id}/extract")
async def extract_from_summary(source_id: str, data: dict = Body(...), db: Session = Depends(get_db)):
    """从已生成的概要中提取实体和关系"""
    try:
        file_path = data.get("file", "").strip()
        if not file_path:
            raise HTTPException(status_code=400, detail="file is required")

        source = db.query(DocumentSource).filter(DocumentSource.id == source_id).first()
        if not source:
            raise HTTPException(status_code=404, detail="文档源不存在")

        summary_abs_path = os.path.join("data", "summaries", "DOC", source_id, file_path + ".json")
        if not os.path.isfile(summary_abs_path):
            raise HTTPException(status_code=404, detail="概要不存在，请先生成概要")

        with open(summary_abs_path, "r", encoding="utf-8") as f:
            summary = json.load(f)

        datasource = f"DOC://{source_id}/{file_path}"

        model_config = ModelService.get_available_model(db)
        if not model_config:
            raise HTTPException(status_code=503, detail="没有可用的模型，请先在模型管理中启用一个模型")

        from entity_extraction.llm_entity_enhancer import LLMEntityEnhancer
        from utils.data_store import EntityDataStore

        enhancer = LLMEntityEnhancer(model_config=model_config)

        # 流式分段、合并、提交 LLM 调用（不构建中间大列表）
        structure = summary.get("structure", [])
        segments = _iter_segments(structure)
        chunks = _merge_segments_iter(segments)

        max_workers = data.get("parallelism", 8)
        all_entities = []
        all_relationships = []
        lock = Lock()

        def extract_one(idx: int, chunk: str):
            logger.info(f"提取第 {idx+1} 块，长度: {len(chunk)}")
            result = enhancer.extract_entities_and_relationships(chunk)
            return result.get("entities", []), result.get("relationships", [])

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            chunk_count = 0
            for i, chunk in enumerate(chunks):
                chunk_count += 1
                logger.info(f"提交第 {chunk_count} 块到LLM")
                future = executor.submit(extract_one, i, chunk)
                futures[future] = i

            logger.info(f"共 {chunk_count} 个文本块，开始提取")

            if chunk_count == 0:
                raise HTTPException(status_code=400, detail="概要中没有可提取的文本内容")

            for future in as_completed(futures):
                ents, rels = future.result()
                with lock:
                    all_entities.extend(ents)
                    all_relationships.extend(rels)

        # 全局去重
        seen_entity = set()
        entities = []
        for e in all_entities:
            key = f"{e.get('n', '')}_{e.get('t', '')}"
            if key not in seen_entity:
                seen_entity.add(key)
                e["datasource"] = datasource
                entities.append(e)

        seen_rel = set()
        relationships = []
        for r in all_relationships:
            key = f"{r.get('s', '')}_{r.get('p', '')}_{r.get('o', '')}"
            if key not in seen_rel:
                seen_rel.add(key)
                relationships.append(r)

        # 保存到知识库和图谱
        entity_count, rel_count = EntityDataStore.save_all(entities, relationships, datasource=datasource)

        logger.info(f"实体关系提取完成: entities={entity_count}, relationships={rel_count}")
        return {
            "status": "success",
            "file": file_path,
            "entity_count": entity_count,
            "relationship_count": rel_count,
            "entities": entities,
            "relationships": relationships,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提取实体关系失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/{source_id}/entities")
async def get_source_entities(source_id: str, file: str, db: Session = Depends(get_db)):
    """从知识库和图谱中获取已提取的实体和关系"""
    from knowledge_graph.graph_manager import graph_manager

    try:
        datasource = f"DOC://{source_id}/{file}"
        entities = graph_manager.get_entities_by_datasource(datasource)

        entity_ids = {e.get("entity_id") for e in entities if e.get("entity_id")}
        all_rels = graph_manager.list_relationships(limit=1000)
        relationships = [
            r for r in all_rels
            if r.get("subject_id") in entity_ids or r.get("object_id") in entity_ids
        ]

        return {
            "status": "success",
            "entities": entities,
            "relationships": relationships,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实体列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
