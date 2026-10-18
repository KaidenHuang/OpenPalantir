"""
CDC 事件处理器 — 将 Debezium 变更事件转化为 Neo4j 实体/关系操作
"""
import json
import time
from typing import Dict, Any, Optional, List
from datetime import datetime

from config.neo4j_config import neo4j_conn
from cdc.schema_cache import SchemaCache
from knowledge_graph.source_scope import union_sources
from knowledge_graph.graph_performance import graph_performance
from utils.json_utils import db_json_dumps
from system.logger import logger
from models.ids import compute_entity_id
from ontology.predicates import canonical_rel_id, cypher_rel_type


class EventProcessor:
    """处理 Debezium CDC 事件，将其同步到 Neo4j"""

    def __init__(self, schema: SchemaCache, connection_id: str, database_name: str):
        self.schema = schema
        self.connection_id = connection_id
        self.database_name = database_name
        self._last_cache_clear = 0.0

    def _invalidate_graph_cache(self) -> None:
        """图谱写入后失效 Redis 快照缓存（5 秒节流，高频事件不逐条清）。"""
        now = time.time()
        if now - self._last_cache_clear >= 5:
            graph_performance.clear_cache("graph:*")
            self._last_cache_clear = now

    def _datasource(self, table_name: str) -> str:
        """事件所属来源 URI —— 与全量导入同一 DBS:// 体系，保证命中同一节点"""
        return f"DBS://{self.connection_id}/{self.database_name}/{table_name}"

    def process_event(self, event: Dict[str, Any]) -> str:
        """
        处理单条 Debezium 事件

        Args:
            event: Debezium payload dict

        Returns:
            操作类型: 'upsert' / 'delete' / 'skip'
        """
        op = event.get("op", "")
        source = event.get("source", {})
        table_name = source.get("table", "")

        if op in ("c", "r"):
            # INSERT 或 snapshot read
            row = event.get("after")
            if row:
                self._handle_upsert(table_name, row)
                self._invalidate_graph_cache()
                return "upsert"

        elif op == "u":
            # UPDATE
            row = event.get("after")
            if row:
                self._handle_upsert(table_name, row)
                self._invalidate_graph_cache()
                return "upsert"

        elif op == "d":
            # DELETE
            row = event.get("before")
            if row:
                self._handle_delete(table_name, row)
                self._invalidate_graph_cache()
                return "delete"

        return "skip"

    def _handle_upsert(self, table_name: str, row: Dict[str, Any]):
        """处理 INSERT 或 UPDATE 事件，按 table_role 分流"""
        role = self.schema.get_table_role(table_name)

        if role == "junction":
            self._handle_junction_upsert(table_name, row)
            return
        elif role == "attribute":
            self._handle_attribute_upsert(table_name, row)
            return

        # entity 表：正常 MERGE 实体 + 同步 FK 关系
        entity_name = self.schema.build_entity_name(table_name, row)
        if not entity_name:
            return  # PK 值为空，跳过

        entity_id = compute_entity_id(entity_name)
        datasource = self._datasource(table_name)
        entity_type = self.schema.entity_types.get(table_name, "other")
        description = self._build_description(table_name, row)
        ts = datetime.now().isoformat()

        # MERGE 实体（与全量导入共享同一 entity_id 体系）
        query = """
        MERGE (e:Entity {id: $entity_id})
        ON CREATE SET e.datasource = $datasource
        SET e.name = $name,
            e.type = $type,
            e.description = $description,
            e.count = 1,
            e.confidence = 1.0,
            e.cdc_updated_at = $ts
        REMOVE e._placeholder
        SET e.datasources = """ + union_sources('e', '$datasource') + """
        """
        neo4j_conn.execute_query(query, {
            "entity_id": entity_id,
            "name": entity_name,
            "type": entity_type,
            "datasource": datasource,
            "description": description,
            "ts": ts,
        })

        # 同步 FK 关系
        self._sync_fk_relationships(table_name, row, entity_id, entity_name)

    def _handle_delete(self, table_name: str, row: Dict[str, Any]):
        """处理 DELETE 事件，按 table_role 分流"""
        role = self.schema.get_table_role(table_name)

        if role == "junction":
            self._handle_junction_delete(table_name, row)
            return
        elif role == "attribute":
            # 属性表删除暂不处理（父实体属性需要重新聚合，复杂度高）
            logger.debug(f"[CDC] 跳过属性表 DELETE: {table_name}")
            return

        entity_name = self.schema.build_entity_name(table_name, row)
        if not entity_name:
            return

        entity_id = compute_entity_id(entity_name)

        neo4j_conn.execute_query(
            "MATCH (n:Entity {id: $id}) DETACH DELETE n",
            {"id": entity_id}
        )
        logger.debug(f"[CDC] DELETE 实体: {entity_name} (id={entity_id})")

    def _sync_fk_relationships(
        self,
        table_name: str,
        row: Dict[str, Any],
        subject_id: str,
        subject_name: str
    ):
        """根据当前行数据中的 FK 值，同步该实体的出向 FK 关系

        策略：查旧 → 算新 → 差量删/建
        所有操作均幂等，重复调用结果不变
        """
        fk_defs = self.schema.fk_columns.get(table_name, [])
        if not fk_defs:
            return

        # 1) 查询该实体当前的出向 FK 关系（通过 r.source = 'cdc_fk' 标识；泛型匹配全部 LinkType）
        existing_query = """
        MATCH (s:Entity {id: $entity_id})-[r]->(t:Entity)
        WHERE r.source = 'cdc_fk'
        RETURN r.relationship_id as rel_id, t.name as target_name
        """
        existing_rels = neo4j_conn.execute_query(existing_query, {"entity_id": subject_id})
        existing_map = {r["target_name"]: r["rel_id"] for r in existing_rels}

        # 2) 根据当前行数据计算应该存在的关系
        desired_rels: Dict[str, Dict] = {}
        for fk in fk_defs:
            fk_value = row.get(fk["column"])
            if fk_value is None or str(fk_value).strip() == "" or str(fk_value) == "None":
                continue

            ref_table = fk["referenced_table_name"]
            target_name = f"{ref_table}:{fk_value}"
            target_id = compute_entity_id(target_name)
            raw_predicate = "Foreign key"
            rel_id, predicate, hit = canonical_rel_id(subject_name, raw_predicate, target_name)
            if not hit:
                logger.warning(f"[CDC] FK 谓词未命中受控词表，归一为 '{predicate}'")
            description = f"{table_name}.{fk['column']}={fk_value} -> {ref_table}"

            desired_rels[target_name] = {
                "target_id": target_id,
                "target_name": target_name,
                "predicate": predicate,
                "raw_predicate": raw_predicate if raw_predicate != predicate else "",
                "rel_id": rel_id,
                "description": description,
            }

        # 3) 删除不再需要的关系（FK 值变更导致旧目标失效）
        stale_targets = set(existing_map.keys()) - set(desired_rels.keys())
        for target_name in stale_targets:
            old_rel_id = existing_map[target_name]
            neo4j_conn.execute_query(
                "MATCH ()-[r {relationship_id: $rel_id}]->() DELETE r",
                {"rel_id": old_rel_id}
            )
            logger.debug(f"[CDC] 删除旧关系: {subject_name} -> {target_name}")

        # 4) 创建新增的关系（首次插入或 FK 值变更）
        #    使用 MERGE 创建目标占位节点：若目标实体尚未到达，先建空节点，
        #    后续 INSERT 事件到达时 MERGE 会更新同一节点（entity_id 确定性相同）
        new_targets = set(desired_rels.keys()) - set(existing_map.keys())
        for target_name in new_targets:
            desired = desired_rels[target_name]
            rel_type = cypher_rel_type(desired["predicate"])
            neo4j_conn.execute_query(f"""
                MATCH (s:Entity {{id: $subject_id}})
                MERGE (t:Entity {{id: $target_id}})
                ON CREATE SET t.name = $target_name, t._placeholder = true
                MERGE (s)-[r:{rel_type} {{relationship_id: $rel_id}}]->(t)
                ON CREATE SET r.datasource = $datasource
                SET r.predicate = $predicate,
                    r.raw_predicate = $raw_predicate,
                    r.source = 'cdc_fk',
                    r.description = $description,
                    r.confidence = 1.0
                SET r.datasources = {union_sources('r', '$datasource')}
            """, {
                "subject_id": subject_id,
                "target_id": desired["target_id"],
                "target_name": desired["target_name"],
                "rel_id": desired["rel_id"],
                "predicate": desired["predicate"],
                "raw_predicate": desired["raw_predicate"],
                "description": desired["description"],
                "datasource": self._datasource(table_name),
            })
            logger.debug(f"[CDC] 创建关系: {subject_name} -> {target_name}")

    def _build_description(self, table_name: str, row: Dict[str, Any]) -> str:
        """构建实体描述：所有列 col=val 拼接"""
        col_names = self.schema.get_all_column_names(table_name)
        if col_names:
            parts = [f"{col}={row.get(col, '')}" for col in col_names]
        else:
            parts = [f"{k}={v}" for k, v in row.items()]
        return ", ".join(parts)

    # ── Junction 表处理 ──

    def _handle_junction_upsert(self, table_name: str, row: Dict[str, Any]):
        """关联表 INSERT/UPDATE：不创建实体，在被引用实体之间创建直接关系边"""
        fk_defs = self.schema.fk_columns.get(table_name, [])
        if len(fk_defs) < 2:
            return

        # 解析各 FK 值对应的目标实体
        targets = []
        fk_col_names = set()
        for fk in fk_defs:
            fk_col = fk["column"]
            fk_col_names.add(fk_col)
            fk_val = row.get(fk_col)
            if fk_val is None or str(fk_val).strip() == "" or str(fk_val) == "None":
                continue
            ref_table = fk["referenced_table_name"]
            target_name = f"{ref_table}:{fk_val}"
            target_id = compute_entity_id(target_name)
            targets.append((ref_table, target_name, target_id))

        if len(targets) < 2:
            return

        # 非 FK 列作为关系属性
        attrs = {k: v for k, v in row.items() if k not in fk_col_names and v is not None}
        attrs_str = db_json_dumps(attrs) if attrs else "{}"

        # 为每对 (A, B) 创建单向关系 A→B（避免双向重复）
        for i in range(len(targets)):
            for j in range(i + 1, len(targets)):
                _, src_name, src_id = targets[i]
                _, tgt_name, tgt_id = targets[j]
                rel_id, predicate, hit = canonical_rel_id(src_name, table_name, tgt_name)
                if not hit:
                    logger.debug(f"[CDC] Junction 表名谓词 '{table_name}' 不在受控词表，归一为 '{predicate}'")
                description = f"{table_name}: {src_name} -> {tgt_name}"
                rel_type = cypher_rel_type(predicate)

                neo4j_conn.execute_query(f"""
                    MERGE (s:Entity {{id: $src_id}})
                    ON CREATE SET s.name = $src_name, s._placeholder = true
                    MERGE (t:Entity {{id: $tgt_id}})
                    ON CREATE SET t.name = $tgt_name, t._placeholder = true
                    MERGE (s)-[r:{rel_type} {{relationship_id: $rel_id}}]->(t)
                    ON CREATE SET r.datasource = $datasource
                    SET r.predicate = $predicate,
                        r.raw_predicate = $raw_predicate,
                        r.source = 'cdc_junction',
                        r.description = $description,
                        r.attributes = $attributes,
                        r.confidence = 1.0
                    SET r.datasources = {union_sources('r', '$datasource')}
                """, {
                    "src_id": src_id, "src_name": src_name,
                    "tgt_id": tgt_id, "tgt_name": tgt_name,
                    "rel_id": rel_id, "predicate": predicate,
                    "raw_predicate": table_name if table_name != predicate else "",
                    "description": description, "attributes": attrs_str,
                    "datasource": self._datasource(table_name),
                })
                logger.debug(f"[CDC] Junction 关系: {src_name} -> {tgt_name}")

    def _handle_junction_delete(self, table_name: str, row: Dict[str, Any]):
        """关联表 DELETE：删除对应的直接关系边"""
        fk_defs = self.schema.fk_columns.get(table_name, [])
        if len(fk_defs) < 2:
            return

        targets = []
        for fk in fk_defs:
            fk_val = row.get(fk["column"])
            if fk_val is None or str(fk_val).strip() == "" or str(fk_val) == "None":
                continue
            ref_table = fk["referenced_table_name"]
            target_name = f"{ref_table}:{fk_val}"
            targets.append(target_name)

        if len(targets) < 2:
            return

        for i in range(len(targets)):
            for j in range(i + 1, len(targets)):
                rel_id, predicate, _hit = canonical_rel_id(targets[i], table_name, targets[j])
                neo4j_conn.execute_query(
                    "MATCH ()-[r {relationship_id: $rel_id}]->() DELETE r",
                    {"rel_id": rel_id}
                )
                logger.debug(f"[CDC] 删除 Junction 关系: {targets[i]} -> {targets[j]}")

    # ── Attribute 表处理 ──

    def _handle_attribute_upsert(self, table_name: str, row: Dict[str, Any]):
        """属性表 INSERT/UPDATE：不创建实体，将数据合并到父实体的 attributes"""
        fk_defs = self.schema.fk_columns.get(table_name, [])
        if len(fk_defs) != 1:
            return

        fk = fk_defs[0]
        fk_col = fk["column"]
        fk_val = row.get(fk_col)
        if fk_val is None or str(fk_val).strip() == "" or str(fk_val) == "None":
            return

        ref_table = fk["referenced_table_name"]
        parent_name = f"{ref_table}:{fk_val}"
        parent_id = compute_entity_id(parent_name)

        # 去掉 FK 列，剩余列作为属性记录
        attr_record = {k: v for k, v in row.items() if k != fk_col and v is not None}
        if not attr_record:
            return

        # 读取父实体现有 attributes
        result = neo4j_conn.execute_query(
            "MATCH (e:Entity {id: $id}) RETURN e.attributes as attrs",
            {"id": parent_id}
        )
        existing_attrs = {}
        if result:
            raw = result[0].get("attrs", "{}")
            if isinstance(raw, str):
                try:
                    existing_attrs = json.loads(raw)
                except Exception:
                    existing_attrs = {}
            elif isinstance(raw, dict):
                existing_attrs = raw

        # 合并：按表名分组，追加或更新记录
        table_records = existing_attrs.get(table_name, [])
        # 简单追加（如果记录已存在则替换最后一条）
        table_records.append(attr_record)
        existing_attrs[table_name] = table_records

        neo4j_conn.execute_query(
            "MATCH (e:Entity {id: $id}) SET e.attributes = $attrs",
            {"id": parent_id, "attrs": db_json_dumps(existing_attrs)}
        )
        logger.debug(f"[CDC] 属性合并: {table_name} -> {parent_name}")
