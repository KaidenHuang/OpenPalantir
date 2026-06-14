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
        topic_prefix: str = "openpalantir",
    ) -> Dict:
        """启动指定连接的 CDC Consumer"""
        key = self._make_key(connection_id, database_name)

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
            r = redis.Redis(host=self._redis_host, port=self._redis_port, decode_responses=True)
            try:
                # 检查所有相关 Stream 中最旧的消息
                from cdc.schema_cache import SchemaCache
                schema = SchemaCache(connection_id, database_name)
                schema.load()
                stream_keys = schema.get_stream_keys()

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
            db.commit()

            logger.info(
                f"[CDC] 保存 binlog 检查点: conn={connection_id}, db={database_name}, "
                f"info={binlog_info}"
            )
        except Exception as e:
            logger.error(f"[CDC] 保存 binlog 检查点失败: {e}")
            db.rollback()
        finally:
            db.close()

    # ─────────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────────

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
