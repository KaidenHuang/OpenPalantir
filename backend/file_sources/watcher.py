"""
文档源监听 —— 轮询内容指纹，自动派发刷新任务

与 CDC 对称：CDC 管数据库行级增量，这里管文档级增量。默认关闭，
设 DOC_WATCH_ENABLED=1 启用；同一文档同时只保留一个在途刷新任务。
"""
import os
import threading
from typing import Dict, List, Optional

from system.logger import logger

DEFAULT_INTERVAL = 60
_FINISHED = ("completed", "failed")


class DocumentWatcher:
    def __init__(self, interval: Optional[int] = None):
        if interval is None:
            interval = int(os.getenv("DOC_WATCH_INTERVAL", str(DEFAULT_INTERVAL)))
        self.interval = max(5, interval)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._inflight: Dict[str, str] = {}

    def start(self) -> bool:
        """启动监听线程；已在运行时返回 False"""
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="document-watcher")
        self._thread.start()
        logger.info(f"[watch] 文档监听已启动，间隔 {self.interval}s")
        return True

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread and thread.is_alive():
            thread.join(timeout=3)
        self._inflight.clear()
        logger.info("[watch] 文档监听已停止")

    def poll_once(self) -> List[Dict[str, str]]:
        """扫描一次并派发刷新任务，返回派发结果（供测试与手动触发复用）"""
        from document_processing import summary_generator
        from source_management import refresh_service
        from task_management.task_manager import task_manager

        self._prune(task_manager)

        dispatched = []
        for item in refresh_service.scan_stale():
            datasource = summary_generator.datasource_for(item["source_id"], item["file_path"])
            if datasource in self._inflight:
                continue
            task_id = task_manager.create_task("document_refresh", {
                "source_id": item["source_id"],
                "file_path": item["file_path"],
                "domain": "general",
            })
            self._inflight[datasource] = task_id
            logger.info(f"[watch] 派发刷新: {datasource} ({item['reason']}) → {task_id}")
            dispatched.append({"datasource": datasource, "task_id": task_id,
                               "reason": item["reason"]})
        return dispatched

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as e:
                logger.warning(f"[watch] 轮询失败（下一轮重试）: {e}")
            self._stop.wait(self.interval)

    def _prune(self, task_manager) -> None:
        for datasource, task_id in list(self._inflight.items()):
            task = task_manager.get_task(task_id)
            if task is None or task.status in _FINISHED:
                self._inflight.pop(datasource, None)

    @property
    def inflight(self) -> Dict[str, str]:
        return dict(self._inflight)


document_watcher = DocumentWatcher()
