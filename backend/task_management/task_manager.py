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
from task_management.task_service import TaskService
from task_management.handlers import SchemaAnalyzeHandler, SchemaImportHandler, CdcStartHandler, DocumentSummaryHandler
from system.logger import logger

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "payload": self.payload,
            "result": self.result,
            "progress": self.progress,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at
        }

class TaskManager:
    _handlers = {
        "database_schema_analyze": SchemaAnalyzeHandler,
        "database_schema_import": SchemaImportHandler,
        "database_cdc_start": CdcStartHandler,
        "document_generate_summary": DocumentSummaryHandler,
    }

    def __init__(self, max_concurrent_tasks: int = 5):
        self.tasks: Dict[str, Task] = {}
        self.task_queue: List[str] = []
        self.running_tasks: List[str] = []
        self.max_concurrent_tasks = max_concurrent_tasks
        self.lock = threading.Lock()
        self.worker_thread = threading.Thread(target=self._process_tasks, daemon=True)
        self.worker_thread.start()
        self.task_service = TaskService()
        
        # 从数据库加载任务
        self._load_tasks()

    def create_task(self, task_type: str, payload: Dict[str, Any]) -> str:
        """创建新任务"""
        logger.info(f"[create_task] 入参: task_type={task_type}, payload={payload.get('document_id')}")
        try:
            task_id = str(uuid.uuid4())
            task = Task(task_id, task_type, payload)
            
            # 保存到数据库
            db = SessionLocal()
            try:
                # 直接从payload中获取document_id
                document_id = payload.get("document_id")
                db_task = self.task_service.create_task(db, task_type, document_id, "pending", task_id)
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
                db_task = self.task_service.get_task(db, task_id)
                if db_task:
                    # 创建payload，包含document_id
                    payload = {}
                    if db_task.file_id:
                        payload["document_id"] = db_task.file_id
                    
                    # 创建Task对象
                    task = Task(
                        task_id=db_task.id,
                        task_type=db_task.type,
                        payload=payload
                    )
                    task.status = db_task.status
                    task.result = db_task.result
                    task.created_at = db_task.create_time.isoformat() if db_task.create_time else None
                    task.completed_at = db_task.complete_time.isoformat() if db_task.complete_time else None
                    task.file_id = db_task.file_id
                    
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
            # 直接从数据库中获取
            db = SessionLocal()
            try:
                db_task = self.task_service.get_task(db, task_id)
                if db_task:
                    # 创建Task对象
                    task = Task(
                        task_id=db_task.id,
                        task_type=db_task.type,
                        payload={}
                    )
                    task.status = db_task.status
                    task.result = db_task.result
                    task.created_at = db_task.create_time.isoformat() if db_task.create_time else None
                    task.completed_at = db_task.complete_time.isoformat() if db_task.complete_time else None
                    task.file_id = db_task.file_id
                    
                    result = task.to_dict()
                    return result
            finally:
                db.close()
            
            logger.info(f"[get_task_status] 返回值: 未找到任务, task_id={task_id}")
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
                db_task = self.task_service.get_task(db, task_id)
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
            # 直接从数据库中获取任务列表
            db = SessionLocal()
            try:
                db_tasks = self.task_service.get_tasks(db, skip=0, limit=1000)
                tasks = []
                for db_task in db_tasks:
                    # 创建Task对象
                    task = Task(
                        task_id=db_task.id,
                        task_type=db_task.type,
                        payload={}
                    )
                    task.status = db_task.status
                    task.result = db_task.result
                    task.created_at = db_task.create_time.isoformat() if db_task.create_time else None
                    task.completed_at = db_task.complete_time.isoformat() if db_task.complete_time else None
                    task.file_id = db_task.file_id

                    task_dict = task.to_dict()
                    tasks.append(task_dict)
                logger.info(f"[list_tasks] 返回值: 共{len(tasks)}个任务")
                return tasks
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
                db_task = self.task_service.delete_task(db, task_id)
                if db_task:
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
                if task.status in ["completed", "failed", "stopped"]:
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
            
            # 更新数据库状态
            db = SessionLocal()
            try:
                db_task = self.task_service.update_task(db, task_id, status="stopped")
                if db_task:
                    # 更新内存中的任务状态
                    with self.lock:
                        task.status = "stopped"
                        task.completed_at = datetime.now().isoformat()
                    logger.info(f"[stop_task] 返回值: 任务已停止, task_id={task_id}")
                    return True
                else:
                    logger.warning(f"[stop_task] 返回值: 任务不存在, task_id={task_id}")
                    return False
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[stop_task] 异常: {str(e)}")
            raise

    def _process_tasks(self):
        """处理任务队列"""
        while True:
            with self.lock:
                # 处理队列中的任务
                if len(self.running_tasks) < self.max_concurrent_tasks and self.task_queue:
                    task_id = self.task_queue.pop(0)
                    self.running_tasks.append(task_id)
                    task = self.tasks[task_id]
                    task.status = "running"
                    task.started_at = datetime.now().isoformat()
                    self._update_task_in_db(task_id, "running")
                    
                    # 执行任务
                    threading.Thread(target=self._execute_task, args=(task_id,)).start()
                else:
                    time.sleep(1)
                    continue
            
            time.sleep(0.1)

    def _execute_task(self, task_id: str):
        """执行具体任务"""
        logger.info(f"[_execute_task] 入参: task_id={task_id}")
        try:
            # 直接从数据库获取任务
            db = SessionLocal()
            try:
                db_task = self.task_service.get_task(db, task_id)
                if not db_task:
                    logger.warning(f"[_execute_task] 未找到任务: task_id={task_id}")
                    return
                
                # 从内存中获取任务（包含payload）
                with self.lock:
                    task = self.tasks.get(task_id)
                    if not task:
                        logger.warning(f"[_execute_task] 内存中未找到任务: task_id={task_id}")
                        # 如果内存中没有任务，创建一个新的Task对象
                        # 创建payload，包含document_id
                        payload = {}
                        if db_task.file_id:
                            payload["document_id"] = db_task.file_id
                        
                        task = Task(
                            task_id=db_task.id,
                            task_type=db_task.type,
                            payload=payload
                        )
                        task.status = db_task.status
                        task.result = db_task.result
                        task.created_at = db_task.create_time.isoformat() if db_task.create_time else None
                        task.completed_at = db_task.complete_time.isoformat() if db_task.complete_time else None
                        task.file_id = db_task.file_id
                        self.tasks[task_id] = task
            finally:
                db.close()
            
            try:
                # 通过 handler 分发执行
                handler_class = self._handlers.get(task.task_type)
                if handler_class is None:
                    raise ValueError(f"Unknown task type: {task.task_type}")

                def progress_callback(progress: int):
                    with self.lock:
                        task.progress = progress

                handler = handler_class()
                result = handler.execute(task, progress_callback)

                # 任务完成（若已被 stop_task 置为 stopped，则保持 stopped 不覆盖）
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
            raise


    def _update_task_in_db(self, task_id: str, status: str, result: str = None, error: str = None):
        """更新数据库中的任务状态"""
        try:
            # 直接使用task_id更新数据库
            db = SessionLocal()
            try:
                update_data = {"status": status}
                if result:
                    update_data["result"] = str(result)
                if error:
                    update_data["error"] = error
                self.task_service.update_task(db, task_id, **update_data)
            finally:
                db.close()
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
                tasks = self.task_service.get_tasks(db, skip=0, limit=1000)
                loaded_count = 0
                for db_task in tasks:
                    if db_task.status in ["pending", "running"]:
                        # 直接使用数据库中的task_id
                        task = Task(db_task.id, db_task.type, {})
                        task.status = db_task.status
                        task.result = db_task.result
                        task.created_at = db_task.create_time.isoformat() if db_task.create_time else None
                        task.completed_at = db_task.complete_time.isoformat() if db_task.complete_time else None
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