"""数据库源注册 —— 连接配置的存在性与可达性管理

职责：数据库连接的注册/列表/更新/软删/恢复/连通性测试/库列表。
不涉及 Schema 提取（content_extraction）与标注（summary_generation）。
"""
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from models.database import DB_STATUS_DELETED, DB_STATUS_EXTRACTED, DatabaseConnection
from system.logger import logger


class DatabaseSourceRegistry:
    """数据库源注册表（数据访问层，路由只做 HTTP 映射）"""

    def get(self, db: Session, connection_id: str) -> Optional[DatabaseConnection]:
        return db.query(DatabaseConnection).filter_by(id=connection_id).first()

    def require(self, db: Session, connection_id: str) -> DatabaseConnection:
        conn = self.get(db, connection_id)
        if not conn:
            raise ValueError(f"连接不存在: {connection_id}")
        return conn

    def require_alive(self, db: Session, connection_id: str) -> DatabaseConnection:
        conn = self.require(db, connection_id)
        if conn.is_deleted:
            raise ValueError(f"连接已删除: {connection_id}")
        return conn

    def get_by_name(self, db: Session, name: str) -> Optional[DatabaseConnection]:
        return db.query(DatabaseConnection).filter(
            DatabaseConnection.name == name,
            DatabaseConnection.is_deleted == False,
        ).first()

    def list(self, db: Session, include_deleted: bool = False) -> List[DatabaseConnection]:
        query = db.query(DatabaseConnection)
        if not include_deleted:
            query = query.filter(DatabaseConnection.is_deleted == False)
        return query.all()

    def create(self, db: Session, config: Dict) -> DatabaseConnection:
        """注册数据库连接（名称重复拒绝）"""
        if not str(config.get("name", "")).strip():
            raise ValueError("连接名称不能为空")
        existing = self.get_by_name(db, config["name"])
        if existing:
            raise ValueError(f"连接名称已存在: {config['name']}")

        conn = DatabaseConnection(
            id=str(uuid.uuid4()),
            name=config["name"],
            type=config["type"],
            host=config.get("host"),
            port=config.get("port"),
            database=config.get("database"),
            username=config.get("username"),
            password=config.get("password"),
            service_name=config.get("service_name"),
            description=config.get("description"),
            created_at=datetime.now(),
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)
        logger.info(f"[source_registry] 数据库连接已注册: {conn.id}")
        return conn

    _UPDATABLE = ("name", "type", "host", "port", "database",
                  "username", "password", "service_name", "description")

    def update(self, db: Session, connection_id: str, config: Dict) -> bool:
        conn = self.get(db, connection_id)
        if not conn:
            raise ValueError(f"连接不存在: {connection_id}")
        for field in self._UPDATABLE:
            if field in config:
                setattr(conn, field, config[field])
        conn.updated_at = datetime.now()
        db.commit()
        logger.info(f"[source_registry] 数据库连接已更新: {connection_id}")
        return True

    def delete(self, db: Session, connection_id: str) -> bool:
        """删除连接：无关联 Schema/概要时硬删，否则软删"""
        conn = self.get(db, connection_id)
        if not conn:
            raise ValueError(f"连接不存在: {connection_id}")

        if self.has_persisted_data(db, connection_id):
            conn.is_deleted = True
            conn.deleted_at = datetime.now()
            conn.updated_at = datetime.now()
            db.commit()
            logger.info(f"[source_registry] 数据库连接软删除: {connection_id}")
            return False

        db.delete(conn)
        db.commit()
        logger.info(f"[source_registry] 数据库连接硬删除（无数据）: {connection_id}")
        return True

    def restore(self, db: Session, connection_id: str) -> None:
        conn = self.get(db, connection_id)
        if not conn or not conn.is_deleted:
            raise ValueError(f"已删除的连接不存在: {connection_id}")
        conn.is_deleted = False
        conn.deleted_at = None
        conn.updated_at = datetime.now()
        db.commit()
        logger.info(f"[source_registry] 数据库连接已恢复: {connection_id}")

    def has_persisted_data(self, db: Session, connection_id: str) -> bool:
        """该连接是否已有 Schema 或概要产出（Schema 落库判定 + 摘要目录判定）"""
        from models.database import DatabaseTable
        if db.query(DatabaseTable).filter(
                DatabaseTable.connection_id == connection_id).first() is not None:
            return True

        summary_dir = os.path.join(_data_dir(), "summaries", "DBS", connection_id)
        return os.path.isdir(summary_dir) and bool(os.listdir(summary_dir))

    # ── 连通性 ──

    def test(self, db: Session, connection_id: str) -> bool:
        conn = self.require(db, connection_id)
        from content_extraction.database.connector import create_engine_for
        return test_engine(create_engine_for(_conn_dict(conn)))

    def test_config(self, config: Dict) -> bool:
        """试连配置（创建前测试，不落库；未指定库名用裸引擎）"""
        from content_extraction.database.connector import create_engine_for, create_bare_engine_for
        engine = (create_engine_for(config) if config.get("database")
                  else create_bare_engine_for(config))
        return test_engine(engine)

    def list_databases(self, db: Session, connection_id: str) -> List[str]:
        import os as _os
        conn = self.require(db, connection_id)
        cfg = _conn_dict(conn)
        db_type = (cfg.get("type") or "").lower()

        if db_type == "sqlite":
            path = cfg.get("database") or ""
            return [_os.path.basename(path) if path else "default"]
        if db_type == "oracle":
            svc = cfg.get("service_name") or cfg.get("database") or "ORCL"
            return [svc]

        from content_extraction.database.connector import create_bare_engine_for
        engine = create_bare_engine_for(cfg)
        if not engine:
            raise ValueError("无法创建数据库引擎")

        from sqlalchemy import text
        system_dbs = {
            "mysql": {"information_schema", "mysql", "performance_schema", "sys"},
            "mssql": {"master", "tempdb", "model", "msdb"},
        }
        try:
            with engine.connect() as engine_conn:
                if db_type == "mysql":
                    rows = engine_conn.execute(text("SHOW DATABASES")).fetchall()
                    sys = system_dbs["mysql"]
                    return [r[0] for r in rows if r[0].lower() not in sys]
                if db_type == "postgresql":
                    rows = engine_conn.execute(
                        text("SELECT datname FROM pg_database WHERE datistemplate = false")
                    ).fetchall()
                    return [r[0] for r in rows]
                if db_type == "mssql":
                    rows = engine_conn.execute(text("SELECT name FROM sys.databases")).fetchall()
                    sys = system_dbs["mssql"]
                    return [r[0] for r in rows if r[0].lower() not in sys]
            return []
        except Exception as e:
            logger.error(f"[source_registry] 获取数据库列表失败: {e}")
            raise

    def merge_databases_with_status(self, live_databases: list,
                                    analyzed_databases: list) -> list:
        """实时库列表与已分析记录合并 → [{name, status}]"""
        analyzed_names = {ad["database_name"] for ad in analyzed_databases}
        live_set = set(live_databases)
        result = [{"name": db, "status": DB_STATUS_EXTRACTED if db in analyzed_names else None}
                  for db in live_databases]
        result.extend({"name": ad["database_name"], "status": DB_STATUS_DELETED}
                      for ad in analyzed_databases if ad["database_name"] not in live_set)
        return result


def dict_from_connection(conn) -> Dict:
    """连接 ORM 对象/字典 → 统一 dict 配置（跨组件契约）"""
    if isinstance(conn, dict):
        return conn
    return {
        "type": conn.type,
        "host": conn.host,
        "port": conn.port,
        "database": conn.database,
        "username": conn.username,
        "password": conn.password,
        "service_name": getattr(conn, "service_name", None),
    }


def _conn_dict(conn) -> Dict:
    return dict_from_connection(conn)


def test_engine(engine) -> bool:
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"[source_registry] 连接测试失败: {e}")
        return False


def _data_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "data")


database_source_registry = DatabaseSourceRegistry()
