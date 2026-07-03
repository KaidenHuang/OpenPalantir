"""
Debezium 配置生成与 CDC 前置准备。

把前端添加的 MySQL 数据源连接信息同步到 Debezium 的 ``application.properties``，
并自动创建/赋权 ``cdc_user``、清理旧库残留位点，使 CDC 真正针对该 MySQL 工作。

由 ``cdc_manager.configure_connection()`` 编排调用，对应前端「配置 CDC」按钮。
"""
import os
from pathlib import Path
from typing import Dict

from sqlalchemy import text

from system.logger import logger

# ── 路径常量（与 offset_store.py 同款：backend/cdc/xxx.py → 项目根上溯两级）──
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEBEZIUM_HOME = _PROJECT_ROOT / "dependencies" / "debezium" / "extracted"
DEBEZIUM_CONFIG_PATH = DEBEZIUM_HOME / "config" / "application.properties"
# 多实例：每 MySQL 连接一个独立 Debezium 运行目录（阶段 2）
DEBEZIUM_INSTANCES_HOME = _PROJECT_ROOT / "dependencies" / "debezium" / "instances"

# cdc_user 固定凭据（与 scripts/install/setup-cdc-user.sql 默认值一致），
# 建账号与写 Debezium 配置共用，用户无需输入。
CDC_USER = "cdc_user"
CDC_PASSWORD = "cdc_password"
DEFAULT_TOPIC_PREFIX = "openpalantir"


def render_application_properties(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    topic_prefix: str = DEFAULT_TOPIC_PREFIX,
    redis_address: str = "127.0.0.1:6379",
    connector_type: str = "mysql",
    server_id: int = None,
) -> str:
    """按 connector_type 渲染 application.properties（mysql/postgresql）。"""
    if connector_type == "postgresql":
        return _render_pg(host, port, database, user, password, topic_prefix, redis_address)
    return _render_mysql(host, port, database, user, password, server_id, topic_prefix, redis_address)


def _render_mysql(host, port, database, user, password, server_id, topic_prefix, redis_address) -> str:
    """MySQL connector 模板（database.include.list + server.id）。"""
    return f"""# ============================================================
# Debezium Server - mysql Connector
# ============================================================
# 本文件由 OpenPalantir「配置 CDC」自动生成，请勿手动编辑。
# 如需切换源库，请在数据库管理页面重新点击「配置 CDC」。
# ============================================================
# ---- Sink: 写入 Redis Streams ----
debezium.sink.type=redis
debezium.sink.redis.address={redis_address}
debezium.sink.redis.stream-type=stream

# ---- 快照模式 ----
# no_data = 首次启动只做 schema 快照（读当前表结构写入 schema history，不读数据、
# 不重放历史）并记录位点，之后从该位点捕获增量。避免空 schema history 导致从
# binlog 头重放整个历史撑爆内存。
debezium.source.snapshot.mode=no_data

# ---- 偏移量存储（Debezium 内部断点）----
debezium.source.offset.storage=org.apache.kafka.connect.storage.FileOffsetBackingStore
debezium.source.offset.storage.file.filename=data/debezium/offsets/offsets.dat
debezium.source.offset.flush.interval.ms=5000

# ---- 日志 ----
quarkus.log.level=INFO
quarkus.log.console.json=false
# ---- HTTP 端口（随机，避免多实例 Debezium 冲突；CDC 经 Redis stream 输出，不依赖 HTTP 管理）----
quarkus.http.port=0
# ---- Source: MySQL ----
debezium.source.connector.class=io.debezium.connector.mysql.MySqlConnector
debezium.source.database.hostname={host}
debezium.source.database.port={port}
debezium.source.database.user={user}
debezium.source.database.password={password}
debezium.source.database.connectionTimeZone=Asia/Shanghai
debezium.source.database.server.id={server_id}
debezium.source.topic.prefix={topic_prefix}
debezium.source.database.include.list={database}
# ---- Schema History（MySQL connector 必需，用 Redis 存储，避免依赖 Kafka）----
debezium.source.schema.history.internal=io.debezium.storage.redis.history.RedisSchemaHistory
debezium.source.schema.history.internal.redis.address={redis_address}
debezium.source.schema.history.internal.redis.key=schemahistory.{topic_prefix}
"""


def _render_pg(host, port, database, user, password, topic_prefix, redis_address) -> str:
    """PostgreSQL connector 模板（dbname + pgoutput + public.*，无 server.id）。"""
    return f"""# ============================================================
# Debezium Server - postgresql Connector
# ============================================================
# 本文件由 OpenPalantir「配置 CDC」自动生成，请勿手动编辑。
# ============================================================
# ---- Sink: 写入 Redis Streams ----
debezium.sink.type=redis
debezium.sink.redis.address={redis_address}
debezium.sink.redis.stream-type=stream

# ---- 快照模式 ----
# no_data = 首次启动只做 schema 快照（读当前表结构写入 schema history，不读数据、
# 不重放历史）并记录位点，之后从该位点捕获增量。
debezium.source.snapshot.mode=no_data

# ---- 偏移量存储（Debezium 内部断点）----
debezium.source.offset.storage=org.apache.kafka.connect.storage.FileOffsetBackingStore
debezium.source.offset.storage.file.filename=data/debezium/offsets/offsets.dat
debezium.source.offset.flush.interval.ms=5000

# ---- 日志 ----
quarkus.log.level=INFO
quarkus.log.console.json=false
quarkus.http.port=0
# ---- Source: PostgreSQL ----
debezium.source.connector.class=io.debezium.connector.postgresql.PostgresConnector
debezium.source.database.hostname={host}
debezium.source.database.port={port}
debezium.source.database.user={user}
debezium.source.database.password={password}
debezium.source.database.dbname={database}
debezium.source.topic.prefix={topic_prefix}
debezium.source.table.include.list=public.*
debezium.source.plugin.name=pgoutput
# ---- Schema History（用 Redis 存储）----
debezium.source.schema.history.internal=io.debezium.storage.redis.history.RedisSchemaHistory
debezium.source.schema.history.internal.redis.address={redis_address}
debezium.source.schema.history.internal.redis.key=schemahistory.{topic_prefix}
"""


def instance_dir(instance_id: str) -> Path:
    """实例运行根目录：dependencies/debezium/instances/{connection_id}"""
    return DEBEZIUM_INSTANCES_HOME / instance_id


def instance_config_path(instance_id: str) -> Path:
    return instance_dir(instance_id) / "config" / "application.properties"


def instance_offset_path(instance_id: str) -> Path:
    return instance_dir(instance_id) / "data" / "debezium" / "offsets" / "offsets.dat"


def instance_pid_path(instance_id: str) -> Path:
    return instance_dir(instance_id) / "debezium.pid"


def create_instance_layout(instance_id: str) -> str:
    """为实例创建独立运行目录：建子目录 + 复制 runner.jar/run.bat + 建 lib/connectors/config/lib 联接。

    幂等：已存在则跳过。run.bat 不改（cd /d %~dp0 + 相对路径在实例目录自适应）。
    返回实例根目录绝对路径。
    """
    import glob
    import shutil

    inst = instance_dir(instance_id)
    config_dir = inst / "config"
    (inst / "data" / "debezium" / "offsets").mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)

    # 复制 runner.jar（文件符号链接需管理员，故复制；jar 仅数百 KB）
    for runner in glob.glob(str(DEBEZIUM_HOME / "debezium-server-*runner.jar")):
        dst = inst / os.path.basename(runner)
        if not dst.exists():
            shutil.copy2(runner, dst)
    # 复制 run.bat
    run_bat = DEBEZIUM_HOME / "run.bat"
    if run_bat.exists() and not (inst / "run.bat").exists():
        shutil.copy2(run_bat, inst / "run.bat")

    # 目录联接（mklink /J，无需管理员）共享 lib/connectors/config/lib
    _ensure_junction(inst / "lib", DEBEZIUM_HOME / "lib")
    _ensure_junction(inst / "connectors", DEBEZIUM_HOME / "connectors")
    _ensure_junction(config_dir / "lib", DEBEZIUM_HOME / "config" / "lib")

    logger.info("[debezium_config] 实例目录就绪: %s", inst)
    return str(inst)


def _ensure_junction(link: Path, target: Path):
    """确保 link 是指向 target 的目录联接（mklink /J）。已存在则跳过。"""
    import subprocess

    if link.exists():
        return  # 联接或目录已存在
    if not target.exists():
        logger.warning("[debezium_config] 联接目标不存在，跳过: %s", target)
        return
    try:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, timeout=15, check=True,
        )
        logger.info("[debezium_config] 已建联接: %s -> %s", link.name, target)
    except Exception as e:
        logger.warning("[debezium_config] 建联接失败 %s: %s", link, e)


def write_application_properties(content: str, instance_id: str = None) -> str:
    """写入 application.properties（UTF-8 无 BOM，原子替换）。

    instance_id 非空时写入实例目录（多实例）；否则写入全局 DEBEZIUM_CONFIG_PATH（回退）。
    返回写入的绝对路径。
    """
    path = instance_config_path(instance_id) if instance_id else DEBEZIUM_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    logger.info("[debezium_config] 已写入 %s", path)
    return str(path)


def ensure_cdc_user(
    conn_config: Dict,
    cdc_user: str = CDC_USER,
    cdc_password: str = CDC_PASSWORD,
    connector_type: str = "mysql",
) -> Dict:
    """按 connector_type 用连接账号登录源库，创建/赋权 cdc 账号 + 前置检测。

    Args:
        conn_config: 含 type/host/port/username/password/database 的连接配置。
            username/password 必须是具建号权限的高权限账号（MySQL 需 GRANT，PG 需 SUPERUSER/CREATEROLE）。
        connector_type: "mysql" 或 "postgresql"。

    Returns:
        MySQL: ``{"binlog": {...}}``；PG: ``{"wal": {...}}``。
    """
    if connector_type == "postgresql":
        return _ensure_cdc_user_pg(conn_config, cdc_user, cdc_password)
    return _ensure_cdc_user_mysql(conn_config, cdc_user, cdc_password)


def _ensure_cdc_user_mysql(conn_config: Dict, cdc_user: str, cdc_password: str) -> Dict:
    """MySQL：创建/赋权 cdc_user（REPLICATION SLAVE/CLIENT）+ binlog 前置检测。"""
    # 延迟导入避免循环依赖
    from database_management.database_manager import database_manager

    engine = database_manager._create_bare_engine(conn_config)
    if engine is None:
        raise ValueError("无法连接源 MySQL，请检查连接配置（host/port/账号密码）")

    statements = [
        # IF NOT EXISTS 容错已存在；ALTER USER 保证密码与配置一致
        f"CREATE USER IF NOT EXISTS '{cdc_user}'@'%' IDENTIFIED BY '{cdc_password}'",
        f"ALTER USER '{cdc_user}'@'%' IDENTIFIED BY '{cdc_password}'",
        # Debezium MySQL connector 所需权限：SELECT 读表、RELOAD/SHOW DATABASES 元数据、
        # REPLICATION SLAVE/CLIENT 读 binlog（核心）
        f"GRANT SELECT, RELOAD, SHOW DATABASES, REPLICATION SLAVE, REPLICATION CLIENT "
        f"ON *.* TO '{cdc_user}'@'%'",
        "FLUSH PRIVILEGES",
    ]
    try:
        with engine.connect() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
            conn.commit()

            # 前置 binlog 检测：SHOW MASTER STATUS 为空说明 log_bin 未开，CDC 无法工作
            result = conn.execute(text("SHOW MASTER STATUS"))
            row = result.fetchone()
            if not row:
                raise ValueError(
                    "源 MySQL 未开启 binlog（SHOW MASTER STATUS 为空）。"
                    "请在 my.cnf 配置 log_bin=mysql-bin 与 server_id=<唯一整数>，"
                    "重启 MySQL 后再配置 CDC。"
                )
            cols = list(result.keys())
            data = dict(zip(cols, row))
            binlog = {"file": data.get("File", ""), "position": data.get("Position", 0)}
    except ValueError:
        raise
    except Exception as e:
        # GRANT 权限不足、密码策略不符等 → 转成可读错误
        raise ValueError(f"创建/赋权 cdc_user 失败（请确认连接账号具 GRANT 权限）: {e}")

    logger.info(
        "[debezium_config] cdc_user 已就绪，当前 binlog=%s:%s",
        binlog["file"], binlog["position"],
    )
    return {"binlog": binlog}


def _ensure_cdc_user_pg(conn_config: Dict, cdc_user: str, cdc_password: str) -> Dict:
    """PG：创建 cdc_user（REPLICATION 角色 + SELECT）+ wal_level=logical 前置检测。"""
    from database_management.database_manager import database_manager

    # PG 建号需连具体 dbname（GRANT 在库级）；conn_config.database 是目标库
    engine = database_manager._create_engine(conn_config)
    if engine is None:
        raise ValueError("无法连接源 PostgreSQL，请检查连接配置（host/port/dbname/账号密码）")

    # DO $$ 容错已存在；ALTER ROLE 保证密码与 REPLICATION 属性一致
    db_name = conn_config.get("database")
    statements = [
        f"DO $$ BEGIN "
        f"CREATE ROLE {cdc_user} WITH REPLICATION LOGIN PASSWORD '{cdc_password}'; "
        f"EXCEPTION WHEN duplicate_object THEN "
        f"ALTER ROLE {cdc_user} WITH REPLICATION LOGIN PASSWORD '{cdc_password}'; "
        f"END $$",
        # 建 logical replication slot 需 CREATE on database；CONNECT 兜底
        f"GRANT CONNECT, CREATE ON DATABASE {db_name} TO {cdc_user}",
        f"GRANT USAGE ON SCHEMA public TO {cdc_user}",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {cdc_user}",
        # 预建 publication（FOR ALL TABLES 需 SUPERUSER；cdc_user 非超管，由连接账号预建，
        # Debezium 默认 publication.name=dbz_publication，发现已存在则直接使用）
        f"DO $$ BEGIN CREATE PUBLICATION dbz_publication FOR ALL TABLES; "
        f"EXCEPTION WHEN duplicate_object THEN NULL; END $$",
    ]
    try:
        with engine.connect() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
            conn.commit()

            # 前置检测：wal_level 必须 logical 才能逻辑复制
            wal_level = conn.execute(text("SHOW wal_level")).scalar()
            if wal_level != "logical":
                raise ValueError(
                    f"PostgreSQL wal_level={wal_level}，需设为 logical 才能逻辑复制。"
                    "请在 postgresql.conf 设 wal_level=logical 后重启 PG 再配置 CDC。"
                )
            lsn = conn.execute(text("SELECT pg_current_wal_lsn()")).scalar()
            wal = {"wal_lsn": str(lsn) if lsn else ""}
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"创建 PG 复制账号失败（请确认连接账号具 SUPERUSER/CREATEROLE）: {e}")

    logger.info(
        "[debezium_config] PG cdc_user 已就绪，wal_level=logical, lsn=%s", wal["wal_lsn"]
    )
    return {"wal": wal}


def clear_debezium_state(
    redis_host: str,
    redis_port: int,
    topic_prefix: str = DEFAULT_TOPIC_PREFIX,
    instance_id: str = None,
):
    """切换源库时清理残留位点，确保新库干净起步。

    1. 删除旧 offsets.dat（实例目录或全局默认）；
    2. 删除 Redis 中的 schema history key（旧库 DDL 历史）。
    """
    # 1. offsets.dat：多实例用实例目录，否则复用 offset_store 默认路径
    if instance_id:
        offset_file = str(instance_offset_path(instance_id))
    else:
        from cdc.offset_store import _default_offset_file
        offset_file = _default_offset_file()
    if os.path.exists(offset_file):
        os.remove(offset_file)
        logger.info("[debezium_config] 已删除旧 offsets.dat: %s", offset_file)

    # 2. Redis schema history
    import redis

    key = f"schemahistory.{topic_prefix}"
    r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True, protocol=2)
    try:
        r.delete(key)
        logger.info("[debezium_config] 已清理 Redis schema history: %s", key)
    finally:
        r.close()
