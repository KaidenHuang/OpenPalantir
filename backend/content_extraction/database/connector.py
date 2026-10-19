"""数据库连接执行器 —— SQLAlchemy 引擎构建（自 database_manager 抽出的可复用缝）

只负责「按连接配置造 engine」，不做任何业务判定；
extract_schema 的编排在 schema_reader，行级读取在 entity_extraction.database。
"""
from typing import Any, Optional
from urllib.parse import quote

from sqlalchemy import create_engine
from system.logger import logger


def _fields(connection: Any) -> dict:
    """兼容 dict 与 ORM 对象两种入参"""
    if isinstance(connection, dict):
        return connection
    return {
        "type": connection.type,
        "host": connection.host,
        "port": connection.port,
        "database": connection.database,
        "username": connection.username,
        "password": connection.password,
        "service_name": getattr(connection, "service_name", None),
    }


def _url(cfg: dict, *, bare: bool) -> Optional[str]:
    db_type = (cfg.get("type") or "").lower()
    host = cfg.get("host")
    port = cfg.get("port")
    database = cfg.get("database")
    username = cfg.get("username")
    password = cfg.get("password")
    service_name = cfg.get("service_name")

    user = quote(username) if username else ""
    pw = quote(password) if password else ""

    if bare:  # 不指定具体数据库（用于列举库/测试连通）
        if db_type == "mysql":
            return f"mysql+pymysql://{user}:{pw}@{host}:{port}?charset=utf8mb4"
        if db_type == "postgresql":
            return f"postgresql://{user}:{pw}@{host}:{port}/postgres"
        if db_type == "sqlite":
            return f"sqlite:///{quote(str(database), safe='/:\\\\')}" if database else None
        if db_type == "oracle":
            return (f"oracle+cx_oracle://{user}:{pw}@{host}:{port}/{service_name}"
                    if service_name
                    else f"oracle+cx_oracle://{user}:{pw}@{host}:{port}")
        if db_type == "mssql":
            return f"mssql+pyodbc://{user}:{pw}@{host}:{port}?driver=ODBC+Driver+17+for+SQL+Server"
        logger.error(f"不支持的数据库类型: {db_type}")
        return None

    if db_type == "mysql":
        return f"mysql+pymysql://{user}:{pw}@{host}:{port}/{database}?charset=utf8mb4"
    if db_type == "postgresql":
        return f"postgresql://{user}:{pw}@{host}:{port}/{database}"
    if db_type == "sqlite":
        return f"sqlite:///{quote(str(database), safe='/:\\\\')}"
    if db_type == "oracle":
        if service_name:
            return f"oracle+cx_oracle://{user}:{pw}@{host}:{port}/{quote(service_name, safe='')}"
        return f"oracle+cx_oracle://{user}:{pw}@{host}:{port}/{quote(database, safe='')}"
    if db_type == "mssql":
        return (f"mssql+pyodbc://{user}:{pw}@{host}:{port}/{quote(database, safe='')}"
                "?driver=ODBC+Driver+17+for+SQL+Server")
    logger.error(f"不支持的数据库类型: {db_type}")
    return None


def _engine(cfg: dict, *, bare: bool) -> Optional[Any]:
    try:
        url = _url(cfg, bare=bare)
        if not url:
            return None
        return create_engine(url)
    except Exception as e:
        logger.error(f"创建数据库引擎失败: {e}")
        return None


def create_engine_for(connection: Any):
    """按连接配置创建指向具体库的引擎（dict 或 ORM 对象均可）"""
    return _engine(_fields(connection), bare=False)


def create_bare_engine_for(connection: Any):
    """创建不指定具体库的裸引擎（列举数据库用）"""
    return _engine(_fields(connection), bare=True)
