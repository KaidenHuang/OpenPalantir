"""② 内容提取（数据库侧）—— Schema/视图提取编排

读连接配置（source_registry）→ 建引擎（connector）→ 方言提取（dialects）
→ 表过滤 → DatabaseSchema。纯解析无 LLM；业务标注归 summary_generation.database。
"""
from typing import Dict, List, Optional

from system.logger import logger


def extract_schema(connection_cfg: Dict, engine, tables: Optional[List[str]] = None,
                   ignore_tables: Optional[List[str]] = None) -> Dict:
    """按方言提取完整 Schema（含视图），并按表过滤"""
    from content_extraction.database.dialects import schema_extractor
    return schema_extractor.extract(connection_cfg, engine, tables, ignore_tables)


def extract_schema_for_connection(connection_id: str, tables: Optional[List[str]] = None,
                                  ignore_tables: Optional[List[str]] = None,
                                  database_name: Optional[str] = None) -> Dict:
    """编排入口：按 connection_id 取配置 → 建引擎 → 提取（供任务处理器调用）"""
    from config.database import SessionLocal
    from content_extraction.database.connector import create_engine_for
    from source_registry.database.registry import (
        database_source_registry,
        dict_from_connection,
    )

    db = SessionLocal()
    try:
        conn = database_source_registry.require(db, connection_id)
        cfg = dict_from_connection(conn)
    finally:
        db.close()

    # SQLite 的配置库名是文件路径、Oracle 是服务名，均不做「切库」覆盖
    if database_name and cfg.get("type", "").lower() not in ("sqlite", "oracle"):
        cfg = {**cfg, "database": database_name}

    engine = create_engine_for(cfg)
    if not engine:
        raise ValueError("无法创建数据库引擎")

    schema = extract_schema(cfg, engine, tables, ignore_tables)
    logger.info(f"Schema提取完成: connection={connection_id}, tables={len(schema['tables'])}")
    return schema
