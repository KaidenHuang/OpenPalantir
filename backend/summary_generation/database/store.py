"""③ 摘要生成（数据库侧）—— 库/表概要 JSON 的统一存取

协定目录 data/summaries/DBS/{connection_id}/{db_name}.json，与历史布局一致；
概要结构：{db_name, db_description, business_domain, key_entities, table_count, structure[]}。
"""
import json
import os

from system.logger import logger

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SUMMARY_ROOT = os.path.join(BACKEND_DIR, "data", "summaries", "DBS")


def summary_dir(connection_id: str) -> str:
    return os.path.join(SUMMARY_ROOT, connection_id)


def summary_path(connection_id: str, db_name: str) -> str:
    return os.path.join(summary_dir(connection_id), f"{db_name or 'database_summary'}.json")


def save(connection_id: str, db_name: str, data: dict) -> str:
    path = summary_path(connection_id, db_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"[summary][database] 数据库概要已保存: {path}")
    return path


def load(connection_id: str, db_name: str = None) -> dict:
    """读取数据库概要；db_name 缺省时按连接配置库名解析（供路由直读）"""
    if db_name is None:
        from config.database import SessionLocal
        from source_registry.database.registry import database_source_registry

        db = SessionLocal()
        try:
            conn = database_source_registry.get(db, connection_id)
        finally:
            db.close()
        db_name = conn.database if conn else None
        if not db_name:
            return {}
    path = summary_path(connection_id, db_name)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def has_data(connection_id: str) -> bool:
    d = summary_dir(connection_id)
    return os.path.isdir(d) and bool(os.listdir(d))
