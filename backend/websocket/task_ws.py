"""
WebSocket 任务状态推送 — 广播任务进度和状态变更给所有连接的客户端。
"""
import asyncio
import json
from typing import List

from fastapi import WebSocket
from system.logger import logger


class TaskWSManager:
    """管理 WebSocket 连接并广播任务更新"""

    def __init__(self):
        self._connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._connections.append(websocket)
        logger.info(f"[ws] 客户端连接，当前连接数: {len(self._connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self._connections:
            self._connections.remove(websocket)
        logger.info(f"[ws] 客户端断开，当前连接数: {len(self._connections)}")

    async def broadcast(self, data: dict):
        """向所有连接的客户端广播消息"""
        if not self._connections:
            return
        message = json.dumps(data, ensure_ascii=False)
        stale = []
        for conn in self._connections:
            try:
                await conn.send_text(message)
            except Exception:
                stale.append(conn)
        for conn in stale:
            self.disconnect(conn)

    def broadcast_sync(self, data: dict):
        """同步接口 — 在后台线程中调度广播（供 task_manager 调用）"""
        if not self._connections:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.broadcast(data))
            else:
                loop.run_until_complete(self.broadcast(data))
        except Exception as e:
            logger.warning(f"[ws] 同步广播失败: {e}")


# 全局单例
task_ws_manager = TaskWSManager()
