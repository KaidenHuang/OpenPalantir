"""
CDC 事件处理器 — 将 Debezium 变更事件转化为 Neo4j 实体/关系操作
"""
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime

from config.neo4j_config import neo4j_conn
from cdc.schema_cache import SchemaCache
from system.logger import logger


class EventProcessor:
    """处理 Debezium CDC 事件，将其同步到 Neo4j"""

    def __init__(self, schema: SchemaCache, connection_id: str, database_name: str):
        self.schema = schema
        self.connection_id = connection_id
        self.database_name = database_name

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
                return "upsert"

        elif op == "u":
            # UPDATE
            row = event.get("after")
            if row:
                self._handle_upsert(table_name, row)
                return "upsert"

        elif op == "d":
            # DELETE
            row = event.get("before")
            if row:
                self._handle_delete(table_name, row)
                return "delete"

        return "skip"

    def _handle_upsert(self, table_name: str, row: Dict[str, Any]):
        """处理 INSERT 或 UPDATE 事件：MERGE 实体 + 同步 FK 关系"""
        entity_name = self.schema.build_entity_name(table_name, row)
        if not entity_name:
            return  # PK 值为空，跳过

        entity_id = hashlib.md5(entity_name.encode()).hexdigest()
        datasource = f"DBS://{self.connection_id}/{self.database_name}/{table_name}"
        entity_type = self.schema.entity_types.get(table_name, "其他")
        description = self._build_description(table_name, row)
        ts = datetime.now().isoformat()

        # MERGE 实体（与全量导入共享同一 entity_id 体系）
        query = """
        MERGE (e:Entity {id: $entity_id})
        SET e.name = $name,
            e.type = $type,
            e.datasource = $datasource,
            e.description = $description,
            e.count = 1,
            e.confidence = 1.0,
            e.cdc_updated_at = $ts
        REMOVE e._placeholder
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
        """处理 DELETE 事件：DETACH DELETE 实体及所有关联关系"""
        entity_name = self.schema.build_entity_name(table_name, row)
        if not entity_name:
            return

        entity_id = hashlib.md5(entity_name.encode()).hexdigest()

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

        # 1) 查询该实体当前的出向 FK 关系（通过 r.source = 'cdc_fk' 标识）
        existing_query = """
        MATCH (s:Entity {id: $entity_id})-[r:RELATED_TO]->(t:Entity)
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
            target_id = hashlib.md5(target_name.encode()).hexdigest()
            predicate = "Foreign key"
            rel_id = hashlib.md5(
                f"{subject_name}_{predicate}_{target_name}".encode()
            ).hexdigest()
            description = f"{table_name}.{fk['column']}={fk_value} -> {ref_table}"

            desired_rels[target_name] = {
                "target_id": target_id,
                "target_name": target_name,
                "predicate": predicate,
                "rel_id": rel_id,
                "description": description,
            }

        # 3) 删除不再需要的关系（FK 值变更导致旧目标失效）
        stale_targets = set(existing_map.keys()) - set(desired_rels.keys())
        for target_name in stale_targets:
            old_rel_id = existing_map[target_name]
            neo4j_conn.execute_query(
                "MATCH ()-[r:RELATED_TO {relationship_id: $rel_id}]->() DELETE r",
                {"rel_id": old_rel_id}
            )
            logger.debug(f"[CDC] 删除旧关系: {subject_name} -> {target_name}")

        # 4) 创建新增的关系（首次插入或 FK 值变更）
        #    使用 MERGE 创建目标占位节点：若目标实体尚未到达，先建空节点，
        #    后续 INSERT 事件到达时 MERGE 会更新同一节点（entity_id 确定性相同）
        new_targets = set(desired_rels.keys()) - set(existing_map.keys())
        for target_name in new_targets:
            desired = desired_rels[target_name]
            neo4j_conn.execute_query("""
                MATCH (s:Entity {id: $subject_id})
                MERGE (t:Entity {id: $target_id})
                ON CREATE SET t.name = $target_name, t._placeholder = true
                MERGE (s)-[r:RELATED_TO {relationship_id: $rel_id}]->(t)
                SET r.predicate = $predicate,
                    r.source = 'cdc_fk',
                    r.description = $description,
                    r.confidence = 1.0
            """, {
                "subject_id": subject_id,
                "target_id": desired["target_id"],
                "target_name": desired["target_name"],
                "rel_id": desired["rel_id"],
                "predicate": desired["predicate"],
                "description": desired["description"],
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
