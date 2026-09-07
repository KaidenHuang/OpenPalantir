import json
import os
import uuid
from typing import Any, Callable, Dict

from system.logger import logger

from .base import TaskHandler


class SchemaAnalyzeHandler(TaskHandler):
    """执行数据库Schema分析任务（阶段1）"""

    def execute(self, task, progress_callback: Callable[[int], None]) -> Dict:
        logger.info(
            f"[SchemaAnalyzeHandler] 入参: task_id={task.task_id}, task_type={task.task_type}"
        )
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

            progress_callback(10)

            logger.info("步骤1: 提取数据库Schema")
            schema = database_manager.extract_schema(
                connection_id, tables, ignore_tables, database_name=database_name
            )

            progress_callback(40)

            logger.info("步骤2: 使用LLM进行业务标注")
            db = SessionLocal()
            try:
                annotator = SchemaAnnotator(db_session=db)
                annotated_schema = annotator.batch_annotate(schema)
            finally:
                db.close()

            db_summary = (
                annotated_schema.pop("database_summary", {})
                if isinstance(annotated_schema, dict)
                else {}
            )

            progress_callback(70)

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

                from models.database import AnalyzedTable

                table_list = [
                    {k.lower(): v for k, v in t.items()}
                    for t in annotated_schema.get("tables", [])
                ]
                for tbl in table_list:
                    table_uri = (
                        f"DBS://{connection_id}/{analyzed_db_name}/{tbl['table_name']}"
                    )
                    existing_table = (
                        db.query(AnalyzedTable)
                        .filter(
                            AnalyzedTable.connection_id == connection_id,
                            AnalyzedTable.table_name == tbl["table_name"],
                        )
                        .first()
                    )
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
                    table_list = [
                        {k.lower(): v for k, v in t.items()}
                        for t in annotated_schema.get("tables", [])
                    ]
                    columns_list = [
                        {k.lower(): v for k, v in c.items()}
                        for c in annotated_schema.get("columns", [])
                    ]
                    raw_columns = [
                        {k.lower(): v for k, v in c.items()}
                        for c in schema.get("columns", [])
                    ]
                    raw_fks = [
                        {k.lower(): v for k, v in fk.items()}
                        for fk in schema.get("foreign_keys", [])
                    ]

                    columns_by_table = {}
                    for col in columns_list:
                        columns_by_table.setdefault(col["table_name"], []).append(col)

                    col_types = {}
                    for col in raw_columns:
                        tn = col.get("table_name", "")
                        cn = col.get("column_name", "")
                        dt = col.get("data_type", "")
                        if tn and cn:
                            col_types[(tn, cn)] = dt

                    fk_by_table = {}
                    for fk in raw_fks:
                        table = fk.get("table_name", "")
                        col = fk.get("column_name", "")
                        ref_table = fk.get("referenced_table_name", "")
                        ref_col = fk.get("referenced_column_name", "")
                        if table:
                            fk_by_table.setdefault(table, []).append(
                                {
                                    "column": col,
                                    "references": f"{ref_table}.{ref_col}",
                                }
                            )

                    pk_columns = {}
                    uk_columns = {}
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
                        col_names = [
                            c["column_name"]
                            for c in columns_by_table.get(tbl_name, [])
                        ]
                        cols_with_types = [
                            f'{c}({col_types.get((tbl_name, c), "")})'
                            for c in col_names
                        ]

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
                            table_keys.append(
                                {
                                    "column": fk_entry["column"],
                                    "type": "FOREIGN KEY",
                                    "references": fk_entry["references"],
                                }
                            )

                        structure_nodes.append(
                            {
                                "table_name": tbl_name,
                                "node_id": str(idx + 1).zfill(8),
                                "description": f"包含字段: {', '.join(cols_with_types)}",
                                "summary": tbl.get("business_description", ""),
                                "entity_type": tbl.get("entity_type", ""),
                                "keys": table_keys,
                            }
                        )

                    db_summary_file = {
                        "db_name": analyzed_db_name or "default",
                        "db_description": db_summary.get("overview", ""),
                        "business_domain": db_summary.get("business_domain", ""),
                        "key_entities": db_summary.get("key_entities", ""),
                        "table_count": len(table_list),
                        "structure": structure_nodes,
                    }

                    summary_dir = os.path.join("data", "summaries", "DBS", connection_id)
                    os.makedirs(summary_dir, exist_ok=True)
                    summary_filename = (
                        f"{analyzed_db_name or 'database_summary'}.json"
                    )
                    summary_path = os.path.join(summary_dir, summary_filename)
                    with open(summary_path, "w", encoding="utf-8") as f:
                        json.dump(db_summary_file, f, ensure_ascii=False, indent=2)
                    logger.info(f"数据库概要已保存: {summary_path}")
                except Exception as e:
                    logger.error(f"保存数据库概要时出错: {e}")

            progress_callback(100)

            table_count = len(annotated_schema.get("tables", []))
            column_count = len(annotated_schema.get("columns", []))
            fk_count = len(annotated_schema.get("foreign_keys", []))

            result = {
                "connection_id": connection_id,
                "table_count": table_count,
                "column_count": column_count,
                "foreign_key_count": fk_count,
                "message": f"分析完成，共 {table_count} 个表，{column_count} 个字段，{fk_count} 个外键约束",
            }
            task.result = result
            logger.info(f"[SchemaAnalyzeHandler] 任务完成: {result}")
            return result

        except Exception as e:
            logger.error(f"执行数据库Schema分析任务时出错: {e}")
            raise