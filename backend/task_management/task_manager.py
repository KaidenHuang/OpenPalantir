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
from system.logger import logger

_PRIMARY_KEY_MARKERS = ("PRI", "PRIMARY KEY", "PK")
_DEFAULT_ENTITY_TYPE = "其他"
_MAX_CROSS_PRODUCT_PAIRS = 50


def _build_entity_name(table_name: str, row: Dict, pk_columns: List[str]) -> str:
    """构建行实体的规范名称 {table_name}:{pk_value1}:{pk_value2}...，PK 缺失时返回空字符串"""
    if not pk_columns or not row:
        return ""
    pk_values = []
    for pk in pk_columns:
        val = row.get(pk)
        if val is None or str(val) == "":
            return ""
        pk_values.append(str(val))
    return f"{table_name}:{':'.join(pk_values)}"


def _detect_primary_keys(columns_by_table: Dict[str, List[Dict]]) -> Dict[str, List[str]]:
    pk_columns = {}
    for table_name, cols in columns_by_table.items():
        pk_cols = [c["column_name"] for c in cols if c.get("column_key") in _PRIMARY_KEY_MARKERS]
        if not pk_cols:
            first = cols[0]["column_name"] if cols else None
            if first:
                logger.warning(f"表 {table_name} 未检测到主键，使用首列 '{first}' 作为代理键")
                pk_cols = [first]
        pk_columns[table_name] = pk_cols
    return pk_columns


def _refine_pks_via_dialect(pk_columns: Dict[str, List[str]], columns_by_table: Dict[str, List[Dict]],
                             dialect, connection, table_names: List[str]):
    """对于使用代理键的表，通过数据库 dialect 检测真实主键"""
    for full_name in table_names:
        if len(pk_columns.get(full_name, [])) != 1:
            continue
        try:
            real_pks = dialect.get_primary_key_columns(connection, full_name)
            if real_pks:
                pk_columns[full_name] = real_pks
                logger.info(f"表 {full_name} 通过 dialect 检测到主键: {real_pks}")
        except Exception:
            pass


def _make_relationship(subject: str, object_: str, predicate: str, confidence: float = 0.8,
                        description: str = "") -> Dict:
    return {
        "s": subject,
        "o": object_,
        "p": predicate,
        "ot": "",
        "d": description
    }


def _get_fk_column_info(foreign_keys: List[Dict], inferred_relationships: List[Dict]) -> Dict[str, set]:
    """收集需要建立值索引的列：返回 {表名: {列名集合}}"""
    col_info: Dict[str, set] = {}
    for fk in foreign_keys:
        table = fk.get("table_name") or fk.get("TABLE_NAME", "")
        col = fk.get("column_name") or fk.get("COLUMN_NAME", "")
        if table and col:
            col_info.setdefault(table, set()).add(col)
    for rel in inferred_relationships:
        src_t = rel.get("source_table", "")
        src_c = rel.get("source_column", "")
        tgt_t = rel.get("target_table", "")
        tgt_c = rel.get("target_column", "")
        if src_t and src_c:
            col_info.setdefault(src_t, set()).add(src_c)
        if tgt_t and tgt_c:
            col_info.setdefault(tgt_t, set()).add(tgt_c)
    return col_info


def _extract_pk_value(row: Dict, pk_columns: List[str]) -> Optional[str]:
    """从行数据中提取 PK 值字符串，多列用 : 连接，无法提取时返回 None"""
    values = []
    for pk in pk_columns:
        val = row.get(pk)
        if val is None or str(val) == "":
            return None
        values.append(str(val))
    return ":".join(values)


def _build_entities_batch(rows: List[Dict], table_name: str, entity_type: str,
                           pk_columns: List[str], db_prefix: str) -> List[Dict]:
    """为一批行构建实体字典列表"""
    entities = []
    for row in rows:
        entity_name = _build_entity_name(table_name, row, pk_columns)
        if not entity_name:
            continue
        description_parts = [f"{col}={val}" for col, val in row.items()]
        description = ", ".join(description_parts)
        entities.append({
            "n": entity_name,
            "t": entity_type,
            "bn": None,
            "c": 1,
            "datasource": f"{db_prefix}/{table_name}",
            "d": description
        })
    return entities


def _dedup_relationships(relationships: List[Dict]) -> List[Dict]:
    """去重关系列表，保留首次出现的 (subject, predicate, object) 三元组"""
    seen: set = set()
    deduped = []
    for rel in relationships:
        key = (rel.get("s", ""), rel.get("p", ""), rel.get("o", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(rel)
    skipped = len(relationships) - len(deduped)
    if skipped:
        logger.info(f"关系去重: 移除了 {skipped} 条重复关系")
    return deduped


def _build_relationships_from_index(foreign_keys: List[Dict], inferred_relationships: List[Dict],
                                     pk_index: Dict[str, Dict[str, str]],
                                     fk_index: Dict[str, Dict[str, Dict[str, str]]],
                                     max_cross_product_pairs: int = 50) -> List[Dict]:
    """使用 PK/FK 索引构建关系，无需完整行数据"""
    relationships = []

    for fk in foreign_keys:
        source_table = fk.get("table_name") or fk.get("TABLE_NAME", "")
        source_column = fk.get("column_name") or fk.get("COLUMN_NAME", "")
        target_table = fk.get("referenced_table_name") or fk.get("REFERENCED_TABLE_NAME", "")

        source_fk_idx = fk_index.get(source_table, {}).get(source_column, {})
        target_pk_idx = pk_index.get(target_table, {})

        for fk_value, source_entity in source_fk_idx.items():
            target_entity = target_pk_idx.get(fk_value)
            if not target_entity:
                continue
            desc = f"{source_table}.{source_column}={fk_value} -> {target_table}"
            relationships.append(
                _make_relationship(source_entity, target_entity, "Foreign key", 1.0, desc)
            )

    for rel in inferred_relationships:
        source_table = rel.get("source_table", "")
        target_table = rel.get("target_table", "")
        src_col = rel.get("source_column", "")
        tgt_col = rel.get("target_column", "")
        pred = rel.get("relationship_type", "Related to")
        confidence = rel.get("confidence", 0.8)
        rel_desc = rel.get("description", "")

        if src_col and tgt_col:
            src_idx = fk_index.get(source_table, {}).get(src_col, {})
            tgt_idx = fk_index.get(target_table, {}).get(tgt_col, {})
            if not src_idx or not tgt_idx:
                continue
            common = set(src_idx.keys()) & set(tgt_idx.keys())
            for val in common:
                s_entity = src_idx[val]
                t_entity = tgt_idx[val]
                relationships.append(
                    _make_relationship(s_entity, t_entity, pred, confidence, rel_desc)
                )
        else:
            src_pk = pk_index.get(source_table, {})
            tgt_pk = pk_index.get(target_table, {})
            if len(src_pk) * len(tgt_pk) > max_cross_product_pairs:
                logger.warning(f"跳过推断关系 {source_table}->{target_table}: "
                               f"行对过多 ({len(src_pk)}x{len(tgt_pk)})")
                continue
            for s_entity in src_pk.values():
                for t_entity in tgt_pk.values():
                    relationships.append(
                        _make_relationship(s_entity, t_entity, pred, confidence, rel_desc)
                    )

    if relationships:
        relationships = _dedup_relationships(relationships)
    return relationships


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
                # 根据任务类型执行不同的处理逻辑
                if task.task_type == "database_schema_analyze":
                    self._execute_database_schema_analyze(task)
                elif task.task_type == "database_schema_import":
                    self._execute_database_schema_import(task)
                elif task.task_type == "document_generate_summary":
                    self._execute_document_generate_summary(task)
                else:
                    raise ValueError(f"Unknown task type: {task.task_type}")
                
                # 任务完成
                with self.lock:
                    task.status = "completed"
                    task.completed_at = datetime.now().isoformat()
                    if task_id in self.running_tasks:
                        self.running_tasks.remove(task_id)
                    self._update_task_in_db(task_id, "completed", result=task.result)
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

    def _update_task_progress_in_db(self, task_id: str, progress: int):
        """更新数据库中的任务进度"""
        # 进度在 Task 对象的内存中跟踪，DB 的 result 列仅存储最终结果
        pass

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

    def _execute_database_schema_analyze(self, task: Task):
        """执行数据库Schema分析任务（阶段1）"""
        logger.info(f"[_execute_database_schema_analyze] 入参: task_id={task.task_id}, task_type={task.task_type}")
        try:
            from database_management.database_manager import database_manager
            from database_management.database_service import DatabaseService
            from database_management.schema_annotator import SchemaAnnotator
            from config.database import SessionLocal
            
            connection_id = task.payload.get("connection_id")
            tables = task.payload.get("tables")
            ignore_tables = task.payload.get("ignore_tables")
            database_name = task.payload.get("database_name")

            logger.info(f"开始执行数据库Schema分析任务，连接ID: {connection_id}, 数据库: {database_name}")
            
            if not connection_id:
                raise ValueError("缺少connection_id")
            
            with self.lock:
                task.progress = 10
                self._update_task_progress_in_db(task.task_id, task.progress)
            
            logger.info("步骤1: 提取数据库Schema")
            schema = database_manager.extract_schema(connection_id, tables, ignore_tables, database_name=database_name)
            
            with self.lock:
                task.progress = 40
                self._update_task_progress_in_db(task.task_id, task.progress)
            
            logger.info("步骤2: 使用LLM进行业务标注")
            # 创建数据库会话并传入SchemaAnnotator以获取可用模型
            db = SessionLocal()
            try:
                annotator = SchemaAnnotator(db_session=db)
                annotated_schema = annotator.batch_annotate(schema)
            finally:
                db.close()

            # 从标注结果中提取数据库概要（从annotated_schema移除，避免存入SQLite）
            db_summary = annotated_schema.pop("database_summary", {}) if isinstance(annotated_schema, dict) else {}

            with self.lock:
                task.progress = 70
                self._update_task_progress_in_db(task.task_id, task.progress)

            logger.info("步骤3: 保存分析结果到数据库")
            connection_name = ""
            db = SessionLocal()
            try:
                db_service = DatabaseService()
                db_service.save_schema(db, connection_id, annotated_schema)

                conn = db_service.get_connection(db, connection_id)
                analyzed_db_name = database_name or (conn.database if conn else None)
                connection_name = conn.name if conn else ""
                if analyzed_db_name:
                    db_service.save_analyzed_database(db, connection_id, analyzed_db_name)
                    logger.info(f"已分析数据库已记录: {analyzed_db_name}")

                # 为每张表创建 AnalyzedTable 记录（含 URI）
                from models.database import AnalyzedTable
                table_list = [{k.lower(): v for k, v in t.items()} for t in annotated_schema.get("tables", [])]
                for tbl in table_list:
                    table_uri = f"DBS://{connection_id}/{analyzed_db_name}/{tbl['table_name']}"
                    existing_table = db.query(AnalyzedTable).filter(
                        AnalyzedTable.connection_id == connection_id,
                        AnalyzedTable.table_name == tbl["table_name"]
                    ).first()
                    if not existing_table:
                        analyzed_table = AnalyzedTable(
                            id=str(uuid.uuid4()),
                            connection_id=connection_id,
                            database_name=analyzed_db_name or "",
                            table_name=tbl["table_name"],
                            uri=table_uri,
                        )
                        db.add(analyzed_table)
                logger.info(f"已为 {len(table_list)} 个表创建 AnalyzedTable 记录")
            finally:
                db.close()

            # 步骤4: 保存数据库概要到本地文件
            if db_summary and db_summary.get("overview"):
                try:
                    # 统一规范化键名（兼容不同数据库驱动的大小写差异）
                    table_list = [{k.lower(): v for k, v in t.items()} for t in annotated_schema.get("tables", [])]
                    columns_list = [{k.lower(): v for k, v in c.items()} for c in annotated_schema.get("columns", [])]
                    raw_columns = [{k.lower(): v for k, v in c.items()} for c in schema.get("columns", [])]
                    raw_fks = [{k.lower(): v for k, v in fk.items()} for fk in schema.get("foreign_keys", [])]

                    columns_by_table = {}
                    for col in columns_list:
                        columns_by_table.setdefault(col["table_name"], []).append(col)

                    # 从原始 schema 构建列类型映射
                    col_types = {}
                    for col in raw_columns:
                        tn = col.get("table_name", "")
                        cn = col.get("column_name", "")
                        dt = col.get("data_type", "")
                        if tn and cn:
                            col_types[(tn, cn)] = dt

                    # 从原始 schema 构建外键映射
                    fk_by_table = {}
                    for fk in raw_fks:
                        table = fk.get("table_name", "")
                        col = fk.get("column_name", "")
                        ref_table = fk.get("referenced_table_name", "")
                        ref_col = fk.get("referenced_column_name", "")
                        if table:
                            fk_by_table.setdefault(table, []).append({
                                "column": col,
                                "references": f"{ref_table}.{ref_col}"
                            })

                    # 从原始 schema 构建主键/唯一键映射
                    pk_columns = {}   # {table_name: [column_name, ...]}
                    uk_columns = {}   # {table_name: [column_name, ...]}
                    for col in raw_columns:
                        tn = col.get("table_name", "")
                        cn = col.get("column_name", "")
                        ck = col.get("column_key", "")
                        if tn and cn:
                            if ck == "PRI":
                                pk_columns.setdefault(tn, []).append(cn)
                            elif ck == "UNI":
                                uk_columns.setdefault(tn, []).append(cn)

                    structure_nodes = []
                    for idx, tbl in enumerate(table_list):
                        tbl_name = tbl["table_name"]
                        col_names = [c["column_name"] for c in columns_by_table.get(tbl_name, [])]
                        cols_with_types = [f'{c}({col_types.get((tbl_name, c), "")})' for c in col_names]

                        # 合并所有键信息
                        table_keys = []
                        seen = set()
                        for c in pk_columns.get(tbl_name, []):
                            table_keys.append({"column": c, "type": "PRIMARY KEY"})
                            seen.add(c)
                        for c in uk_columns.get(tbl_name, []):
                            if c not in seen:
                                table_keys.append({"column": c, "type": "UNIQUE KEY"})
                                seen.add(c)
                        for fk_entry in fk_by_table.get(tbl_name, []):
                            table_keys.append({
                                "column": fk_entry["column"],
                                "type": "FOREIGN KEY",
                                "references": fk_entry["references"]
                            })

                        structure_nodes.append({
                            "table_name": tbl_name,
                            "node_id": str(idx + 1).zfill(8),
                            "description": f"包含字段: {', '.join(cols_with_types)}",
                            "summary": tbl.get("business_description", ""),
                            "entity_type": tbl.get("entity_type", ""),
                            "keys": table_keys
                        })

                    db_summary_file = {
                        "db_name": analyzed_db_name or "default",
                        "db_description": db_summary.get("overview", ""),
                        "business_domain": db_summary.get("business_domain", ""),
                        "key_entities": db_summary.get("key_entities", ""),
                        "table_count": len(table_list),
                        "structure": structure_nodes
                    }

                    summary_dir = os.path.join("data", "summaries", "DBS", connection_id)
                    os.makedirs(summary_dir, exist_ok=True)
                    summary_filename = f"{analyzed_db_name or 'database_summary'}.json"
                    summary_path = os.path.join(summary_dir, summary_filename)
                    with open(summary_path, "w", encoding="utf-8") as f:
                        json.dump(db_summary_file, f, ensure_ascii=False, indent=2)
                    logger.info(f"数据库概要已保存: {summary_path}")
                except Exception as e:
                    logger.error(f"保存数据库概要时出错: {e}")
            
            with self.lock:
                task.progress = 100
                self._update_task_progress_in_db(task.task_id, task.progress)
            
            table_count = len(annotated_schema.get("tables", []))
            column_count = len(annotated_schema.get("columns", []))
            fk_count = len(annotated_schema.get("foreign_keys", []))
            
            task.result = {
                "connection_id": connection_id,
                "table_count": table_count,
                "column_count": column_count,
                "foreign_key_count": fk_count,
                "message": f"分析完成，共 {table_count} 个表，{column_count} 个字段，{fk_count} 个外键约束"
            }
            logger.info(f"[_execute_database_schema_analyze] 任务完成: {task.result}")
        
        except Exception as e:
            logger.error(f"执行数据库Schema分析任务时出错: {e}")
            raise
    
    def _execute_database_schema_import(self, task: Task):
        """执行数据库行级数据导入知识图谱任务（阶段2）— 分批导入"""
        logger.info(f"[_execute_database_schema_import] 入参: task_id={task.task_id}, task_type={task.task_type}")
        try:
            from database_management.database_service import DatabaseService
            from database_management.database_manager import database_manager, DIALECT_MAP
            from utils.data_store import EntityDataStore
            from config.database import SessionLocal

            connection_id = task.payload.get("connection_id")
            batch_size = task.payload.get("batch_size", 5000)
            row_limit = task.payload.get("row_limit", 0)
            neo4j_batch_size = task.payload.get("neo4j_batch_size", 20000)  # Neo4j 写入批大小
            use_merge = task.payload.get("use_merge", False)  # 默认使用 CREATE（更快）
            auto_start_cdc = task.payload.get("auto_start_cdc", False)

            logger.info(f"开始执行数据库行级导入任务，连接ID: {connection_id}, "
                        f"源批量大小: {batch_size}, Neo4j写入批大小: {neo4j_batch_size}, use_merge={use_merge}")

            if not connection_id:
                raise ValueError("缺少connection_id")

            with self.lock:
                task.progress = 10
                self._update_task_progress_in_db(task.task_id, task.progress)

            logger.info("步骤1: 从本地数据库获取Schema和连接信息")
            db = SessionLocal()
            try:
                db_service = DatabaseService()
                schema = db_service.get_schema(db, connection_id)
                conn_config = db_service.get_connection(db, connection_id)
                analyzed_dbs = db_service.get_analyzed_databases(db, connection_id)
                analyzed_db_names = [ad.database_name for ad in analyzed_dbs]
                if conn_config:
                    conn_config = {
                        "type": conn_config.type,
                        "host": conn_config.host,
                        "port": conn_config.port,
                        "database": conn_config.database,
                        "username": conn_config.username,
                        "password": conn_config.password,
                        "service_name": getattr(conn_config, "service_name", None)
                    }
            finally:
                db.close()

            if not schema["tables"]:
                raise ValueError("未找到Schema信息，请先执行分析任务")

            columns_by_table: Dict[str, List[Dict]] = {}
            for col in schema["columns"]:
                columns_by_table.setdefault(col["table_name"], []).append(col)

            with self.lock:
                task.progress = 20
                self._update_task_progress_in_db(task.task_id, task.progress)

            logger.info("步骤2: 检测主键列")
            pk_columns = _detect_primary_keys(columns_by_table)
            logger.info(f"主键检测完成: {len(pk_columns)} 个表")

            with self.lock:
                task.progress = 25
                self._update_task_progress_in_db(task.task_id, task.progress)

            # 需要建立 FK 值索引的列
            fk_column_info = _get_fk_column_info(
                schema["foreign_keys"],
                schema.get("inferred_relationships", [])
            )
            logger.info(f"外键/关联索引列数: {len(fk_column_info)} 个表")

            # --- Phase 1: 分批导入实体，同时建立索引 ---
            logger.info("步骤3: 分批获取行数据并导入实体")
            pk_index: Dict[str, Dict[str, str]] = {}
            fk_index: Dict[str, Dict[str, Dict[str, str]]] = {}
            all_saved_entities: List[Tuple[str, str]] = []  # (entity_name, entity_id)

            total_tables = len(schema["tables"])

            if not conn_config:
                raise ValueError("未找到数据库连接配置")

            engine = database_manager._create_engine(conn_config)
            if not engine:
                raise ValueError("无法创建数据库引擎")

            dialect_type = conn_config.get("type", "").lower()
            if dialect_type not in DIALECT_MAP:
                raise ValueError(f"不支持的数据库类型: {dialect_type}")

            dialect = DIALECT_MAP[dialect_type]()
            conn = engine.connect()

            # 先精炼主键信息
            _refine_pks_via_dialect(
                pk_columns, columns_by_table, dialect, conn,
                [t["table_name"] for t in schema["tables"]]
            )

            # 记录 binlog/WAL 位点（全量导入前，供 CDC 衔接使用）
            binlog_info = dialect.capture_binlog_position(conn)
            if binlog_info:
                logger.info(f"已捕获 binlog 位点: {binlog_info}")
                logger.warning(
                    f"[CDC] binlog 位点已记录，但仅在导入成功完成后保存检查点。"
                    f"若导入中途失败，需重新执行全量导入才能启用 CDC 增量同步。"
                )

            from knowledge_graph.graph_manager import graph_manager

            # 确保 Neo4j 索引已创建（Entity.name 索引对关系写入性能至关重要）
            try:
                graph_manager.performance.create_indexes()
                logger.info("Neo4j 索引已就绪")
            except Exception as e:
                logger.warning(f"创建 Neo4j 索引失败（可能已存在）: {e}")

            database_name_for_uri = analyzed_db_names[0] if analyzed_db_names else ""
            db_prefix = f"DBS://{connection_id}"
            if database_name_for_uri:
                db_prefix += f"/{database_name_for_uri}"

            # 全量导入前清理该数据源的旧实体（DELETE + CREATE 策略：清理后用 CREATE 保证性能）
            deleted_count = graph_manager.delete_entities_by_datasource(db_prefix)
            if deleted_count > 0:
                logger.info(f"全量导入前清理旧数据: 删除 {deleted_count} 个实体（datasource={db_prefix}）")

            # 分批导入期间延迟缓存清除
            graph_manager.set_defer_cache(True)

            try:
                for table_idx, table_info in enumerate(schema["tables"]):
                    full_table_name = table_info["table_name"]
                    entity_type = table_info.get("entity_type", _DEFAULT_ENTITY_TYPE)
                    table_pks = pk_columns.get(full_table_name, [])
                    table_cols = columns_by_table.get(full_table_name, [])
                    col_names = [c["column_name"] for c in table_cols]

                    if not col_names or not table_pks:
                        logger.warning(f"跳过表 {full_table_name}: 无有效列或主键")
                        continue

                    fk_cols_for_table = fk_column_info.get(full_table_name, set())
                    # FK 列可能与 PK 列重叠（如 dept_emp 的 emp_no 同时是 FK 和 PK）
                    # 需要保留 FK 列索引用于关系构建，不减去 PK 列
                    fk_cols_to_index = fk_cols_for_table
                    need_fk_index = bool(fk_cols_to_index)

                    table_pk_idx: Dict[str, str] = {}
                    table_fk_idx: Dict[str, Dict[str, str]] = {}
                    for fcol in fk_cols_to_index:
                        table_fk_idx[fcol] = {}

                    batch_count = 0
                    total_rows_for_table = 0
                    entity_buffer: List[Dict] = []

                    # 跳过 COUNT(*) 查询（大表耗时且仅用于进度估算）
                    total_batches = 0

                    for batch in dialect.fetch_table_rows_keyset(conn, full_table_name, col_names, table_pks, batch_size, max_rows=row_limit):
                        batch_count += 1
                        total_rows_for_table += len(batch)
                        logger.info(f"  表 {full_table_name}: 第 {batch_count} 批 ({len(batch)} 行，累计 {total_rows_for_table})")

                        entities_batch = _build_entities_batch(
                            batch, full_table_name, entity_type, table_pks, db_prefix
                        )
                        if not entities_batch:
                            continue

                        # 累积实体到缓冲区，达到 neo4j_batch_size 后一次性写入 Neo4j
                        entity_buffer.extend(entities_batch)

                        # 建立 PK 索引（立即执行，不需要 entity_id）
                        for row in batch:
                            pk_val = _extract_pk_value(row, table_pks)
                            if pk_val is None:
                                continue
                            entity_name = _build_entity_name(full_table_name, row, table_pks)
                            if entity_name:
                                table_pk_idx[pk_val] = entity_name

                        # 建立 FK 值索引（立即执行，不需要 entity_id）
                        if need_fk_index:
                            for row in batch:
                                entity_name = _build_entity_name(full_table_name, row, table_pks)
                                if not entity_name:
                                    continue
                                for fcol in fk_cols_to_index:
                                    fk_val = str(row.get(fcol, ""))
                                    if fk_val and fk_val != "None":
                                        table_fk_idx[fcol][fk_val] = entity_name

                        # 缓冲区达到上限，批量写入 Neo4j
                        if len(entity_buffer) >= neo4j_batch_size:
                            saved_batch = EntityDataStore.save_entities_only(entity_buffer, db_prefix)
                            all_saved_entities.extend(
                                (e.get("name", ""), e.get("entity_id", "")) for e in saved_batch
                            )
                            entity_buffer.clear()

                    # 写空剩余实体
                    if entity_buffer:
                        saved_batch = EntityDataStore.save_entities_only(entity_buffer, db_prefix)
                        all_saved_entities.extend(
                            (e.get("name", ""), e.get("entity_id", "")) for e in saved_batch
                        )
                        entity_buffer.clear()

                    pk_index[full_table_name] = table_pk_idx
                    if need_fk_index:
                        fk_index[full_table_name] = table_fk_idx

                    logger.info(f"  表 {full_table_name}: 完成，共 {total_rows_for_table} 行，"
                                f"{len(table_pk_idx)} 个索引条目")

                    progress_pct = 30 + int(40 * (table_idx + 1) / total_tables)
                    with self.lock:
                        task.progress = min(progress_pct, 70)
                        self._update_task_progress_in_db(task.task_id, task.progress)
            finally:
                conn.close()
            t_close = time.time()

            # 恢复缓存清除并手动清一次
            graph_manager.set_defer_cache(False)
            t_defer = time.time()
            graph_manager.performance.clear_cache("graph:*")
            t_cache = time.time()

            entity_count = len(all_saved_entities)
            logger.info(f"分批导入完成，共 {entity_count} 个实体")
            logger.info(f"  耗时细分: conn.close={t_defer-t_close:.3f}s  defer_cache={t_cache-t_defer:.3f}s")

            with self.lock:
                task.progress = 75
                self._update_task_progress_in_db(task.task_id, task.progress)

            # --- Phase 2: 从索引构建关系 ---
            logger.info("步骤4: 使用索引构建行级关系")
            t_phase2 = time.time()
            logger.info(f"  Phase1→Phase2 间隔: {t_phase2-t_cache:.3f}s")
            relationships = _build_relationships_from_index(
                foreign_keys=schema["foreign_keys"],
                inferred_relationships=schema.get("inferred_relationships", []),
                pk_index=pk_index,
                fk_index=fk_index,
                max_cross_product_pairs=_MAX_CROSS_PRODUCT_PAIRS
            )
            logger.info(f"关系构建完成: {len(relationships)} 条")

            # 清理索引，释放内存
            del pk_index
            del fk_index

            with self.lock:
                task.progress = 85
                self._update_task_progress_in_db(task.task_id, task.progress)

            # --- Phase 3: 保存关系 ---
            logger.info("步骤5: 保存关系到知识库和图谱存储")
            rel_count = 0
            if relationships:
                entity_name_map = {}
                for name, entity_id in all_saved_entities:
                    name = name.strip()
                    if name:
                        ent = {"name": name, "entity_id": entity_id}
                        entity_name_map[name] = ent
                        entity_name_map[name.lower()] = ent
                del all_saved_entities

                rel_count = EntityDataStore.save_relationships_only(relationships, entity_name_map, use_create=not use_merge)
                logger.info(f"关系保存完成: {rel_count} 条")
            else:
                del all_saved_entities

            with self.lock:
                task.progress = 100
                self._update_task_progress_in_db(task.task_id, task.progress)

            task.result = {
                "connection_id": connection_id,
                "entity_count": entity_count,
                "relationship_count": rel_count,
                "message": f"行级导入完成，共创建 {entity_count} 个实体，{rel_count} 条关系",
                "batch_size": batch_size
            }
            logger.info(f"[_execute_database_schema_import] 任务完成: {task.result}")

            # 保存 binlog 位点，供 CDC 增量同步衔接
            if binlog_info and database_name_for_uri:
                from cdc.cdc_manager import cdc_manager
                cdc_manager.save_binlog_checkpoint(connection_id, database_name_for_uri, binlog_info)

                # 可选：导入完成后自动启动增量同步
                if auto_start_cdc:
                    logger.info(f"全量导入完成，自动启动 CDC 增量同步: conn={connection_id}, db={database_name_for_uri}")
                    cdc_manager.start(connection_id, database_name_for_uri)

        except Exception as e:
            logger.error(f"执行数据库行级导入任务时出错: {e}")
            raise

    def _execute_document_generate_summary(self, task: Task):
        """执行文档概要生成任务"""
        logger.info(f"[_execute_document_generate_summary] 入参: task_id={task.task_id}")
        from pageindex import (
            generate_pageindex_pdf,
            generate_pageindex_md,
            generate_pageindex_txt,
        )

        try:
            source_id = task.payload.get("source_id")
            file_path = task.payload.get("file_path")
            full_path = task.payload.get("full_path")

            if not all([source_id, file_path, full_path]):
                raise ValueError("缺少必要参数: source_id, file_path, full_path")

            ext = os.path.splitext(full_path)[1].lower()
            logger.info(f"开始生成文档概要: source_id={source_id}, file={file_path}, ext={ext}")

            if ext == ".pdf":
                result = generate_pageindex_pdf(full_path)
            elif ext == ".md":
                result = generate_pageindex_md(full_path)
            elif ext == ".txt":
                result = generate_pageindex_txt(full_path)
            else:
                raise ValueError(f"不支持的文件类型: {ext}")

            with self.lock:
                task.progress = 70

            # 保存到 data/summaries/DOC/{source_id}/{file}.json
            summary_rel_path = file_path + ".json"
            summary_abs_path = os.path.join("data", "summaries", "DOC", source_id, summary_rel_path)
            os.makedirs(os.path.dirname(summary_abs_path), exist_ok=True)
            with open(summary_abs_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            logger.info(f"文档概要已保存: {summary_abs_path}")

            with self.lock:
                task.progress = 100

            task.result = {
                "status": "success",
                "file": file_path,
                "summary_path": summary_rel_path,
                "doc_name": result.get("doc_name", ""),
                "doc_description": result.get("doc_description", ""),
            }
            logger.info(f"[_execute_document_generate_summary] 完成: file={file_path}")

        except RuntimeError as e:
            logger.error(f"文档概要生成失败(模型不可用): {e}")
            raise
        except Exception as e:
            logger.error(f"文档概要生成任务异常: {e}")
            raise

# 创建全局任务管理器实例
task_manager = TaskManager()