"""
CDC Manager — 管理所有活跃的 CDC Consumer 实例
"""
import os
import threading
from typing import Dict, Optional

import redis

from cdc.cdc_consumer import CDCConsumer
from config.database import SessionLocal
from models.cdc import CdcSyncState
from system.logger import logger


class CDCManager:
    """管理所有 CDC Consumer 的生命周期"""

    def __init__(self):
        self._consumers: Dict[str, CDCConsumer] = {}  # key: "{connection_id}:{database_name}"
        self._lock = threading.Lock()

        self._redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
        self._redis_port = int(os.getenv("REDIS_PORT", "6379"))

    def _make_key(self, connection_id: str, database_name: str) -> str:
        return f"{connection_id}:{database_name}"

    def start(
        self,
        connection_id: str,
        database_name: str,
    ) -> Dict:
        """启动指定连接的 CDC Consumer"""
        key = self._make_key(connection_id, database_name)

        # topic_prefix + connector_type 按连接隔离（从 CdcSyncState 解析）
        topic_prefix = self._resolve_topic_prefix(connection_id)
        connector_type = self._resolve_connector_type(connection_id)

        with self._lock:
            if key in self._consumers and self._consumers[key].is_running:
                return {"status": "already_running", "message": "增量同步已在运行"}

            # 确保 CdcSyncState 记录存在
            self._ensure_state(connection_id, database_name)

            # 创建并启动 Consumer
            consumer = CDCConsumer(
                connection_id=connection_id,
                database_name=database_name,
                redis_host=self._redis_host,
                redis_port=self._redis_port,
                topic_prefix=topic_prefix,
                connector_type=connector_type,
            )
            consumer.start()
            self._consumers[key] = consumer

        return {"status": "started", "message": "增量同步已启动"}

    def stop(self, connection_id: str, database_name: str) -> Dict:
        """优雅停止指定连接的 CDC Consumer"""
        key = self._make_key(connection_id, database_name)

        with self._lock:
            consumer = self._consumers.get(key)
            if not consumer or not consumer.is_running:
                return {"status": "not_running", "message": "增量同步未在运行"}

            consumer.request_stop()

        # 在锁外等待线程结束（避免死锁）
        consumer.join(timeout=30)

        with self._lock:
            if key in self._consumers:
                del self._consumers[key]

        return {"status": "stopped", "message": "增量同步已停止"}

    def pause(self, connection_id: str, database_name: str) -> Dict:
        """暂停增量同步（等同于 stop + 状态标记为 paused）"""
        result = self.stop(connection_id, database_name)
        if result["status"] == "stopped":
            self._set_status(connection_id, database_name, "paused")
            result["status"] = "paused"
            result["message"] = "增量同步已暂停"
        return result

    def get_status(self, connection_id: str, database_name: str) -> Optional[Dict]:
        """查询同步状态"""
        key = self._make_key(connection_id, database_name)

        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=connection_id, database_name=database_name)
                .first()
            )
            if not state:
                return None

            result = state.to_dict()

            # 如果内存中有活跃的 Consumer，使用实时数据
            consumer = self._consumers.get(key)
            if consumer and consumer.is_running:
                result["status"] = "running"
                result["events_processed"] = consumer.events_processed
                result["last_message_id"] = consumer.last_message_id
                result["last_event_ts"] = consumer.last_event_ts

            return result
        finally:
            db.close()

    def get_all_statuses(self) -> list:
        """获取所有 CDC 同步状态"""
        db = SessionLocal()
        try:
            states = db.query(CdcSyncState).all()
            results = []
            for state in states:
                result = state.to_dict()
                key = self._make_key(state.connection_id, state.database_name)
                consumer = self._consumers.get(key)
                if consumer and consumer.is_running:
                    result["status"] = "running"
                    result["events_processed"] = consumer.events_processed
                results.append(result)
            return results
        finally:
            db.close()

    def check_stream_continuity(
        self, connection_id: str, database_name: str
    ) -> Dict:
        """检测停机期间是否有事件断层"""
        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=connection_id, database_name=database_name)
                .first()
            )
            if not state or not state.last_message_id:
                return {"has_gap": False, "message": "无历史检查点，可直接启动"}

            last_id = state.last_message_id
            r = redis.Redis(host=self._redis_host, port=self._redis_port, decode_responses=True, protocol=2)
            try:
                # 检查所有相关 Stream 中最旧的消息（用连接级 topic_prefix，避免检查错误的 stream）
                from cdc.schema_cache import SchemaCache
                schema = SchemaCache(connection_id, database_name)
                schema.load()
                stream_keys = schema.get_stream_keys(self._resolve_topic_prefix(connection_id))

                for key in stream_keys:
                    try:
                        oldest = r.xrange(key, count=1)
                        if oldest:
                            oldest_id = oldest[0][0]
                            # Redis Stream ID 格式: "timestamp-seq"，可直接字符串比较
                            if oldest_id > last_id:
                                return {
                                    "has_gap": True,
                                    "message": (
                                        f"Stream {key} 中最旧消息 ({oldest_id}) 比上次处理位点 "
                                        f"({last_id}) 更新，存在事件断层。建议重新执行全量导入。"
                                    ),
                                }
                        elif last_id:
                            # Stream 存在但为空（可能被 XTRIM 清空），且有历史检查点 → 断层
                            return {
                                "has_gap": True,
                                "message": (
                                    f"Stream {key} 已被清空（无消息），但上次处理位点为 "
                                    f"({last_id})，存在事件断层。建议重新执行全量导入。"
                                ),
                            }
                    except redis.exceptions.ResponseError:
                        continue  # Stream 不存在

                return {"has_gap": False, "message": "Stream 数据连续，可安全恢复"}
            finally:
                r.close()

        finally:
            db.close()

    def shutdown_all(self):
        """关闭所有 Consumer（应用退出时调用）"""
        logger.info("[CDC] 正在关闭所有 Consumer...")
        with self._lock:
            consumers = list(self._consumers.values())

        for consumer in consumers:
            consumer.request_stop()

        for consumer in consumers:
            consumer.join(timeout=10)

        with self._lock:
            self._consumers.clear()

        logger.info("[CDC] 所有 Consumer 已关闭")

    def save_binlog_checkpoint(
        self,
        connection_id: str,
        database_name: str,
        binlog_info: Dict,
    ):
        """全量导入完成后保存 binlog 位点（供 Debezium 启动使用）"""
        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=connection_id, database_name=database_name)
                .first()
            )
            if not state:
                state = CdcSyncState(
                    connection_id=connection_id,
                    database_name=database_name,
                    status="idle",
                )
                db.add(state)

            state.binlog_file = binlog_info.get("file")
            state.binlog_position = binlog_info.get("position")
            state.wal_lsn = binlog_info.get("wal_lsn")
            state.status = "idle"
            # 回填连接级隔离配置（兼容旧记录与全量导入先于 configure 的场景）
            if not state.topic_prefix:
                state.topic_prefix = self._resolve_topic_prefix(connection_id)
            if not state.connector_type:
                state.connector_type = (
                    "postgresql" if binlog_info.get("wal_lsn") else "mysql"
                )
            # 重导 = 全新起点：清零运行态与消费进度。否则旧 last_message_id 会让
            # check_stream_continuity 误判断层，导致重导后仍无法启动 CDC。
            state.last_message_id = None
            state.events_processed = 0
            state.last_event_ts = None
            state.last_error = None
            db.commit()

            logger.info(
                f"[CDC] 保存 binlog 检查点: conn={connection_id}, db={database_name}, "
                f"info={binlog_info}"
            )

            # snapshot.mode=no_data 模式下，Debezium 自管 schema history 与 offset
            # （首次启动做 schema 快照建立 history 并记录位点），无需 Python 写 offsets.dat——
            # 否则会与 Debezium 的周期性 flush 互相覆盖（offset 战争）。
            # 此处仅保留 CdcSyncState 记录（CDCConsumer 断点续传用 last_message_id）。
        except Exception as e:
            logger.error(f"[CDC] 保存 binlog 检查点失败: {e}")
            db.rollback()
        finally:
            db.close()

    def _write_debezium_offset(self, binlog_info: Dict, topic_prefix: str):
        """将 binlog 位点写入 Debezium offsets.dat（MySQL 专用）。

        独立 try/except：写入失败不影响已保存的 CdcSyncState 检查点与全量导入结果，
        仅记录 warning——增量同步启动前需确保 offsets.dat 正确。
        """
        binlog_file = binlog_info.get("file")
        binlog_pos = binlog_info.get("position")
        if not binlog_file or not binlog_pos:
            return  # 非 MySQL 或无位点，跳过
        try:
            from cdc.offset_store import write_debezium_offset
            write_debezium_offset(binlog_file, int(binlog_pos), topic_prefix=topic_prefix)
        except Exception as e:
            logger.warning(
                f"[CDC] 写入 Debezium offsets.dat 失败（不影响全量导入）: {e}"
            )

    def configure_connection(self, connection_id: str) -> Dict:
        """为已添加的 MySQL 数据源一键配置 CDC。

        编排：读连接配置 → 校验 MySQL → 建 cdc_user（含 binlog 前置检测）→
        写 application.properties → 停止 Debezium → 清理旧库残留位点 → 启动 Debezium。
        任一致命步骤失败即停止并返回 failed，便于前端定位。
        """
        from database_management.database_service import DatabaseService
        from cdc.debezium_config import (
            CDC_PASSWORD,
            CDC_USER,
            clear_debezium_state,
            create_instance_layout,
            ensure_cdc_user,
            render_application_properties,
            write_application_properties,
        )

        steps = []

        # 1. 读取连接配置
        db = SessionLocal()
        try:
            db_service = DatabaseService()
            conn = db_service.get_connection(db, connection_id)
        finally:
            db.close()

        if not conn:
            raise ValueError(f"连接不存在: {connection_id}")
        db_type = (conn.type or "").lower()
        if db_type not in ("mysql", "postgresql"):
            raise ValueError(f"CDC 配置仅支持 MySQL/PostgreSQL，当前连接类型: {conn.type}")
        if not conn.database:
            raise ValueError("该连接未选择目标数据库，请先在数据库管理页面选定一个库")

        conn_config = {
            "type": conn.type,
            "host": conn.host,
            "port": conn.port,
            "username": conn.username,
            "password": conn.password,
            "database": conn.database,
        }

        # 2. 创建/赋权 cdc_user + 前置检测（MySQL binlog / PG wal_level）
        try:
            user_info = ensure_cdc_user(conn_config, connector_type=db_type)
            steps.append({
                "step": "create_cdc_user",
                "status": "ok",
                "message": f"已创建/赋权 {CDC_USER}",
                **user_info,
            })
        except Exception as e:
            logger.error(f"[CDC] 配置失败（建用户阶段）: {e}")
            return {"status": "failed", "step": "create_cdc_user", "message": str(e), "steps": steps}

        # 3. 创建实例目录 + 解析隔离配置 + 渲染写入 application.properties
        try:
            instance_path = create_instance_layout(connection_id)
            topic_prefix = self._resolve_topic_prefix(connection_id)
            redis_address = f"{self._redis_host}:{self._redis_port}"
            if db_type == "postgresql":
                server_id = None  # PG 用 replication slot，无 server.id
                content = render_application_properties(
                    host=conn.host, port=conn.port, database=conn.database,
                    user=CDC_USER, password=CDC_PASSWORD,
                    topic_prefix=topic_prefix, redis_address=redis_address,
                    connector_type="postgresql",
                )
            else:
                server_id = self._resolve_server_id(connection_id)
                content = render_application_properties(
                    host=conn.host, port=conn.port, database=conn.database,
                    user=CDC_USER, password=CDC_PASSWORD,
                    topic_prefix=topic_prefix, redis_address=redis_address,
                    connector_type="mysql", server_id=server_id,
                )
            config_path = write_application_properties(content, connection_id)
            # 持久化隔离配置到该 {conn,db} 的 CdcSyncState
            self._save_instance_config(connection_id, conn.database, topic_prefix, server_id, db_type)
            steps.append({
                "step": "write_config",
                "status": "ok",
                "message": f"实例目录就绪 + 配置写入（type={db_type}, topic.prefix={topic_prefix}, server.id={server_id}）",
                "config_path": config_path,
                "instance_path": instance_path,
            })
        except Exception as e:
            logger.error(f"[CDC] 配置失败（写配置阶段）: {e}")
            return {"status": "failed", "step": "write_config", "message": str(e), "steps": steps}

        # 4. 停止该实例 Debezium（必须在清理前停，避免运行实例周期性 flush 把旧 offsets.dat 写回）
        try:
            self._stop_debezium(connection_id)
            steps.append({"step": "stop", "status": "ok", "message": f"已停止实例 {connection_id[:8]} 的 Debezium"})
        except Exception as e:
            logger.error(f"[CDC] 停止 Debezium 失败: {e}")
            steps.append({"step": "stop", "status": "failed", "message": str(e)})
            return {"status": "failed", "step": "stop", "message": str(e), "steps": steps}

        # 5. 清理该实例旧残留位点（Debezium 已停，删除不会被 flush 覆盖；非致命）
        try:
            clear_debezium_state(self._redis_host, self._redis_port, topic_prefix, instance_id=connection_id)
            steps.append({"step": "clear_state", "status": "ok",
                          "message": f"已清理旧 offsets.dat / schema history（key={topic_prefix}）"})
        except Exception as e:
            logger.warning(f"[CDC] 清理旧状态失败（非致命）: {e}")
            steps.append({"step": "clear_state", "status": "warning", "message": str(e)})

        # 6. 启动该实例 Debezium，新配置生效
        try:
            self._start_debezium(connection_id)
            steps.append({"step": "start", "status": "ok", "message": f"实例 {connection_id[:8]} Debezium 已启动"})
        except Exception as e:
            logger.error(f"[CDC] 启动 Debezium 失败: {e}")
            steps.append({"step": "start", "status": "failed", "message": str(e)})
            return {"status": "failed", "step": "start", "message": str(e), "steps": steps}

        logger.info(f"[CDC] 连接 {connection_id} 配置完成")
        return {"status": "ok", "message": "CDC 配置完成", "steps": steps}

    def _stop_debezium(self, instance_id: str):
        """调用 stop-debezium 脚本停止指定实例的 Debezium（不碰 Neo4j/Redis）。"""
        self._run_debezium_script("stop-debezium", instance_id)

    def _start_debezium(self, instance_id: str):
        """调用 start-debezium 脚本启动指定实例的 Debezium（不碰 Neo4j/Redis）。"""
        self._run_debezium_script("start-debezium", instance_id)

    def _run_debezium_script(self, name: str, instance_id: str):
        """调用 scripts/service/ 下的 Debezium 管理脚本（按 instance_id）。

        根据操作系统自动选择解释器：Windows 用 PowerShell（.ps1），Linux 用 bash（.sh）。
        """
        import subprocess
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[2]
        if os.name == "nt":
            script = project_root / "scripts" / "service" / f"{name}.ps1"
            if not script.exists():
                raise FileNotFoundError(f"脚本不存在: {script}")
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(script), "-InstanceId", instance_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        else:
            script = project_root / "scripts" / "service" / f"{name}.sh"
            if not script.exists():
                raise FileNotFoundError(f"脚本不存在: {script}")
            result = subprocess.run(
                ["bash", str(script), instance_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        if result.returncode != 0:
            raise RuntimeError(f"脚本 {name} 返回非零退出码 {result.returncode}")

    # ─────────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────────

    def _resolve_topic_prefix(self, connection_id: str) -> str:
        """解析连接级 topic_prefix：优先用该连接任一 CdcSyncState 已存的；
        否则确定性生成 ``openpalantir.{connection_id前8位}``（同连接多库共享）。"""
        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=connection_id)
                .filter(CdcSyncState.topic_prefix.isnot(None))
                .first()
            )
            if state and state.topic_prefix:
                return state.topic_prefix
        finally:
            db.close()
        return f"openpalantir.{connection_id[:8]}"

    def _resolve_server_id(self, connection_id: str) -> int:
        """解析连接级 server_id：优先复用该连接已存的（保证重启后 slave 身份稳定）；
        否则随机生成 10000-99999（首次配置，由调用方持久化）。"""
        import random

        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=connection_id)
                .filter(CdcSyncState.server_id.isnot(None))
                .first()
            )
            if state and state.server_id:
                return state.server_id
        finally:
            db.close()
        return random.randint(10000, 99999)

    def _resolve_connector_type(self, connection_id: str) -> str:
        """解析连接的 connector_type（mysql/postgresql），默认 mysql。"""
        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=connection_id)
                .filter(CdcSyncState.connector_type.isnot(None))
                .first()
            )
            if state and state.connector_type:
                return state.connector_type
        finally:
            db.close()
        return "mysql"

    def _save_instance_config(
        self,
        connection_id: str,
        database_name: str,
        topic_prefix: str,
        server_id: int,
        connector_type: str,
    ):
        """把隔离配置写入该 {conn,db} 的 CdcSyncState（不存在则创建）。非致命。"""
        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=connection_id, database_name=database_name)
                .first()
            )
            if not state:
                state = CdcSyncState(
                    connection_id=connection_id,
                    database_name=database_name,
                    status="idle",
                )
                db.add(state)
            state.topic_prefix = topic_prefix
            state.server_id = server_id
            state.connector_type = connector_type
            db.commit()
        except Exception as e:
            logger.warning(f"[CDC] 持久化实例配置失败（非致命）: {e}")
            db.rollback()
        finally:
            db.close()

    def _ensure_state(self, connection_id: str, database_name: str):
        """确保 CdcSyncState 记录存在"""
        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=connection_id, database_name=database_name)
                .first()
            )
            if not state:
                state = CdcSyncState(
                    connection_id=connection_id,
                    database_name=database_name,
                    status="idle",
                )
                db.add(state)
                db.commit()
        finally:
            db.close()

    def _set_status(self, connection_id: str, database_name: str, status: str):
        """设置状态"""
        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=connection_id, database_name=database_name)
                .first()
            )
            if state:
                state.status = status
                db.commit()
        finally:
            db.close()


# 全局单例
cdc_manager = CDCManager()
