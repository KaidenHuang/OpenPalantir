import time
from typing import Callable, Dict, List, Tuple

from database_management.import_helpers import (
    _DEFAULT_ENTITY_TYPE,
    _MAX_CROSS_PRODUCT_PAIRS,
    build_entities_batch,
    build_entity_name,
    build_relationships_from_index,
    build_junction_relationships,
    classify_tables_by_role,
    detect_primary_keys,
    extract_pk_value,
    get_fk_column_info,
    refine_pks_via_dialect,
)
from models.ids import compute_entity_id, compute_relationship_id
from system.logger import logger

from .base import TaskHandler


def _flush_attributes_batch(accumulator, neo4j_conn, db_json_dumps, compute_entity_id_fn):
    """将累积的属性数据批量合并写入 Neo4j（多属性表安全，不覆盖已有键）

    策略：先读取已有 e.attributes → Python 侧合并 → 写回
    无需 APOC 插件，兼容所有 Neo4j 版本
    """
    import json as _json

    if not accumulator:
        return 0

    # 1) 构建 entity_id → (parent_name, new_attrs) 映射
    id_to_parent = {}
    batch_ids = []
    for parent_name, table_attrs in accumulator.items():
        entity_id = compute_entity_id_fn(parent_name)
        id_to_parent[entity_id] = (parent_name, table_attrs)
        batch_ids.append(entity_id)

    # 2) 批量读取现有 attributes
    result = neo4j_conn.execute_query(
        "UNWIND $ids AS eid MATCH (e:Entity {id: eid}) "
        "RETURN e.id AS id, e.attributes AS attrs",
        {"ids": batch_ids}
    )
    existing: dict = {}
    for record in result:
        raw = record["attrs"]
        if isinstance(raw, str):
            try:
                existing[record["id"]] = _json.loads(raw)
            except Exception:
                existing[record["id"]] = {}
        elif isinstance(raw, dict):
            existing[record["id"]] = raw

    # 3) 合并并批量写回
    update_batch = []
    for eid in batch_ids:
        parent_name, table_attrs = id_to_parent[eid]
        attrs = existing.get(eid, {})
        for attr_table, rows in table_attrs.items():
            attrs[attr_table] = rows
        update_batch.append({
            "id": eid,
            "attrs": db_json_dumps(attrs)
        })

    if update_batch:
        neo4j_conn.execute_query(
            "UNWIND $batch AS item "
            "MATCH (e:Entity {id: item.id}) "
            "SET e.attributes = item.attrs",
            {"batch": update_batch}
        )
    return len(update_batch)


def _save_junction_batch(relationships, neo4j_conn, db_json_dumps, compute_entity_id_fn):
    """将一批 junction 关系直接写入 Neo4j"""
    batch = []
    for rel in relationships:
        src_id = compute_entity_id_fn(rel["s"])
        tgt_id = compute_entity_id_fn(rel["o"])
        rel_id = compute_relationship_id(rel["s"], rel["p"], rel["o"])
        batch.append({
            "src_id": src_id, "src_name": rel["s"],
            "tgt_id": tgt_id, "tgt_name": rel["o"],
            "rel_id": rel_id,
            "predicate": rel["p"],
            "description": rel["d"],
            "attributes": db_json_dumps(rel.get("a", {})),
        })
    if batch:
        neo4j_conn.execute_query(
            "UNWIND $batch AS item "
            "MERGE (s:Entity {id: item.src_id}) "
            "ON CREATE SET s.name = item.src_name, s._placeholder = true "
            "MERGE (t:Entity {id: item.tgt_id}) "
            "ON CREATE SET t.name = item.tgt_name, t._placeholder = true "
            "MERGE (s)-[r:RELATED_TO {relationship_id: item.rel_id}]->(t) "
            "SET r.predicate = item.predicate, r.source = 'junction_import', "
            "r.description = item.description, r.attributes = item.attributes, "
            "r.confidence = 1.0",
            {"batch": batch}
        )
    return len(batch)


class SchemaImportHandler(TaskHandler):
    """执行数据库行级数据导入知识图谱任务（阶段2）— 分批导入"""

    def execute(self, task, progress_callback: Callable[[int], None]) -> Dict:
        logger.info(
            f"[SchemaImportHandler] 入参: task_id={task.task_id}, task_type={task.task_type}"
        )
        try:
            from database_management.database_service import DatabaseService
            from database_management.database_manager import database_manager, DIALECT_MAP
            from utils.data_store import EntityDataStore
            from config.database import SessionLocal

            connection_id = task.payload.get("connection_id")
            batch_size = task.payload.get("batch_size", 5000)
            row_limit = task.payload.get("row_limit", 0)
            neo4j_batch_size = task.payload.get("neo4j_batch_size", 20000)
            use_merge = task.payload.get("use_merge", False)
            auto_start_cdc = task.payload.get("auto_start_cdc", False)

            logger.info(
                f"开始执行数据库行级导入任务，连接ID: {connection_id}, "
                f"源批量大小: {batch_size}, Neo4j写入批大小: {neo4j_batch_size}, use_merge={use_merge}"
            )

            if not connection_id:
                raise ValueError("缺少connection_id")

            progress_callback(10)

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
                        "service_name": getattr(conn_config, "service_name", None),
                    }
            finally:
                db.close()

            if not schema["tables"]:
                raise ValueError("未找到Schema信息，请先执行分析任务")

            columns_by_table: Dict[str, List[Dict]] = {}
            for col in schema["columns"]:
                columns_by_table.setdefault(col["table_name"], []).append(col)

            progress_callback(20)

            logger.info("步骤2: 检测主键列")
            pk_columns = detect_primary_keys(columns_by_table)
            logger.info(f"主键检测完成: {len(pk_columns)} 个表")

            progress_callback(25)

            fk_column_info = get_fk_column_info(
                schema["foreign_keys"],
                schema.get("inferred_relationships", []),
            )
            logger.info(f"外键/关联索引列数: {len(fk_column_info)} 个表")

            # --- 按 table_role 分类 ---
            fk_defs_by_table: Dict[str, List[Dict]] = {}
            for fk in schema["foreign_keys"]:
                tbl = fk.get("table_name") or fk.get("TABLE_NAME", "")
                if tbl:
                    fk_defs_by_table.setdefault(tbl, []).append(fk)

            role_map = classify_tables_by_role(
                schema["tables"], pk_columns, schema["foreign_keys"], columns_by_table
            )
            junction_table_names = [t for t, r in role_map.items() if r == "junction"]
            attribute_table_names = [t for t, r in role_map.items() if r == "attribute"]
            # junction/attribute 表不产生常规 FK 关系
            skip_fk_tables = set(junction_table_names) | set(attribute_table_names)

            # --- Phase 1: 分批导入实体 + 流式属性/关联 ---
            pk_index: Dict[str, Dict[str, str]] = {}
            fk_index: Dict[str, Dict[str, Dict[str, str]]] = {}
            all_saved_entities: List[Tuple[str, str]] = []

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

            refine_pks_via_dialect(
                pk_columns, columns_by_table, dialect, conn,
                [t["table_name"] for t in schema["tables"]],
            )

            binlog_info = dialect.capture_binlog_position(conn)
            if binlog_info:
                logger.info(f"已捕获 binlog 位点: {binlog_info}")
                logger.warning(
                    f"[CDC] binlog 位点已记录，但仅在导入成功完成后保存检查点。"
                    f"若导入中途失败，需重新执行全量导入才能启用 CDC 增量同步。"
                )

            from knowledge_graph.graph_manager import graph_manager

            try:
                graph_manager.performance.create_indexes()
                logger.info("Neo4j 索引已就绪")
            except Exception as e:
                logger.warning(f"创建 Neo4j 索引失败（可能已存在）: {e}")

            database_name_for_uri = analyzed_db_names[0] if analyzed_db_names else ""
            db_prefix = f"DBS://{connection_id}"
            if database_name_for_uri:
                db_prefix += f"/{database_name_for_uri}"

            deleted_count = graph_manager.delete_entities_by_datasource(db_prefix)
            if deleted_count > 0:
                logger.info(f"全量导入前清理旧数据: 删除 {deleted_count} 个实体（datasource={db_prefix}）")

            graph_manager.set_defer_cache(True)

            actual_row_counts: Dict[str, int] = {}

            try:
                # ── 步骤 3a: entity 表 ──
                entity_tables = [t for t in schema["tables"]
                                 if role_map.get(t["table_name"], "entity") == "entity"]
                logger.info(f"步骤3a: 导入 {len(entity_tables)} 个实体表")

                for table_idx, table_info in enumerate(entity_tables):
                    full_table_name = table_info["table_name"]
                    entity_type = table_info.get("entity_type", _DEFAULT_ENTITY_TYPE)
                    table_pks = pk_columns.get(full_table_name, [])
                    table_cols = columns_by_table.get(full_table_name, [])
                    col_names = [c["column_name"] for c in table_cols]

                    if not col_names or not table_pks:
                        logger.warning(f"跳过表 {full_table_name}: 无有效列或主键")
                        continue

                    fk_cols_for_table = fk_column_info.get(full_table_name, set())
                    need_fk_index = bool(fk_cols_for_table)

                    table_pk_idx: Dict[str, str] = {}
                    table_fk_idx: Dict[str, Dict[str, str]] = {}
                    for fcol in fk_cols_for_table:
                        table_fk_idx[fcol] = {}

                    batch_count = 0
                    total_rows_for_table = 0
                    entity_buffer: List[Dict] = []

                    for batch in dialect.fetch_table_rows_keyset(
                        conn, full_table_name, col_names, table_pks, batch_size, max_rows=row_limit
                    ):
                        batch_count += 1
                        total_rows_for_table += len(batch)
                        logger.info(
                            f"  表 {full_table_name}: 第 {batch_count} 批 ({len(batch)} 行，"
                            f"累计 {total_rows_for_table})"
                        )

                        entities_batch = build_entities_batch(
                            batch, full_table_name, entity_type, table_pks, db_prefix
                        )
                        if entities_batch:
                            entity_buffer.extend(entities_batch)

                        for row in batch:
                            pk_val = extract_pk_value(row, table_pks)
                            if pk_val is None:
                                continue
                            entity_name = build_entity_name(full_table_name, row, table_pks)
                            if entity_name:
                                table_pk_idx[pk_val] = entity_name

                        if need_fk_index:
                            for row in batch:
                                entity_name = build_entity_name(full_table_name, row, table_pks)
                                if not entity_name:
                                    continue
                                for fcol in fk_cols_for_table:
                                    fk_val = str(row.get(fcol, ""))
                                    if fk_val and fk_val != "None":
                                        table_fk_idx[fcol][fk_val] = entity_name

                        if len(entity_buffer) >= neo4j_batch_size:
                            saved_batch = EntityDataStore.save_entities_only(
                                entity_buffer, db_prefix
                            )
                            all_saved_entities.extend(
                                (e.get("name", ""), e.get("entity_id", ""))
                                for e in saved_batch
                            )
                            entity_buffer.clear()

                    if entity_buffer:
                        saved_batch = EntityDataStore.save_entities_only(
                            entity_buffer, db_prefix
                        )
                        all_saved_entities.extend(
                            (e.get("name", ""), e.get("entity_id", ""))
                            for e in saved_batch
                        )
                        entity_buffer.clear()

                    pk_index[full_table_name] = table_pk_idx
                    if need_fk_index:
                        fk_index[full_table_name] = table_fk_idx

                    logger.info(
                        f"  表 {full_table_name}: 完成，共 {total_rows_for_table} 行，"
                        f"{len(table_pk_idx)} 个索引条目"
                    )
                    actual_row_counts[full_table_name] = total_rows_for_table

                    progress_pct = 30 + int(25 * (table_idx + 1) / len(entity_tables))
                    progress_callback(min(progress_pct, 55))

                # ── 步骤 3b: attribute 表（流式） ──
                FLUSH_SIZE = 50000
                if attribute_table_names:
                    logger.info(f"步骤3b: 流式处理 {len(attribute_table_names)} 个属性表")
                    from utils.json_utils import db_json_dumps
                    from config.neo4j_config import neo4j_conn

                    for attr_idx, attr_table in enumerate(attribute_table_names):
                        fks = fk_defs_by_table.get(attr_table, [])
                        if len(fks) != 1:
                            continue

                        fk = fks[0]
                        fk_col = fk.get("column_name") or fk.get("COLUMN_NAME", "")
                        ref_table = fk.get("referenced_table_name") or fk.get("REFERENCED_TABLE_NAME", "")
                        if not fk_col or not ref_table:
                            continue

                        table_cols = columns_by_table.get(attr_table, [])
                        col_names = [c["column_name"] for c in table_cols]
                        table_pks = pk_columns.get(attr_table, [])

                        attr_accumulator: Dict[str, Dict[str, list]] = {}
                        record_count = 0
                        total_rows_for_table = 0

                        for batch in dialect.fetch_table_rows_keyset(
                            conn, attr_table, col_names, table_pks, batch_size, max_rows=row_limit
                        ):
                            total_rows_for_table += len(batch)
                            for row in batch:
                                fk_val = row.get(fk_col)
                                if fk_val is None or str(fk_val).strip() == "" or str(fk_val) == "None":
                                    continue
                                parent_name = pk_index.get(ref_table, {}).get(str(fk_val))
                                if not parent_name:
                                    continue
                                attr_record = {k: v for k, v in row.items()
                                               if k != fk_col and v is not None}
                                if not attr_record:
                                    continue
                                attr_accumulator.setdefault(
                                    parent_name, {}
                                ).setdefault(attr_table, []).append(attr_record)
                                record_count += 1

                            if record_count >= FLUSH_SIZE:
                                flushed = _flush_attributes_batch(
                                    attr_accumulator, neo4j_conn, db_json_dumps, compute_entity_id
                                )
                                logger.info(f"  属性批量更新: {flushed} 个实体, {record_count} 条属性记录")
                                attr_accumulator.clear()
                                record_count = 0

                        if record_count > 0:
                            flushed = _flush_attributes_batch(
                                attr_accumulator, neo4j_conn, db_json_dumps, compute_entity_id
                            )
                            logger.info(f"  属性批量更新(尾批): {flushed} 个实体, {record_count} 条属性记录")
                        del attr_accumulator

                        actual_row_counts[attr_table] = total_rows_for_table
                        logger.info(f"  属性表 {attr_table}: 完成，共 {total_rows_for_table} 行")
                        progress_pct = 55 + int(10 * (attr_idx + 1) / len(attribute_table_names))
                        progress_callback(min(progress_pct, 65))

                # ── 步骤 3c: junction 表（流式） ──
                junction_tables_list = [t for t in schema["tables"]
                                        if role_map.get(t["table_name"], "entity") == "junction"]
                if junction_tables_list:
                    logger.info(f"步骤3c: 流式处理 {len(junction_tables_list)} 个关联表")
                    from utils.json_utils import db_json_dumps
                    from config.neo4j_config import neo4j_conn

                    for jt_idx, jt_info in enumerate(junction_tables_list):
                        jt_name = jt_info["table_name"]
                        fks = fk_defs_by_table.get(jt_name, [])
                        if len(fks) < 2:
                            continue

                        table_cols = columns_by_table.get(jt_name, [])
                        col_names = [c["column_name"] for c in table_cols]
                        table_pks = pk_columns.get(jt_name, [])

                        total_rows_for_table = 0
                        total_rels = 0

                        for batch in dialect.fetch_table_rows_keyset(
                            conn, jt_name, col_names, table_pks, batch_size, max_rows=row_limit
                        ):
                            total_rows_for_table += len(batch)
                            rels = build_junction_relationships(
                                [jt_name], {jt_name: batch}, fk_defs_by_table, pk_index
                            )
                            if rels:
                                saved = _save_junction_batch(
                                    rels, neo4j_conn, db_json_dumps, compute_entity_id
                                )
                                total_rels += saved
                            del rels

                        actual_row_counts[jt_name] = total_rows_for_table
                        logger.info(f"  关联表 {jt_name}: 完成，共 {total_rows_for_table} 行，{total_rels} 条关系")
                        progress_pct = 65 + int(5 * (jt_idx + 1) / len(junction_tables_list))
                        progress_callback(min(progress_pct, 70))

            finally:
                conn.close()
            t_close = time.time()

            graph_manager.set_defer_cache(False)
            t_defer = time.time()
            graph_manager.performance.clear_cache("graph:*")
            t_cache = time.time()

            entity_count = len(all_saved_entities)
            logger.info(f"分批导入完成，共 {entity_count} 个实体")
            logger.info(
                f"  耗时细分: conn.close={t_defer-t_close:.3f}s  "
                f"defer_cache={t_cache-t_defer:.3f}s"
            )

            # --- 用实际行数更新 SQLite（替换 information_schema 的估算值）---
            if actual_row_counts:
                try:
                    from config.database import SessionLocal
                    from models.database import DatabaseTable
                    update_db = SessionLocal()
                    try:
                        for tbl_name, cnt in actual_row_counts.items():
                            update_db.query(DatabaseTable).filter(
                                DatabaseTable.connection_id == connection_id,
                                DatabaseTable.table_name == tbl_name
                            ).update({"row_count": cnt})
                        update_db.commit()
                        logger.info(f"已更新 {len(actual_row_counts)} 个表的行数（实际值）")
                    finally:
                        update_db.close()
                except Exception as e:
                    logger.warning(f"更新表行数失败: {e}")

            progress_callback(75)

            # --- Phase 2: 从索引构建关系 ---
            logger.info("步骤4: 使用索引构建行级关系")
            t_phase2 = time.time()
            logger.info(f"  Phase1→Phase2 间隔: {t_phase2-t_cache:.3f}s")
            relationships = build_relationships_from_index(
                foreign_keys=schema["foreign_keys"],
                inferred_relationships=schema.get("inferred_relationships", []),
                pk_index=pk_index,
                fk_index=fk_index,
                max_cross_product_pairs=_MAX_CROSS_PRODUCT_PAIRS,
                skip_tables=skip_fk_tables,
            )

            logger.info(f"关系构建完成: {len(relationships)} 条")

            del pk_index
            del fk_index

            progress_callback(85)

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

                rel_count = EntityDataStore.save_relationships_only(
                    relationships, entity_name_map, use_create=not use_merge
                )
                logger.info(f"关系保存完成: {rel_count} 条")
            else:
                del all_saved_entities

            progress_callback(100)

            result = {
                "connection_id": connection_id,
                "entity_count": entity_count,
                "relationship_count": rel_count,
                "message": f"行级导入完成，共创建 {entity_count} 个实体，{rel_count} 条关系",
                "batch_size": batch_size,
            }
            task.result = result
            logger.info(f"[SchemaImportHandler] 任务完成: {result}")

            if binlog_info and database_name_for_uri:
                from cdc.cdc_manager import cdc_manager

                cdc_manager.save_binlog_checkpoint(
                    connection_id, database_name_for_uri, binlog_info
                )

                if auto_start_cdc:
                    logger.info(
                        f"全量导入完成，自动启动 CDC 增量同步: "
                        f"conn={connection_id}, db={database_name_for_uri}"
                    )
                    cdc_manager.start(connection_id, database_name_for_uri)

            return result

        except Exception as e:
            logger.error(f"执行数据库行级导入任务时出错: {e}")
            raise