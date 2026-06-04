import json
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
from database_management.database_manager import database_manager
from database_management.database_service import DatabaseService
from models.database import DatabaseTable
from sqlalchemy import func
from database_management.schema_annotator import schema_annotator
from task_management.task_manager import task_manager
from typing import Dict, List, Optional
from pydantic import BaseModel
from system.logger import logger

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

@router.post("/test-connection", response_model=Dict)
def test_connection_config(config: ConnectionConfig):
    """测试数据库连接配置（不保存，用于创建前的测试）"""
    try:
        from database_management.database_manager import DatabaseManager
        dm = DatabaseManager()
        success = dm.test_connection_config(config.dict())
        if success:
            return {"success": True, "message": "连接测试成功"}
        else:
            return {"success": False, "message": "连接测试失败"}
    except Exception as e:
        logger.error(f"测试数据库连接配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/connections", response_model=Dict)
def create_connection(config: ConnectionConfig, db: Session = Depends(get_db)):
    """创建数据库连接配置"""
    try:
        logger.info(f"创建数据库连接: {config.name}")
        connection_id = database_manager.create_connection(config.dict())
        return {"connection_id": connection_id, "message": "连接创建成功"}
    except Exception as e:
        logger.error(f"创建数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/connections/{connection_id}/databases", response_model=Dict)
def list_databases(connection_id: str, db: Session = Depends(get_db)):
    """获取数据库服务器上的所有数据库列表，包含分析状态"""
    try:
        live_databases = database_manager.list_databases(connection_id)
        db_service = DatabaseService()
        analyzed_records = db_service.get_analyzed_databases(db, connection_id)
        analyzed_dicts = [r.to_dict() for r in analyzed_records]
        merged = database_manager.merge_databases_with_status(live_databases, analyzed_dicts)
        return {"databases": merged}
    except Exception as e:
        logger.error(f"获取数据库列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/connections", response_model=List[Dict])
def get_all_connections(include_deleted: bool = False, db: Session = Depends(get_db)):
    """获取所有数据库连接配置"""
    try:
        connections = database_manager.get_all_connections(include_deleted=include_deleted)
        # Single query: find all connection_ids that have tables
        conn_with_tables = set(
            row[0] for row in db.query(DatabaseTable.connection_id).distinct().all()
        )
        result = []
        for c in connections:
            d = c.to_dict()
            d["has_schema"] = c.id in conn_with_tables
            result.append(d)
        return result
    except Exception as e:
        logger.error(f"获取数据库连接列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/connections/{connection_id}", response_model=Dict)
def get_connection(connection_id: str, db: Session = Depends(get_db)):
    """获取数据库连接配置"""
    try:
        connection = database_manager.get_connection(connection_id)
        if not connection:
            raise HTTPException(status_code=404, detail="连接不存在")
        d = connection.to_dict()
        has_schema = db.query(DatabaseTable).filter(DatabaseTable.connection_id == connection_id).first()
        d["has_schema"] = has_schema is not None
        return d
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/connections/{connection_id}", response_model=Dict)
def update_connection(connection_id: str, config: ConnectionUpdate, db: Session = Depends(get_db)):
    """更新数据库连接配置（支持部分更新）"""
    try:
        success = database_manager.update_connection(connection_id, config.dict(exclude_unset=True))
        if not success:
            raise HTTPException(status_code=404, detail="连接不存在")
        return {"message": "连接更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/connections/{connection_id}", response_model=Dict)
def delete_connection(connection_id: str, db: Session = Depends(get_db)):
    """删除数据库连接。无提取数据时直接删除，有数据时标记删除"""
    try:
        from datetime import datetime
        import os
        from models.database import DatabaseConnection, DatabaseTable

        connection = db.query(DatabaseConnection).filter(
            DatabaseConnection.id == connection_id,
            DatabaseConnection.is_deleted == False
        ).first()
        if not connection:
            raise HTTPException(status_code=404, detail="连接不存在")

        # 检查是否有已提取的 Schema 或概要数据
        has_data = db.query(DatabaseTable).filter(DatabaseTable.connection_id == connection_id).first() is not None
        if not has_data:
            summary_dir = os.path.join("data", "summaries", "DBS", connection_id)
            has_data = os.path.isdir(summary_dir) and bool(os.listdir(summary_dir))

        if not has_data:
            # 无数据，直接硬删除
            db.delete(connection)
            db.commit()
            logger.info(f"直接删除数据库连接成功（无数据）: id={connection_id}")
            return {"message": "连接删除成功", "deleted": True}
        else:
            # 有数据，标记删除
            connection.is_deleted = True
            connection.deleted_at = datetime.now()
            connection.updated_at = datetime.now()
            db.commit()
            logger.info(f"软删除数据库连接成功: id={connection_id}")
            return {"message": "连接删除成功", "deleted": False}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connections/{connection_id}/restore", response_model=Dict)
def restore_connection(connection_id: str, db: Session = Depends(get_db)):
    """恢复已删除的数据库连接"""
    try:
        from datetime import datetime
        from models.database import DatabaseConnection

        connection = db.query(DatabaseConnection).filter(
            DatabaseConnection.id == connection_id,
            DatabaseConnection.is_deleted == True
        ).first()
        if not connection:
            raise HTTPException(status_code=404, detail="已删除的连接不存在")

        connection.is_deleted = False
        connection.deleted_at = None
        connection.updated_at = datetime.now()
        db.commit()

        logger.info(f"恢复数据库连接成功: id={connection_id}")
        return {"message": "连接恢复成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/connections/{connection_id}/test", response_model=Dict)
def test_connection(connection_id: str):
    """测试数据库连接"""
    try:
        success = database_manager.test_connection(connection_id)
        if success:
            return {"success": True, "message": "连接测试成功"}
        else:
            return {"success": False, "message": "连接测试失败"}
    except Exception as e:
        logger.error(f"测试数据库连接失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{connection_id}/analyze", response_model=Dict)
def analyze_database(connection_id: str, request: Optional[AnalyzeRequest] = None):
    """
    批量分析数据库Schema（阶段1）
    - 提取所有表的表名、字段、主外键关联
    - 使用LLM为所有表和字段添加业务标注
    - 推断表之间的业务关联关系
    """
    try:
        payload = {
            "connection_id": connection_id,
            "tables": request.tables if request else None,
            "ignore_tables": request.ignore_tables if request else None,
            "database_name": request.database if request else None
        }
        task_id = task_manager.create_task("database_schema_analyze", payload)
        return {"task_id": task_id, "message": "分析任务已创建"}
    except Exception as e:
        logger.error(f"创建数据库分析任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{connection_id}/analysis-result", response_model=Dict)
def get_analysis_result(connection_id: str, db: Session = Depends(get_db)):
    """获取数据库分析结果"""
    try:
        db_service = DatabaseService()
        schema = db_service.get_schema(db, connection_id)
        if not schema["tables"]:
            raise HTTPException(status_code=404, detail="未找到分析结果")
        analyzed = db_service.get_analyzed_databases(db, connection_id)
        schema["analyzed_databases"] = [ad.database_name for ad in analyzed if ad.status == "extracted"]
        return schema
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取数据库分析结果失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{connection_id}/summary")
def get_database_summary(connection_id: str):
    """获取数据库概要信息（从本地概要文件读取）"""
    try:
        from database_management.database_service import DatabaseService
        from config.database import SessionLocal

        db = SessionLocal()
        try:
            db_service = DatabaseService()
            conn = db_service.get_connection(db, connection_id)
            db_name = conn.database if conn else None
        finally:
            db.close()

        if not db_name:
            raise HTTPException(status_code=404, detail="未找到数据库连接")

        summary_path = os.path.join("data", "summaries", "DBS", connection_id, f"{db_name}.json")
        if not os.path.isfile(summary_path):
            raise HTTPException(status_code=404, detail="数据库概要不存在，请先执行分析任务")

        with open(summary_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return {"status": "success", "summary": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取数据库概要失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{connection_id}/import", response_model=Dict)
def import_to_graph(connection_id: str, batch_size: int = 5000, row_limit: int = 0, neo4j_batch_size: int = 20000):
    """
    将分析结果导入知识图谱（阶段2）
    - batch_size: 每批从源数据库读取的行数（默认 5000）
    - row_limit: 每表最大导入行数（默认 0=不限制），用于测试
    - neo4j_batch_size: 每批写入 Neo4j 的实体数（默认 20000），增加以减少往返次数
    """
    try:
        payload = {"connection_id": connection_id, "batch_size": batch_size, "row_limit": row_limit, "neo4j_batch_size": neo4j_batch_size}
        task_id = task_manager.create_task("database_schema_import", payload)
        return {"task_id": task_id, "message": "导入任务已创建"}
    except Exception as e:
        logger.error(f"创建图谱导入任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))