from typing import Any, Callable, Dict

from system.logger import logger

from .base import TaskHandler


class CdcStartHandler(TaskHandler):
    """启动 CDC 增量同步——任务常驻 running，直到任务管理点「停止」"""

    def execute(self, task, progress_callback: Callable[[int], None]) -> Dict:
        import time
        from cdc.cdc_manager import cdc_manager
        from config.database import SessionLocal
        from models.cdc import CdcSyncState

        connection_id = task.payload.get("connection_id")
        database_name = task.payload.get("database_name")

        logger.info(
            f"[CdcStartHandler] 入参: task_id={task.task_id}, "
            f"connection_id={connection_id}, database_name={database_name}"
        )

        if not connection_id or not database_name:
            raise ValueError("缺少 connection_id 或 database_name")

        progress_callback(10)

        # 前置检查1：是否已完成全量导入
        db = SessionLocal()
        try:
            state = (
                db.query(CdcSyncState)
                .filter_by(connection_id=connection_id, database_name=database_name)
                .first()
            )
            if not state or (not state.binlog_file and not state.wal_lsn):
                raise ValueError(
                    "尚未完成全量导入，无法启动增量同步。请先点击「导入图谱」完成全量导入。"
                )
        finally:
            db.close()

        progress_callback(30)

        # 前置检查2：断流检测
        gap = cdc_manager.check_stream_continuity(connection_id, database_name)
        if gap.get("has_gap"):
            raise ValueError(gap["message"])

        progress_callback(50)

        # 启动 CDC
        result = cdc_manager.start(connection_id, database_name)

        # 若已在运行，任务直接完成（不进入常驻循环）
        if result["status"] == "already_running":
            task.result = {"status": "already_running", "message": result["message"]}
            logger.info(f"[CdcStartHandler] 增量同步已在运行: {result['message']}")
            return task.result

        # 已 started：常驻 running，轮询停止信号
        task.result = {
            "status": "running",
            "message": "增量同步运行中，停止请到「任务管理」",
            "connection_id": connection_id,
            "database_name": database_name,
        }
        logger.info(
            f"[CdcStartHandler] 增量同步已启动，任务常驻运行: "
            f"conn={connection_id}, db={database_name}"
        )

        progress_callback(90)

        # 阻塞等待停止信号（零 CPU 开销，由 stop_task() 触发 Event.set()）
        task.stop_event.wait()

        # 被停止：清理 CDCConsumer
        try:
            cdc_manager.stop(connection_id, database_name)
        except Exception as e:
            logger.error(f"[CdcStartHandler] 停止 CDC 失败: {e}")
        task.result = {"status": "stopped", "message": "增量同步已停止"}
        logger.info(
            f"[CdcStartHandler] 增量同步已停止: conn={connection_id}, db={database_name}"
        )
        return task.result