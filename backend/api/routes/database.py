"""数据库源路由 —— HTTP 薄壳

注册/生命周期在 source_registry，Schema 读取在 content_extraction（阶段②提取结果），
概要读取在 summary_generation。
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config.database import get_db
from content_extraction.database.store import schema_store
from source_registry.database import registry as db_registry
from system.logger import logger
from task_management.handlers import SchemaAnalyzeHandler, SchemaImportHandler
from task_management.task_manager import task_manager

router = APIRouter(prefix="/api/database", tags=["database"])


class ConnectionConfig(BaseModel):
    name: str
    type: str
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    service_name: Optional[str] = None
    description: Optional[str] = None


class ConnectionUpdate(BaseModel):
    """Partial update model — all fields optional"""
    name: Optional[str] = None
    type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    service_name: Optional[str] = None
    description: Optional[str] = None


class AnalyzeRequest(BaseModel):
    tables: Optional[List[str]] = None
    ignore_tables: Optional[List[str]] = None
    database: Optional[str] = None
    domain: Optional[str] = None   # 本体域包名，决定标注用的实体/关系词表


@router.post("/test-connection", response_model=Dict)
def test_connection_config(config: ConnectionConfig):
    """测试数据库连接配置（不保存，用于创建前的测试）"""
    try:
        if db_registry.database_source_registry.test_config(config.dict()):
            return {"success": True, "message": "连接测试成功"}
        return {"success": False, "message": "连接测试失败"}
    except Exception as e:
        logger.error(f"测试数据库连接配置失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/connections", response_model=Dict)
def create_connection(config: ConnectionConfig, db: Session = Depends(get_db)):
    """创建数据库连接配置"""
    try:
        conn = db_registry.database_source_registry.create(db, config.dict())
        return {"connection_id": conn.id, "message": "连接创建成功"}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"创建数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/connections/{connection_id}/databases", response_model=Dict)
def list_databases(connection_id: str, db: Session = Depends(get_db)):
    """获取数据库服务器上的所有数据库列表，包含分析状态"""
    try:
        reg = db_registry.database_source_registry
        live_databases = reg.list_databases(db, connection_id)
        analyzed_records = schema_store.get_analyzed_databases(db, connection_id)
        analyzed_dicts = [r.to_dict() for r in analyzed_records]
        merged = reg.merge_databases_with_status(live_databases, analyzed_dicts)
        return {"databases": merged}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取数据库列表失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/connections", response_model=Dict)
def get_all_connections(show_deleted: bool = False, db: Session = Depends(get_db)):
    """获取所有数据库连接配置"""
    try:
        connections = db_registry.database_source_registry.list(db, include_deleted=show_deleted)
        # Single query: find all connection_ids that have tables
        from models.database import DatabaseTable
        conn_with_tables = set(
            row[0] for row in db.query(DatabaseTable.connection_id).distinct().all()
        )
        result = []
        for c in connections:
            d = c.to_dict()
            d["has_schema"] = c.id in conn_with_tables
            result.append(d)
        return {"connections": result}
    except Exception as e:
        logger.error(f"获取数据库连接列表失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/connections/{connection_id}", response_model=Dict)
def get_connection(connection_id: str, db: Session = Depends(get_db)):
    """获取数据库连接配置"""
    try:
        conn = db_registry.database_source_registry.get(db, connection_id)
        if not conn:
            raise HTTPException(status_code=404, detail="连接不存在")
        d = conn.to_dict()
        from models.database import DatabaseTable
        has_schema = db.query(DatabaseTable).filter(
            DatabaseTable.connection_id == connection_id).first()
        d["has_schema"] = has_schema is not None
        return d
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/connections/{connection_id}", response_model=Dict)
def update_connection(connection_id: str, config: ConnectionUpdate, db: Session = Depends(get_db)):
    """更新数据库连接配置（支持部分更新）"""
    try:
        db_registry.database_source_registry.update(db, connection_id, config.dict(exclude_unset=True))
        return {"message": "连接更新成功"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"更新数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/connections/{connection_id}", response_model=Dict)
def delete_connection(connection_id: str, db: Session = Depends(get_db)):
    """删除数据库连接。无提取数据时直接删除，有数据时标记删除"""
    try:
        deleted = db_registry.database_source_registry.delete(db, connection_id)
        return {"status": "success", "deleted": deleted,
                "message": "连接删除成功"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"删除数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/connections/{connection_id}/restore", response_model=Dict)
def restore_connection(connection_id: str, db: Session = Depends(get_db)):
    """恢复已删除的数据库连接"""
    try:
        db_registry.database_source_registry.restore(db, connection_id)
        return {"message": "连接恢复成功"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"恢复数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/connections/{connection_id}/test", response_model=Dict)
def test_connection(connection_id: str, db: Session = Depends(get_db)):
    """测试数据库连接"""
    try:
        success = db_registry.database_source_registry.test(db, connection_id)
        if success:
            return {"success": True, "message": "连接测试成功"}
        return {"success": False, "message": "连接测试失败"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"测试数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{connection_id}/analyze", response_model=Dict)
def analyze_database(connection_id: str, request: Optional[AnalyzeRequest] = None):
    """
    批量分析数据库Schema（阶段1）
    - 提取所有表的表名、字段、主外键关联、视图
    - 使用LLM为所有表和字段添加业务标注
    - 推断表之间的业务关联关系
    """
    try:
        payload = {
            "connection_id": connection_id,
            "tables": request.tables if request else None,
            "ignore_tables": request.ignore_tables if request else None,
            "database_name": request.database if request else None,
            "domain": (request.domain if request and request.domain else "general"),
        }
        task_id = task_manager.create_task(SchemaAnalyzeHandler.TASK_TYPE, payload)
        return {"task_id": task_id, "message": "分析任务已创建"}
    except Exception as e:
        logger.error(f"创建数据库分析任务失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{connection_id}/analysis-result", response_model=Dict)
def get_analysis_result(connection_id: str, database: Optional[str] = None,
                        db: Session = Depends(get_db)):
    """获取指定库的数据库分析结果（未分析时返回空结构；database 缺省按连接配置库名解析）"""
    try:
        from content_extraction.database.store import normalize_db_name
        from source_registry.database.registry import database_source_registry
        if database is None:
            conn = database_source_registry.get(db, connection_id)
            database = normalize_db_name(conn.database if conn else None,
                                         conn.type if conn else None)
        schema = schema_store.get_schema(db, connection_id, database)
        analyzed = schema_store.get_analyzed_databases(db, connection_id)
        schema["analyzed_databases"] = [ad.database_name for ad in analyzed if ad.status == "extracted"]
        return schema
    except Exception as e:
        logger.error(f"获取数据库分析结果失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{connection_id}/summary")
def get_database_summary(connection_id: str, database: Optional[str] = None,
                         db: Session = Depends(get_db)):
    """获取数据库概要信息（从本地概要文件读取；database 缺省按连接配置库名解析）"""
    try:
        from summary_generation.database import store
        data = store.load(connection_id, database)
        if not data:
            raise HTTPException(status_code=404, detail="数据库概要不存在，请先执行分析任务")
        return {"status": "success", "summary": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取数据库概要失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{connection_id}/import", response_model=Dict)
def import_to_graph(connection_id: str, batch_size: int = 5000, row_limit: int = 0, neo4j_batch_size: int = 20000, use_merge: bool = False, auto_start_cdc: bool = False, database_name: Optional[str] = None):
    """
    将分析结果导入知识图谱（阶段2）
    - batch_size: 每批从源数据库读取的行数（默认 5000）
    - row_limit: 每表最大导入行数（默认 0=不限制），用于测试
    - neo4j_batch_size: 每批写入 Neo4j 的实体数（默认 20000），增加以减少往返次数
    - use_merge: 关系写入是否使用 MERGE（默认 False=使用 CREATE，更快；True=使用 MERGE，幂等安全）
    - auto_start_cdc: 导入完成后是否自动启动 CDC 增量同步（默认 False）
    - database_name: 目标库名，缺省取该连接最早记录的已分析库
    """
    try:
        payload = {"connection_id": connection_id, "batch_size": batch_size, "row_limit": row_limit, "neo4j_batch_size": neo4j_batch_size, "use_merge": use_merge, "auto_start_cdc": auto_start_cdc, "database_name": database_name}
        task_id = task_manager.create_task(SchemaImportHandler.TASK_TYPE, payload)
        return {"task_id": task_id, "message": "导入任务已创建"}
    except Exception as e:
        logger.error(f"创建图谱导入任务失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
