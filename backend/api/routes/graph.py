from fastapi import APIRouter, HTTPException, Body, Query
from pydantic import BaseModel
from typing import Dict, Any, Optional
from knowledge_graph.graph_manager import graph_manager
from system.logger import logger

router = APIRouter()


# ── Request Models ──

class EntityUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None

class EntitySearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 10
    page: Optional[int] = 1
    entity_type: Optional[str] = None


def _get_entity_or_404(entity_id: str) -> dict:
    """获取实体，不存在则抛出 404"""
    entity = graph_manager.get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


# ═══════════════════════════════════════════
# Node (Entity) Endpoints
# ═══════════════════════════════════════════

@router.get("/nodes")
async def list_nodes(
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(10, ge=1, le=1000, description="每页条数"),
    entity_type: Optional[str] = Query(None, description="实体类型"),
    query: Optional[str] = Query(None, description="搜索关键词")
):
    """获取节点/实体列表（支持分页、搜索和类型过滤）"""
    try:
        logger.debug(f"接收获取节点列表请求: page={page}, limit={limit}, entity_type={entity_type}, query={query}")

        offset = (page - 1) * limit
        entities, total_count = graph_manager.list_entities_with_pagination(
            entity_type=entity_type if entity_type else None,
            query=query or None,
            limit=limit,
            offset=offset,
        )
        total_pages = (total_count + limit - 1) // limit

        logger.info(f"获取节点列表成功: 共 {total_count} 个节点, 当前页 {page}/{total_pages}")
        return {
            "status": "success",
            "data": {
                "entities": entities,
                "pagination": {
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "current_page": page,
                    "page_size": limit
                }
            }
        }
    except Exception as e:
        logger.error(f"获取节点列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nodes/{entity_id}")
async def get_node(entity_id: str):
    """获取节点/实体详情"""
    try:
        logger.debug(f"接收获取节点详情请求: entity_id={entity_id}")

        entity = _get_entity_or_404(entity_id)
        logger.info(f"获取节点详情成功: {entity_id}")
        return {"status": "success", "data": {"entity": entity}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取节点详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nodes/search")
async def search_nodes(request: EntitySearchRequest):
    """搜索节点/实体"""
    try:
        logger.info(f"接收搜索节点请求: query={request.query}, page={request.page}, limit={request.limit}, entity_type={request.entity_type}")

        offset = (request.page - 1) * request.limit
        entities, total_count = graph_manager.list_entities_with_pagination(
            entity_type=request.entity_type,
            query=request.query,
            limit=request.limit,
            offset=offset,
        )
        total_pages = (total_count + request.limit - 1) // request.limit

        logger.info(f"搜索节点成功: 共 {total_count} 个结果, 当前页 {request.page}/{total_pages}")
        return {
            "status": "success",
            "data": {
                "entities": entities,
                "pagination": {
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "current_page": request.page,
                    "page_size": request.limit
                }
            }
        }
    except Exception as e:
        logger.error(f"搜索节点失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nodes")
async def add_node(entity: dict = Body(...)):
    """添加单个节点/实体"""
    try:
        entity_name = entity.get("name", "unknown")
        logger.debug(f"接收添加节点请求: name={entity_name}")

        result = graph_manager.add_entity(entity)
        logger.info(f"添加节点成功: {entity_name}")
        return result
    except Exception as e:
        logger.error(f"添加节点失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nodes/batch")
async def batch_add_nodes(entities: list = Body(...)):
    """批量添加节点/实体"""
    try:
        logger.debug(f"接收批量添加节点请求: count={len(entities)}")

        result = graph_manager.batch_add_entities(entities)
        logger.info(f"批量添加节点成功: count={len(entities)}")
        return result
    except Exception as e:
        logger.error(f"批量添加节点失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/nodes/{entity_id}")
async def update_node(entity_id: str, request: EntityUpdateRequest):
    """更新节点/实体"""
    try:
        update_data = request.dict(exclude_unset=True)
        logger.info(f"接收更新节点请求: entity_id={entity_id}, update_data={update_data}")

        _get_entity_or_404(entity_id)
        if not update_data:
            raise HTTPException(status_code=400, detail="No data provided for update")

        success = graph_manager.update_entity(entity_id, update_data)
        if success:
            logger.info(f"更新节点成功: {entity_id}")
            return {"status": "success", "message": "Entity updated successfully"}
        raise HTTPException(status_code=404, detail="Entity not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新节点失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/nodes/{entity_id}")
async def delete_node(entity_id: str):
    """删除节点/实体"""
    try:
        logger.info(f"接收删除节点请求: entity_id={entity_id}")

        _get_entity_or_404(entity_id)
        success = graph_manager.delete_entity(entity_id)
        if success:
            logger.info(f"删除节点成功: {entity_id}")
            return {"status": "success", "message": "Entity deleted successfully"}
        raise HTTPException(status_code=404, detail="Entity not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除节点失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nodes/{entity_id}/relationships")
async def get_node_relationships(entity_id: str):
    """获取节点关联的关系"""
    try:
        logger.debug(f"接收获取节点关系请求: entity_id={entity_id}")

        _get_entity_or_404(entity_id)
        relationships = graph_manager.get_entity_relationships(entity_id)
        logger.info(f"获取节点关系成功: {entity_id}, 共 {len(relationships)} 个关系")
        return {
            "status": "success",
            "data": {"relationships": relationships}
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取节点关系失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════
# Edge Endpoints
# ═══════════════════════════════════════════

@router.get("/edges")
async def get_edges():
    """获取图谱边"""
    try:
        logger.debug("接收获取图谱边请求")
        edges = graph_manager.get_edges()
        logger.info(f"获取图谱边成功: 共 {len(edges)} 条边")
        return {"edges": edges}
    except Exception as e:
        logger.error(f"获取图谱边失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════
# Relationship Endpoints
# ═══════════════════════════════════════════

@router.post("/relationships")
async def add_relationship(relationship: dict = Body(...)):
    """添加单个关系"""
    try:
        source = relationship.get("source", relationship.get("subject", "unknown"))
        target = relationship.get("target", relationship.get("object", "unknown"))
        predicate = relationship.get("predicate", "unknown")
        logger.debug(f"接收添加关系请求: source={source}, target={target}, predicate={predicate}")

        result = graph_manager.add_relationship(relationship)
        logger.info(f"添加关系成功: {source} -{predicate}-> {target}")
        return result
    except Exception as e:
        logger.error(f"添加关系失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/relationships/batch")
async def batch_add_relationships(relationships: list = Body(...)):
    """批量添加关系"""
    try:
        logger.debug(f"接收批量添加关系请求: count={len(relationships)}")

        result = graph_manager.batch_add_relationships(relationships)
        logger.info(f"批量添加关系成功: count={len(relationships)}")
        return result
    except Exception as e:
        logger.error(f"批量添加关系失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════
# Graph Query & Export
# ═══════════════════════════════════════════

@router.post("/query")
async def query_graph(query: str = Body(..., description="Cypher 查询语句")):
    """执行 Cypher 查询"""
    try:
        logger.debug(f"接收查询图谱请求: query={query}")

        results = graph_manager.query_graph(query)
        logger.info(f"查询图谱成功: 结果数: {len(results)}")
        return {"query": query, "results": results}
    except Exception as e:
        logger.error(f"查询图谱失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export")
async def export_graph(format: str = Body("json", description="导出格式")):
    """导出图谱"""
    try:
        logger.debug(f"接收导出图谱请求: format={format}")

        nodes = graph_manager.get_nodes()
        edges = graph_manager.get_edges()

        if format == "json":
            logger.info(f"导出图谱成功: 节点数: {len(nodes)}, 边数: {len(edges)}")
            return {
                "format": format,
                "status": "exported",
                "data": {"nodes": nodes, "edges": edges}
            }
        logger.error(f"导出图谱失败: 不支持的格式 {format}")
        return {"format": format, "status": "unsupported"}
    except Exception as e:
        logger.error(f"导出图谱失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════
# Graph Analysis (Partition / Compress / Meta)
# ═══════════════════════════════════════════

@router.post("/partition")
async def partition_graph(method: str = Body("louvain", description="分区方法")):
    """分区图谱"""
    try:
        logger.debug(f"接收分区图谱请求: method={method}")

        result = graph_manager.partition_graph(method)
        logger.info(f"分区图谱成功: method={method}")
        return result
    except Exception as e:
        logger.error(f"分区图谱失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compress")
async def compress_graph(compression_ratio: float = Body(0.5, description="压缩比率")):
    """压缩图谱"""
    try:
        logger.debug(f"接收压缩图谱请求: compression_ratio={compression_ratio}")

        result = graph_manager.compress_graph(compression_ratio)
        logger.info(f"压缩图谱成功: compression_ratio={compression_ratio}")
        return result
    except Exception as e:
        logger.error(f"压缩图谱失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/meta-graph")
async def get_meta_graph():
    """创建元图谱"""
    try:
        logger.debug("接收创建元图谱请求")

        result = graph_manager.create_meta_graph()
        logger.info("创建元图谱成功")
        return result
    except Exception as e:
        logger.error(f"创建元图谱失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/partition/{entity_name}")
async def get_entity_partition(entity_name: str):
    """获取实体所在分区"""
    try:
        logger.debug(f"接收获取实体分区请求: entity_name={entity_name}")

        result = graph_manager.get_partition(entity_name)
        logger.info(f"获取实体分区成功: entity_name={entity_name}")
        return result
    except Exception as e:
        logger.error(f"获取实体分区失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════
# Optimization / Maintenance
# ═══════════════════════════════════════════

@router.post("/optimize/schema")
async def optimize_schema():
    """优化图谱 schema（创建索引等）"""
    try:
        logger.debug("接收优化 schema 请求")

        result = graph_manager.optimize_schema()
        logger.info("优化 schema 成功")
        return result
    except Exception as e:
        logger.error(f"优化 schema 失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize/clear-cache")
async def clear_cache():
    """清除缓存"""
    try:
        logger.debug("接收清除缓存请求")

        result = graph_manager.clear_cache()
        logger.info("清除缓存成功")
        return result
    except Exception as e:
        logger.error(f"清除缓存失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize/query-performance")
async def get_query_performance(query: str = Body(..., description="Cypher 查询语句")):
    """获取查询性能信息"""
    try:
        logger.debug(f"接收获取查询性能信息请求: query={query}")

        result = graph_manager.get_query_performance(query)
        logger.info(f"获取查询性能信息成功: query={query}")
        return result
    except Exception as e:
        logger.error(f"获取查询性能信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
