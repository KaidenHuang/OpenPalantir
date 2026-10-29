import json
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from config.database import SessionLocal
from models.task import Task as TaskRow
from task_management.handlers import HANDLERS
from system.logger import logger
from system.metrics import TASK_DURATION

class Task:
    def __init__(self, task_id: str, task_type: str, payload: Dict[str, Any]):
        self.task_id = task_id
        self.task_type = task_type
        self.payload = payload
        self.status = "pending"  # pending, running, completed, failed
        self.progress = 0
        self.result = None
        self.error = None
        self.created_at = datetime.now().isoformat()
        self.started_at = None
        self.completed_at = None
        self.file_id = None
        self.stop_event = threading.Event()  # 用于 CDC 等长驻任务的通知式停止
        self.datasource_label: Optional[str] = None  # 「数据源」展示标签（list/detail 批量填充）
        self.datasource_uri: Optional[str] = None    # 「数据源 URL」展示值（同上，TYPE://ID 形式）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "payload": self.payload,
            "datasource_label": self.datasource_label,
            "datasource_uri": self.datasource_uri,
            "result": self.result,
            "progress": self.progress,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at
        }

def _apply_db_row(task: "Task", db_task) -> "Task":
    """任务行 → 内存对象的唯一翻译点（消灭五份逐字翻译样板）"""
    task.status = db_task.status
    task.progress = db_task.progress or 0
    task.result = db_task.result
    task.error = db_task.error
    task.created_at = db_task.create_time.isoformat() if db_task.create_time else None
    task.completed_at = db_task.complete_time.isoformat() if db_task.complete_time else None
    task.file_id = db_task.file_id
    return task


_TERMINAL_STATUSES = ("completed", "failed", "stopped")


def _payload_from_db_row(db_task) -> Dict[str, Any]:
    """payload 恢复唯一出口：优先持久化 JSON，兜底 file_id 记录的 document_id"""
    try:
        if db_task.payload:
            data = json.loads(db_task.payload)
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, TypeError):
        pass
    if db_task.file_id:
        return {"document_id": db_task.file_id}
    return {}


def _document_name_from_payload(payload: Dict[str, Any]) -> Optional[str]:
    """文档来源任务的展示名：从 payload 的位置字段（file_path/file）提取文件名"""
    file_path = payload.get("file_path") or payload.get("file")
    if not file_path:
        return None
    return os.path.basename(str(file_path).replace("\\", "/"))


def _wiki_name_from_payload(payload: Dict[str, Any]) -> Optional[str]:
    """Wiki 生成任务的展示名：DOC:// 数据源 URI 拆出目标文件名，实体场景返回 None"""
    datasource = payload.get("datasource")
    if isinstance(datasource, str) and datasource.startswith("DOC://"):
        parts = datasource.split("/")
        if len(parts) >= 3 and parts[-1]:
            return os.path.basename(parts[-1].replace("\\", "/"))
    return None


def _connection_alias_map() -> Dict[str, Dict[str, Optional[str]]]:
    """数据库连接别名映射：connection_id → {name, database}。

    一次批量查询（schema_import 等任务 payload 中无 database_name，需经连接记录补全）。
    """
    from config.database import SessionLocal
    from models.database import DatabaseConnection
    try:
        db = SessionLocal()
        try:
            rows = db.query(
                DatabaseConnection.id, DatabaseConnection.name, DatabaseConnection.database
            ).all()
            return {
                cid: {"name": name, "database": database}
                for cid, name, database in rows
            }
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[_connection_alias_map] 数据源映射查询失败: {str(e)}")
        return {}


def _document_source_alias_map() -> Dict[str, str]:
    """文档源别名映射：source_id → 注册名称。"""
    from config.database import SessionLocal
    from models.source import DocumentSource
    try:
        db = SessionLocal()
        try:
            rows = db.query(DocumentSource.id, DocumentSource.name).all()
            return {sid: name for sid, name in rows}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[_document_source_alias_map] 文档源映射查询失败: {str(e)}")
        return {}


def _datasource_uri_from_payload(payload: Dict[str, Any]) -> Optional[str]:
    """任务「数据源 URL」原始派生（ID 段为 SPI 内部 ID）：`{TYPE}://{ID}/...`。

    - Wiki 任务：payload 已携带 DOC:// 数据源 URI，原样透传
    - 文档单文件任务：DOC://{source_id}/{相对路径}
    - 文档批量任务（payload 带 files 键）：DOC://{source_id}
      （目标文件集合多而散，URI 只到源层面，明细看任务 result）
    - 数据库任务：DBS://{连接}[/{库名}]
    展示层由 _humanize_uri 把 ID 段替换为注册名称。
    """
    datasource = payload.get("datasource")
    if isinstance(datasource, str) and datasource.startswith("DOC://"):
        return datasource

    source_id = payload.get("source_id")
    file_path = payload.get("file_path") or payload.get("file")
    if source_id and file_path:
        return f"DOC://{source_id}/{file_path}"
    if source_id and "files" in payload:
        return f"DOC://{source_id}"

    connection_id = payload.get("connection_id")
    if connection_id:
        database_name = payload.get("database_name")
        return f"DBS://{connection_id}/{database_name}" if database_name else f"DBS://{connection_id}"
    return None
def _humanize_uri(uri: str, aliases: Dict[str, str]) -> str:
    """把数据源 URI 的 ID 段替换为注册名称（数据库名/文档源名），未知 ID 保留原值"""
    if not uri:
        return uri
    from models.resource_identifier import ResourceIdentifier
    try:
        parsed = ResourceIdentifier.parse(uri)
    except ValueError:
        return uri
    name = aliases.get(parsed.uuid)
    if not name:
        return uri
    return f"{parsed.type.value}://{name}/{parsed.path}" if parsed.path else f"{parsed.type.value}://{name}"


def _datasource_label_from_payload(
    payload: Dict[str, Any], conn_aliases: Optional[Dict[str, Dict[str, Optional[str]]]] = None,
    doc_aliases: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """任务「数据源」标签的唯一派生出口，按任务来源类型取值：
    - 文档批量任务（payload 带 files 键）→ 文档源名（N 个文件 / 全源）
    - 文档任务（file_path/file）→ 文件名
    - Wiki 任务（DOC:// datasource）→ 目标文件名
    - 数据库任务（connection_id）→ 库名（连接名）；库名只取任务创建时 payload 锁定的
      `database_name`，不回落到连接当前选中库（用户换库后标签会漂移）
    - 其他任务 → None（前端显示 '-'）
    """
    if payload.get("source_id") and "files" in payload:
        # 批量任务（单文件提取也走批量 handler，files=[path]）。
        # batch_label 由前端按「勾选语义」计算（如目录路径 / 已选 N 项），
        # 优先展示 —— payload 里的 files 是原始条目（可能含目录），条目数 ≠ 文件数
        custom = payload.get("batch_label")
        if isinstance(custom, str) and custom.strip():
            return custom.strip()
        files = payload.get("files")
        source_name = (doc_aliases or {}).get(payload.get("source_id")) or payload.get("source_id")
        if isinstance(files, list) and files:
            return f"{source_name}（{len(files)} 个文件）"
        return f"{source_name}（全源）"

    doc_name = _document_name_from_payload(payload)
    if doc_name:
        return doc_name

    wiki_name = _wiki_name_from_payload(payload)
    if wiki_name:
        return wiki_name

    connection_id = payload.get("connection_id")
    if not connection_id:
        return None
    conn = (conn_aliases or {}).get(connection_id, {})
    database_name = payload.get("database_name")
    conn_name = conn.get("name") or ""
    if database_name:
        return f"{database_name}（{conn_name}）" if conn_name else database_name
    return conn_name or None


class TaskManager:
    def __init__(self, max_concurrent_tasks: int = 5):
        self.tasks: Dict[str, Task] = {}
        self.task_queue: List[str] = []
        self.running_tasks: List[str] = []
        self.max_concurrent_tasks = max_concurrent_tasks
        self.lock = threading.Lock()
        self.worker_thread = threading.Thread(target=self._process_tasks, daemon=True)
        self.worker_thread.start()

        # 从数据库加载任务
        self._load_tasks()

    def _fill_datasource_labels(self, tasks: List["Task"]) -> None:
        """为一批任务批量解析「数据源」标签与 URL。

        一次性批量查询文档源/连接注册表的别名映射；URL 中的 ID 段替换为注册名称，
        数据库任务的库名取任务创建时 payload 锁定的 `database_name`。
        """
        conn_aliases = _connection_alias_map()
        aliases: Dict[str, str] = {cid: c["name"] for cid, c in conn_aliases.items() if c["name"]}

        doc_ids = {t.payload.get("source_id") for t in tasks if t.payload.get("source_id")}
        for t in tasks:
            datasource = t.payload.get("datasource")
            if isinstance(datasource, str) and datasource.startswith("DOC://"):
                parsed = datasource.split("/")
                if len(parsed) >= 3 and parsed[2]:
                    doc_ids.add(parsed[2])
        doc_ids.discard(None)
        if doc_ids:
            aliases.update(_document_source_alias_map())

        for task in tasks:
            task.datasource_label = _datasource_label_from_payload(task.payload, conn_aliases, aliases)
            uri = _datasource_uri_from_payload(task.payload)
            task.datasource_uri = _humanize_uri(uri, aliases) if uri else None

    def create_task(self, task_type: str, payload: Dict[str, Any]) -> str:
        """创建新任务（payload 契约在入口校验 —— 见 handlers/base.py）"""
        handler_cls = HANDLERS.get(task_type)
        if handler_cls is None:
            raise ValueError(f"Unknown task type: {task_type}")
        handler_cls.validate_payload(payload)

        logger.info(f"[create_task] 入参: task_type={task_type}, payload={payload.get('document_id')}")
        try:
            task_id = str(uuid.uuid4())
            task = Task(task_id, task_type, payload)
            
            # 保存到数据库
            db = SessionLocal()
            try:
                # 直接从payload中获取document_id
                document_id = payload.get("document_id")
                db.add(TaskRow(id=task_id, type=task_type, status="pending",
                               file_id=document_id, payload=json.dumps(payload, ensure_ascii=False)))
                db.commit()
            finally:
                db.close()
            
            with self.lock:
                self.tasks[task_id] = task
                self.task_queue.append(task_id)
            
            logger.info(f"[create_task] 返回值: task_id={task_id}")
            return task_id
        except Exception as e:
            logger.error(f"[create_task] 异常: {str(e)}")
            raise

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务信息"""
        logger.info(f"[get_task] 入参: task_id={task_id}")
        try:
            # 先从内存中获取
            with self.lock:
                task = self.tasks.get(task_id)
                if task:
                    logger.info(f"[get_task] 返回值: 从内存获取成功, task_id={task_id}")
                    return task
            
            # 从数据库中获取
            db = SessionLocal()
            try:
                db_task = db.query(TaskRow).filter(TaskRow.id == task_id).first()
                if db_task:
                    task = _apply_db_row(
                        Task(task_id=db_task.id, task_type=db_task.type, payload=_payload_from_db_row(db_task)),
                        db_task)
                    
                    # 保存到内存中
                    with self.lock:
                        self.tasks[task_id] = task
                    
                    logger.info(f"[get_task] 返回值: 从数据库获取成功, task_id={task_id}")
                    return task
            finally:
                db.close()
            
            logger.info(f"[get_task] 返回值: 未找到任务, task_id={task_id}")
            return None
        except Exception as e:
            logger.error(f"[get_task] 异常: {str(e)}")
            raise

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        try:
            db = SessionLocal()
            try:
                db_task = db.query(TaskRow).filter(TaskRow.id == task_id).first()
                if db_task:
                    task = _apply_db_row(
                        Task(task_id=db_task.id, task_type=db_task.type, payload=_payload_from_db_row(db_task)),
                        db_task)
                    self._fill_datasource_labels([task])
                    return task.to_dict()
            finally:
                db.close()

            logger.info(f"[get_task_status] 未找到任务, task_id={task_id}")
            return None
        except Exception as e:
            logger.error(f"[get_task_status] 异常: {str(e)}")
            raise

    def get_task_result(self, task_id: str) -> Optional[Any]:
        """获取任务结果"""
        try:
            # 直接从数据库中获取
            db = SessionLocal()
            try:
                db_task = db.query(TaskRow).filter(TaskRow.id == task_id).first()
                if db_task and db_task.status == "completed":
                    return db_task.result
            finally:
                db.close()
            
            return None
        except Exception as e:
            logger.error(f"[get_task_result] 异常: {str(e)}")
            raise

    def list_tasks(self) -> List[Dict[str, Any]]:
        """列出所有任务"""
        logger.info(f"[list_tasks] 入参: 无")
        try:
            db = SessionLocal()
            try:
                db_tasks = db.query(TaskRow).offset(0).limit(1000).all()
                tasks = []
                for db_task in db_tasks:
                    task = _apply_db_row(
                        Task(task_id=db_task.id, task_type=db_task.type, payload=_payload_from_db_row(db_task)),
                        db_task)
                    tasks.append(task)
                self._fill_datasource_labels(tasks)
                logger.info(f"[list_tasks] 返回值: 共{len(tasks)}个任务")
                return [task.to_dict() for task in tasks]
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[list_tasks] 异常: {str(e)}")
            raise

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        logger.info(f"[delete_task] 入参: task_id={task_id}")
        try:
            with self.lock:
                # 从内存中移除任务
                if task_id in self.tasks:
                    task = self.tasks[task_id]
                    # 如果任务正在运行，不允许删除
                    if task.status == "running":
                        logger.error(f"[delete_task] 任务正在运行，无法删除: task_id={task_id}")
                        raise ValueError("Cannot delete a running task")
                    
                    # 从队列和运行列表中移除
                    if task_id in self.task_queue:
                        self.task_queue.remove(task_id)
                    if task_id in self.running_tasks:
                        self.running_tasks.remove(task_id)
                    
                    del self.tasks[task_id]
            
            # 从数据库中删除
            db = SessionLocal()
            try:
                db_task = db.query(TaskRow).filter(TaskRow.id == task_id).first()
                if db_task:
                    db.delete(db_task)
                    db.commit()
                    logger.info(f"[delete_task] 返回值: 删除成功, task_id={task_id}")
                    return True
                else:
                    logger.warning(f"[delete_task] 返回值: 任务不存在, task_id={task_id}")
                    return False
            finally:
                db.close()
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"[delete_task] 异常: {str(e)}")
            raise

    def stop_task(self, task_id: str) -> bool:
        """停止任务（支持停止运行中和等待中的任务）"""
        logger.info(f"[stop_task] 入参: task_id={task_id}")
        try:
            with self.lock:
                # 检查任务是否存在
                if task_id not in self.tasks:
                    logger.warning(f"[stop_task] 任务不存在: task_id={task_id}")
                    return False
                
                task = self.tasks[task_id]
                
                # 如果任务已完成或已失败，不需要停止
                if task.status in _TERMINAL_STATUSES:
                    logger.warning(f"[stop_task] 任务状态不允许停止: task_id={task_id}, status={task.status}")
                    return False
                
                # 标记任务状态为停止中
                task.status = "stopping"
                task.stop_event.set()  # 通知长驻任务（如 CDC）立即退出
                
                # 如果任务在队列中，从队列移除
                if task_id in self.task_queue:
                    self.task_queue.remove(task_id)
                    logger.info(f"[stop_task] 任务已从队列中移除: task_id={task_id}")
                
                # 如果任务正在运行，从运行列表移除并标记为停止
                if task_id in self.running_tasks:
                    self.running_tasks.remove(task_id)
                    logger.info(f"[stop_task] 任务已从运行列表中移除: task_id={task_id}")
            
            # 更新数据库状态（收尾语义：stopped 属终态，complete_time/广播由 _update_task_in_db 统一处理）
            found = self._update_task_in_db(task_id, "stopped")
            with self.lock:
                task.status = "stopped"
                task.completed_at = datetime.now().isoformat()
            if found:
                logger.info(f"[stop_task] 返回值: 任务已停止, task_id={task_id}")
                return True
            else:
                logger.warning(f"[stop_task] 返回值: 任务不存在, task_id={task_id}")
                return False
        except Exception as e:
            logger.error(f"[stop_task] 异常: {str(e)}")
            raise

    def _process_tasks(self):
        """处理任务队列 —— 锁只保护容器读写；DB 写与等待在锁外（避免 create_task 被周期阻塞）"""
        while True:
            try:
                task_id = None
                with self.lock:
                    if len(self.running_tasks) < self.max_concurrent_tasks and self.task_queue:
                        task_id = self.task_queue.pop(0)
                        self.running_tasks.append(task_id)
                        task = self.tasks[task_id]
                        task.status = "running"
                        task.started_at = datetime.now().isoformat()
                if task_id:
                    self._update_task_in_db(task_id, "running")
                    threading.Thread(target=self._execute_task, args=(task_id,)).start()
                    time.sleep(0.1)
                else:
                    time.sleep(1)
            except Exception as e:
                # 调度线程是进程级单点：任何一轮的意外异常只记账，不允许带死整个循环
                logger.error(f"[_process_tasks] 调度循环异常（继续运行）: {e}")
                time.sleep(1)

    def _execute_task(self, task_id: str):
        """执行具体任务"""
        logger.info(f"[_execute_task] 入参: task_id={task_id}")
        started_at_wall = time.time()
        task_type_label = "unknown"
        try:
            # 直接从数据库获取任务
            db = SessionLocal()
            try:
                db_task = db.query(TaskRow).filter(TaskRow.id == task_id).first()
                if not db_task:
                    logger.warning(f"[_execute_task] 未找到任务: task_id={task_id}")
                    return
                
                # 从内存中获取任务（包含payload）
                with self.lock:
                    task = self.tasks.get(task_id)
                    if not task:
                        logger.warning(f"[_execute_task] 内存中未找到任务: task_id={task_id}")
                        task = _apply_db_row(
                            Task(task_id=db_task.id, task_type=db_task.type, payload=_payload_from_db_row(db_task)),
                            db_task)
                        self.tasks[task_id] = task
                task_type_label = task.task_type or "unknown"
            finally:
                db.close()
            
            try:
                # 通过 handler 契约分发执行（task_type → 类，注册表单一来源）
                handler_class = HANDLERS.get(task.task_type)
                if handler_class is None:
                    raise ValueError(f"Unknown task type: {task.task_type}")

                def progress_callback(progress: int):
                    # 锁只保护内存字段；DB 写在锁外（避免把 SQLite 写纳入全局锁临界区）
                    with self.lock:
                        task.progress = progress
                    try:
                        self._update_task_in_db(task_id, progress=progress)
                    except Exception as db_err:
                        logger.warning(f"[_execute_task] 进度落库失败（不影响执行）: {db_err}")
                    from websocket.task_ws import task_ws_manager
                    task_ws_manager.broadcast_sync({
                        "type": "task_progress",
                        "task_id": task_id,
                        "progress": progress,
                    })

                handler = handler_class()
                result = handler.execute(task, progress_callback)
                # 结果登记的唯一来源：handler 返回值即任务结果（handler 内部不再各自写 task.result）

                # 任务完成（若已被 stop_task 置为 stopped，则保持 stopped 不覆盖）
                task.result = result
                with self.lock:
                    was_stopped = (task.status == "stopped")
                    if not was_stopped:
                        task.status = "completed"
                        task.completed_at = datetime.now().isoformat()
                    if task_id in self.running_tasks:
                        self.running_tasks.remove(task_id)
                if not was_stopped:
                    self._update_task_in_db(task_id, "completed", result=task.result)
                if was_stopped:
                    logger.info(f"[_execute_task] 任务已停止: task_id={task_id}")
                else:
                    logger.info(f"[_execute_task] 任务完成: task_id={task_id}")
            except Exception as e:
                with self.lock:
                    task.status = "failed"
                    task.error = str(e)
                    task.completed_at = datetime.now().isoformat()
                    if task_id in self.running_tasks:
                        self.running_tasks.remove(task_id)
                self._update_task_in_db(task_id, "failed", error=str(e))
                logger.error(f"[_execute_task] 任务执行失败: task_id={task_id}, error={str(e)}")
                raise
        except Exception as e:
            logger.error(f"[_execute_task] 异常: {str(e)}")
        finally:
            # 兜底清槽：任何路径（含任务行缺失早退 / 调度中断）都不允许 Running 槽永久占位
            final_status = None
            needs_db_fail = False
            with self.lock:
                if task_id in self.running_tasks:
                    self.running_tasks.remove(task_id)
                task = self.tasks.get(task_id)
                if task and task.status not in _TERMINAL_STATUSES:
                    task.status = "failed"
                    task.error = "执行器异常退出（任务行缺失或调度被中断）"
                    task.completed_at = datetime.now().isoformat()
                    needs_db_fail = True
                if task:
                    final_status = task.status
            if needs_db_fail:
                self._update_task_in_db(task_id, "failed", error=self.tasks[task_id].error)
            # 任务耗时直方图（完成/失败/停止/兜底统一，CDC 长驻任务除外——它在 stop 时刻自然收到）；
            # 任务行缺失早退（final_status=None）不算执行耗时
            if final_status in _TERMINAL_STATUSES and final_status != "stopped":
                TASK_DURATION.labels(task_type=task_type_label, status=final_status) \
                    .observe(time.time() - started_at_wall)


    def _update_task_in_db(self, task_id: str, status: str = None,
                           result: str = None, error: str = None, progress: int = None) -> bool:
        """任务收尾/状态变更的唯一落库缝：字段更新、terminal 态补 complete_time、WS 广播同处收敛

        Returns:
            目标任务行是否存在
        """
        try:
            db = SessionLocal()
            found = False
            try:
                row = db.query(TaskRow).filter(TaskRow.id == task_id).first()
                if row:
                    found = True
                    if status is not None:
                        row.status = status
                    if result is not None:
                        # 结构化结果统一 JSON 化：前端按 JSON 解析（repr 单引号串不可靠）
                        row.result = result if isinstance(result, str) \
                            else json.dumps(result, ensure_ascii=False)
                    if error:
                        row.error = error
                    if progress is not None:
                        row.progress = progress
                    if status in _TERMINAL_STATUSES and row.complete_time is None:
                        row.complete_time = datetime.now()
                    db.commit()
            finally:
                db.close()

            # WebSocket 广播任务状态变更
            if status is not None:
                from websocket.task_ws import task_ws_manager
                task_ws_manager.broadcast_sync({
                    "type": "task_update",
                    "task_id": task_id,
                    "status": status,
                    "error": error,
                })
            return found
        except Exception as e:
            logger.error(f"[_update_task_in_db] 异常: {str(e)}")
            raise

    def _load_tasks(self):
        """从数据库加载任务"""
        logger.info(f"[_load_tasks] 入参: 无")
        try:
            db = SessionLocal()
            try:
                # 只加载未完成的任务
                tasks = db.query(TaskRow).offset(0).limit(1000).all()
                loaded_count = 0
                for db_task in tasks:
                    if db_task.status in ["pending", "running"]:
                        task = _apply_db_row(
                            Task(db_task.id, db_task.type, _payload_from_db_row(db_task)), db_task)
                        self.tasks[task.task_id] = task
                        
                        # 重新加入队列（如果任务未完成）
                        if task.status == "pending":
                            self.task_queue.append(task.task_id)
                        elif task.status == "running":
                            # 将运行中的任务重新加入队列，以便重新执行
                            self.task_queue.append(task.task_id)
                        loaded_count += 1
                logger.info(f"[_load_tasks] 返回值: 从数据库加载{loaded_count}个未完成任务")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[_load_tasks] 异常: {str(e)}")
            raise

# 创建全局任务管理器实例
task_manager = TaskManager()