import os
from typing import Any, Callable, Dict

from system.logger import logger

from .base import TaskHandler


class SchemaAnalyzeHandler(TaskHandler):
    """执行数据库Schema分析任务（阶段1）"""

    TASK_TYPE = "database_schema_analyze"
    REQUIRED_KEYS = ("connection_id",)
    OPTIONAL_DEFAULTS = {"tables": None, "ignore_tables": None,
                         "database_name": None, "domain": "general"}

    def execute(self, task, progress_callback: Callable[[int], None]) -> Dict:
        logger.info(
            f"[SchemaAnalyzeHandler] 入参: task_id={task.task_id}, task_type={task.task_type}"
        )
        try:
            from config.database import SessionLocal
            from content_extraction.database.store import schema_store
            from content_extraction.database.schema_reader import extract_schema_for_connection
            from source_registry.database.registry import database_source_registry
            from summary_generation.database import store
            from summary_generation.database.build import build_db_summary_file

            connection_id = task.payload.get("connection_id")
            tables = task.payload.get("tables")
            ignore_tables = task.payload.get("ignore_tables")
            database_name = task.payload.get("database_name")
            domain = self.payload_value(task, "domain")

            logger.info(f"开始执行数据库Schema分析任务，连接ID: {connection_id}, 数据库: {database_name}")

            if not connection_id:
                raise ValueError("缺少connection_id")

            progress_callback(10)

            logger.info("步骤1: 提取数据库Schema（含视图）")
            schema = extract_schema_for_connection(
                connection_id, tables, ignore_tables, database_name
            )

            progress_callback(40)

            logger.info("步骤2: 使用LLM进行业务标注")
            db = SessionLocal()
            try:
                from summary_generation.database.annotator import SchemaAnnotator
                annotator = SchemaAnnotator(db_session=db, domain=domain)
                annotated_schema = annotator.batch_annotate(schema)
            finally:
                db.close()

            db_summary = (
                annotated_schema.pop("database_summary", {})
                if isinstance(annotated_schema, dict)
                else {}
            )

            progress_callback(70)

            logger.info("步骤3: 保存分析结果到SQLite")
            analyzed_db_name = None
            sess = SessionLocal()
            try:
                schema_store.save_schema(sess, connection_id, annotated_schema)

                conn = database_source_registry.get(sess, connection_id)
                analyzed_db_name = database_name or (conn.database if conn else None)
                if analyzed_db_name:
                    schema_store.save_analyzed_database(sess, connection_id, analyzed_db_name)
                    logger.info(f"已分析数据库已记录: {analyzed_db_name}")

                table_list = [
                    {k.lower(): v for k, v in t.items()}
                    for t in annotated_schema.get("tables", [])
                ]
                schema_store.save_analyzed_tables(sess, connection_id, analyzed_db_name, table_list)
                logger.info(f"已为 {len(table_list)} 个表创建 AnalyzedTable 记录")
            finally:
                sess.close()

            # 步骤4: 组装并保存数据库概要到本地文件
            if db_summary and db_summary.get("overview"):
                try:
                    summary_data = build_db_summary_file(
                        connection_id, analyzed_db_name, db_summary, annotated_schema
                    )
                    store.save(connection_id, analyzed_db_name, summary_data)
                except Exception as e:
                    logger.error(f"保存数据库概要时出错: {e}")

            progress_callback(100)

            table_count = len(annotated_schema.get("tables", []))
            column_count = len(annotated_schema.get("columns", []))
            fk_count = len(annotated_schema.get("foreign_keys", []))
            view_count = len(annotated_schema.get("views", []))

            result = {
                "connection_id": connection_id,
                "table_count": table_count,
                "column_count": column_count,
                "foreign_key_count": fk_count,
                "view_count": view_count,
                "message": (f"分析完成，共 {table_count} 个表，{column_count} 个字段，"
                            f"{fk_count} 个外键约束，{view_count} 个视图"),
            }
            task.result = result
            logger.info(f"[SchemaAnalyzeHandler] 任务完成: {result}")
            return result

        except Exception as e:
            logger.error(f"执行数据库Schema分析任务时出错: {e}")
            raise
