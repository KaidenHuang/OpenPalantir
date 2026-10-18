from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 后端项目根目录（config/ 的父目录）
BACKEND_DIR = Path(__file__).resolve().parent.parent

# 数据库配置 — 路径始终相对于 backend/ 目录，避免从根目录启动时误创建 data/sqlite
_default_db_path = BACKEND_DIR / "data" / "sqlite" / "database.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_default_db_path}")

# 确保SQLite数据库目录存在
if "sqlite" in DATABASE_URL:
    db_path = DATABASE_URL.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_path)
    os.makedirs(db_dir, exist_ok=True)

# 创建数据库引擎
_sqlite_connect_args = {"check_same_thread": False, "timeout": 30} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=_sqlite_connect_args)

# SQLite 并发写防护：多线程（任务调度/CDC 消费/记忆 worker/FastAPI 线程池）同时写，
# 必须启用 WAL + busy_timeout，否则 "database is locked" 是必然结局。
if "sqlite" in DATABASE_URL:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建基类
Base = declarative_base()

# 依赖项
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_session():
    """提供自动管理的数据库会话（自动 commit/rollback/close）。

    用法：
        with get_session() as db:
            service.get_model(db, model_id)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
