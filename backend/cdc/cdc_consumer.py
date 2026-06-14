"""
CDC Consumer — 从 Redis Streams 消费 Debezium 变更事件，同步到 Neo4j
"""
import json
import threading
import time
from typing import Optional

import redis

from cdc.schema_cache import SchemaCache
from cdc.event_processor import EventProcessor
from config.database import SessionLocal
from models.cdc import CdcSyncState
from system.logger import logger


class CDCConsumer:
    """单个数据库连接的 CDC Consumer（后台线程）"""

    def __init__(
        self,
        connection_id: str,
        database_name: str,
        redis_host: str = "127.0.0.1",
        redis_port: int = 6379,
        topic_prefix: str = "openpalantir",
    ):
        self.connection_id = connection_id
        self.database_name = database_name
        self.topic_prefix = topic_prefix

        # 状态控制：使用 threading.Event 保证线程安全的停止信号
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Redis 客户端
        self._redis = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)

        # Schema 缓存
        self.schema = SchemaCache(connection_id, database_name)

        # 事件处理器
        self.processor: Optional[EventProcessor] = None

        # 统计
        self.events_processed = 0
        self.last_message_id: Optional[str] = None
        self.last_event_ts: Optional[int] = None

    @property
    def is_running(self) -> bool:
        return not self._stop_event.is_set() and self._thread is not None and self._thread.is_alive()

    def start(self):
        """启动消费线程"""
        if self.is_running:
            logger.warning(f"[CDC] Consumer 已在运行: conn={self.connection_id}")
            return

        # 加载 Schema 缓存
        self.schema.load()
        self.processor = EventProcessor(self.schema, self.connection_id, self.database_name)

        # 加载断点续传状态
        self._load_checkpoint()

        # 确保 Redis Consumer Group 存在
        self._ensure_consumer_groups()

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._consume_loop,
            name=f"cdc-{self.connection_id[:8]}",
            daemon=True,
        )
        self._thread.start()

        self._update_status("running")
        logger.info(f"[CDC] Consumer 已启动: conn={self.connection_id}, db={self.database_name}")

    def request_stop(self):
        """请求停止（等待当前批次完成后退出）"""
        self._stop_event.set()

    def join(self, timeout: float = 30.0):
        """等待线程结束"""
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        if self._thread and not self._thread.is_alive():
            self._update_status("stopped")
            logger.info(f"[CDC] Consumer 已停止: conn={self.connection_id}")

    # ─────────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────────

    def _ensure_consumer_groups(self):
        """确保每个 Stream 上的 Consumer Group 已创建"""
        consumer_group = self._group_name
        stream_keys = self.schema.get_stream_keys(self.topic_prefix)

        for key in stream_keys:
            try:
                # id="$" 表示只处理创建 Consumer Group 之后的新消息。
                # 全量导入已覆盖历史数据，无需重放 Stream 中的旧消息。
                # MKSTREAM 参数在 XGROUP CREATE 中可用（Redis 6.2+）
                self._redis.xgroup_create(key, consumer_group, id="$", mkstream=True)
            except redis.exceptions.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    # BUSYGROUP = group already exists，正常情况
                    logger.warning(f"[CDC] 创建 Consumer Group 失败 ({key}): {e}")

    @property
    def _group_name(self) -> str:
        return f"openpalantir-{self.connection_id}"

    def _consume_loop(self):
        """主消费循环（后台线程）"""
        consumer_group = self._group_name
        consumer_name = "worker-1"
        stream_keys = self.schema.get_stream_keys(self.topic_prefix)
        stream_dict = {key: ">" for key in stream_keys}

        logger.info(f"[CDC] 开始消费循环，订阅 {len(stream_keys)} 个 Stream")

        consecutive_errors = 0
        max_backoff = 30  # 最大退避秒数

        while not self._stop_event.is_set():
            try:
                messages = self._redis.xreadgroup(
                    groupname=consumer_group,
                    consumername=consumer_name,
                    streams=stream_dict,
                    count=100,
                    block=3000,  # 阻塞等待 3 秒
                )

                if not messages:
                    consecutive_errors = 0
                    continue

                for stream_name, entries in messages:
                    if not entries:
                        continue

                    last_id_in_batch = None
                    for msg_id, data in entries:
                        if self._stop_event.is_set():
                            # 收到停止信号：不处理剩余消息（留在 PENDING，下次重启时重发）
                            break

                        try:
                            event = self._parse_event(data)
                            if event:
                                result = self.processor.process_event(event)
                                self.events_processed += 1
                                ts_ms = event.get("ts_ms")
                                if ts_ms:
                                    self.last_event_ts = ts_ms
                        except Exception as e:
                            logger.error(f"[CDC] 处理事件失败 (msg_id={msg_id}): {e}")
                            # 继续处理下一条，不阻塞整个流

                        # 每条消息立即 ACK（操作已幂等）
                        self._redis.xack(stream_name, consumer_group, msg_id)
                        last_id_in_batch = msg_id

                    # 批次完成后更新检查点
                    if last_id_in_batch:
                        self.last_message_id = last_id_in_batch
                        self._save_checkpoint()

                consecutive_errors = 0

            except redis.exceptions.ConnectionError:
                consecutive_errors += 1
                backoff = min(2 ** consecutive_errors, max_backoff)
                logger.warning(f"[CDC] Redis 连接断开，{backoff}秒后重试 (错误次数={consecutive_errors})")
                time.sleep(backoff)

            except Exception as e:
                consecutive_errors += 1
                backoff = min(2 ** consecutive_errors, max_backoff)
                logger.error(f"[CDC] 消费循环异常: {e}，{backoff}秒后重试")
                self._update_status("error", str(e))
                time.sleep(backoff)

        # 循环退出：保存最终检查点
        self._save_checkpoint()
        logger.info(f"[CDC] 消费循环结束，共处理 {self.events_processed} 条事件")

    def _parse_event(self, data: dict) -> Optional[dict]:
        """解析 Redis Streams 消息中的 Debezium 事件"""
        # Debezium Server 写入 Redis Streams 时，payload 可能在 "payload" 或 "value" 字段
        payload_str = data.get("payload") or data.get("value")
        if not payload_str:
            return None

        try:
            payload = json.loads(payload_str)
            # Debezium 2.x 格式：外层有 schema + payload
            if "payload" in payload:
                return payload["payload"]
            return payload
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"[CDC] 事件解析失败: {e}")
            return None

    def _load_checkpoint(self):
        """从 SQLite 加载断点续传状态"""
        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=self.connection_id, database_name=self.database_name)
                .first()
            )
            if state:
                self.events_processed = state.events_processed or 0
                self.last_message_id = state.last_message_id
                self.last_event_ts = state.last_event_ts
                logger.info(
                    f"[CDC] 加载检查点: events={self.events_processed}, "
                    f"last_msg_id={self.last_message_id}"
                )
        finally:
            db.close()

    def _save_checkpoint(self):
        """保存检查点到 SQLite"""
        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=self.connection_id, database_name=self.database_name)
                .first()
            )
            if state:
                state.last_message_id = self.last_message_id
                state.last_event_ts = self.last_event_ts
                state.events_processed = self.events_processed
                db.commit()
        except Exception as e:
            logger.error(f"[CDC] 保存检查点失败: {e}")
            db.rollback()
        finally:
            db.close()

    def _update_status(self, status: str, error: str = None):
        """更新 CDC 状态到 SQLite"""
        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=self.connection_id, database_name=self.database_name)
                .first()
            )
            if state:
                state.status = status
                if error:
                    state.last_error = error
                elif status == "running":
                    state.last_error = None
                db.commit()
        except Exception as e:
            logger.error(f"[CDC] 更新状态失败: {e}")
            db.rollback()
        finally:
            db.close()
