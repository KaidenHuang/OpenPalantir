"""
关系仓库 — 封装 Neo4j 类型化关系边（LinkType）的全部 CRUD 操作

从 GraphManager 中拆出，职责单一：关系增删改查。
GraphManager 作为薄门面委托调用本模块。

本体约束（M2）：
- 边类型 = 归一化后的受控 LinkType key（写入前经 ontology.predicates 归一）
- relationship_id = MD5(subject_受控谓词_object)，归一化先于 ID 计算
- predicate 属性与边类型保持一致；未知谓词兜底为「其他」并记录 raw_predicate
- Cypher 类型名插值仅允许来自本体词表的值（cypher_rel_type 白名单校验）

来源约束（M3）：
- 边记 datasource（主来源）与 datasources（全部佐证来源），回收按 datasources 判定
"""
from typing import Any, Dict, List, Tuple
from config.neo4j_config import neo4j_conn
from knowledge_graph.graph_performance import graph_performance
from knowledge_graph.source_scope import match_prefix, strip_prefix, union_sources
from utils.json_utils import db_json_dumps
from ontology.predicates import cypher_rel_type, normalize_predicate, canonical_rel_id
from system.logger import logger


def _normalize_rel(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """单条关系字典 → (归一化后的写入行, 是否命中词表)

    归一化内容：predicate → 受控 key；有 subject/object 名时重算 relationship_id。
    """
    subject = raw.get("subject") or ""
    object_name = raw.get("object") or ""
    raw_predicate = raw.get("predicate") or ""

    if subject and object_name:
        rel_id, pkey, hit = canonical_rel_id(subject, raw_predicate, object_name)
    else:
        rel_id = raw.get("relationship_id") or ""
        pkey, hit = normalize_predicate(raw_predicate)

    attrs = raw.get("attributes", {})
    attrs_str = attrs if isinstance(attrs, str) else (
        db_json_dumps(attrs) if attrs else "{}"
    )

    row = {
        'subject': subject,
        'target': object_name,
        'predicate': pkey,
        'raw_predicate': raw_predicate if raw_predicate != pkey else '',
        'relationship_id': rel_id,
        'confidence': raw.get('confidence', 0.5),
        'subject_id': raw.get('subject_id', ''),
        'object_id': raw.get('object_id', ''),
        'datasource': raw.get('datasource', ''),
        'occurrence_time': raw.get('occurrence_time'),
        'description': raw.get('description'),
        'attributes': attrs_str,
    }
    return row, hit


class RelationshipRepository:
    """Neo4j 类型化关系边 CRUD（边类型来自本体受控词表）"""

    # ── 查询 ──

    def get_edges(self, limit: int = 5000) -> List[Dict[str, Any]]:
        """获取图谱边（泛型匹配，覆盖全部 LinkType）"""
        try:
            safe_limit = min(max(1, limit), 50000)
            logger.info(f"[get_edges] 开始获取图谱边, limit={safe_limit}")

            if safe_limit == 5000:
                cached = graph_performance.get_cached_graph_data("edges:all")
                if cached:
                    logger.info(f"[get_edges] 从缓存获取边: {len(cached)} 条")
                    return cached

            query = """
            MATCH (s)-[r]->(t)
            RETURN s.name as source, t.name as target, r.predicate as type,
                   r.confidence as confidence, r.subject_id as subject_id,
                   r.object_id as object_id, r.occurrence_time as occurrence_time,
                   r.description as description, r.relationship_id as relationship_id
            LIMIT $limit
            """
            result = neo4j_conn.execute_query(query, {"limit": safe_limit})

            edges = []
            for record in result:
                edges.append({
                    'source': record['source'],
                    'target': record['target'],
                    'type': record.get('type') or '其他',
                    'confidence': record.get('confidence', 0.5),
                    'subject_id': record.get('subject_id'),
                    'object_id': record.get('object_id'),
                    'occurrence_time': record.get('occurrence_time'),
                    'description': record.get('description'),
                    'relationship_id': record.get('relationship_id')
                })

            if safe_limit == 5000:
                graph_performance.cache_graph_data("edges:all", edges)

            logger.info(f"[get_edges] 获取边成功: {len(edges)} 条")
            return edges
        except Exception as e:
            logger.error(f"[get_edges] 获取边失败: {str(e)}")
            raise

    def get_edge_count(self) -> int:
        """获取图谱边的总数"""
        try:
            query = "MATCH (s)-[r]->(t) RETURN count(r) as total"
            result = neo4j_conn.execute_query(query)
            return result[0]['total'] if result else 0
        except Exception as e:
            logger.error(f"[get_edge_count] 获取边总数失败: {str(e)}")
            return 0

    def list_relationships(self, limit: int = 100) -> List[Dict[str, Any]]:
        """列出所有关系"""
        try:
            query = """
            MATCH (s:Entity)-[r]->(t:Entity)
            RETURN s.name as subject, s.id as subject_id,
                   t.name as object, t.id as object_id,
                   r.predicate as predicate, r.relationship_id as relationship_id,
                   r.description as description, r.occurrence_time as occurrence_time,
                   r.confidence as confidence
            LIMIT $limit
            """
            result = neo4j_conn.execute_query(query, {"limit": limit})
            rels = []
            for r in result:
                rels.append({
                    'id': r['relationship_id'],
                    'subject': r['subject'],
                    'subject_id': r['subject_id'],
                    'object': r['object'],
                    'object_id': r['object_id'],
                    'predicate': r.get('predicate') or '其他',
                    'relationship_id': r['relationship_id'],
                    'description': r.get('description', ''),
                    'occurrence_time': r.get('occurrence_time', ''),
                    'confidence': r.get('confidence', 0.5),
                })
            return rels
        except Exception as e:
            logger.error(f"列出关系失败: {e}")
            return []

    def get_entity_relationships(self, entity_id: str) -> List[Dict[str, Any]]:
        """获取实体关联的所有关系"""
        try:
            query = """
            MATCH (s:Entity)-[r]->(t:Entity)
            WHERE s.id = $id OR t.id = $id
            RETURN s.name as subject, s.id as subject_id,
                   t.name as object, t.id as object_id,
                   r.predicate as predicate, r.relationship_id as relationship_id,
                   r.description as description, r.occurrence_time as occurrence_time,
                   r.confidence as confidence
            """
            result = neo4j_conn.execute_query(query, {"id": entity_id})
            rels = []
            for r in result:
                rels.append({
                    'id': r['relationship_id'],
                    'subject': r['subject'],
                    'subject_id': r['subject_id'],
                    'object': r['object'],
                    'object_id': r['object_id'],
                    'predicate': r.get('predicate') or '其他',
                    'relationship_id': r['relationship_id'],
                    'description': r.get('description', ''),
                    'occurrence_time': r.get('occurrence_time', ''),
                    'confidence': r.get('confidence', 0.5),
                })
            return rels
        except Exception as e:
            logger.error(f"获取实体关系失败: {e}")
            return []

    # ── 写入 ──

    def add_relationship(self, relationship: Dict[str, Any]) -> Dict[str, Any]:
        """添加单条关系（谓词归一化 + 类型化 MERGE）"""
        try:
            row, hit = _normalize_rel(relationship)
            subject = row['subject']
            object_name = row['target']
            predicate = row['predicate']
            rel_type = cypher_rel_type(predicate)

            if not hit:
                logger.warning(
                    f"[add_relationship] 谓词 '{row['raw_predicate']}' 不在受控词表，"
                    f"归一为 '{predicate}': {subject} -> {object_name}"
                )
            logger.info(f"[add_relationship] 开始添加关系: {subject} -{predicate}-> {object_name}, ID: {row['relationship_id']}")

            query = f"""
            MATCH (s:Entity {{name: $source}})
            MATCH (t:Entity {{name: $target}})
            MERGE (s)-[r:{rel_type} {{relationship_id: $relationship_id}}]->(t)
            ON CREATE SET r.created_at = datetime(), r.datasource = $datasource
            SET r.predicate = $predicate, r.raw_predicate = $raw_predicate,
                r.confidence = $confidence,
                r.subject_id = $subject_id, r.object_id = $object_id,
                r.occurrence_time = $occurrence_time, r.description = $description,
                r.attributes = $attributes
            SET r.datasources = {union_sources('r', '$datasource')}
            RETURN type(r) as type
            """
            neo4j_conn.execute_query(query, {
                'source': subject,
                'target': object_name,
                'predicate': predicate,
                'raw_predicate': row['raw_predicate'],
                'relationship_id': row['relationship_id'],
                'confidence': row['confidence'],
                'subject_id': row['subject_id'],
                'object_id': row['object_id'],
                'datasource': row['datasource'],
                'occurrence_time': row['occurrence_time'],
                'description': row['description'],
                'attributes': row['attributes'],
            })

            graph_performance.clear_cache("graph:edges:*")

            logger.info(f"[add_relationship] 添加关系成功: {subject} -{predicate}-> {object_name}")
            return {"status": "success", "predicate": predicate,
                    "relationship_id": row['relationship_id']}
        except Exception as e:
            logger.error(f"[add_relationship] 添加关系失败: {str(e)}")
            raise

    def add_relationships(self, relationships: List[Dict[str, Any]],
                          use_create: bool = False, defer_cache: bool = False) -> Dict[str, Any]:
        """批量添加关系：按受控谓词分组，每组一条 UNWIND + CREATE/MERGE 类型化查询

        Cypher 关系类型名不能参数化，按 LinkType 分组后逐组写入；
        受控词表规模小，组数可控。
        """
        try:
            logger.info(f"[add_relationships] 开始批量添加关系，数量: {len(relationships)}, use_create={use_create}")

            if not relationships:
                logger.info("[add_relationships] 没有需要添加的关系")
                return {"status": "success", "count": 0, "fallback_count": 0}

            groups: Dict[str, List[Dict[str, Any]]] = {}
            fallback_count = 0
            for raw in relationships:
                row, hit = _normalize_rel(raw)
                if not hit:
                    fallback_count += 1
                    logger.debug(
                        f"[add_relationships] 谓词兜底归一: '{row['raw_predicate']}' -> '{row['predicate']}'"
                    )
                groups.setdefault(row['predicate'], []).append(row)

            if fallback_count:
                logger.warning(f"[add_relationships] {fallback_count} 条关系谓词未命中受控词表，归入兜底类型")

            write_keys = {'subject_id': None, 'object_id': None, 'relationship_id': None,
                          'predicate': None, 'raw_predicate': None, 'confidence': None,
                          'datasource': None,
                          'occurrence_time': None, 'description': None, 'attributes': None}

            written = 0
            union_rel_sources = union_sources('rel', 'r.datasource')
            for predicate, rows in groups.items():
                rel_type = cypher_rel_type(predicate)
                payload = [{k: r[k] for k in write_keys} for r in rows]
                if use_create:
                    query = f"""
                    UNWIND $relationships AS r
                    MATCH (s:Entity {{id: r.subject_id}})
                    MATCH (t:Entity {{id: r.object_id}})
                    CREATE (s)-[rel:{rel_type} {{relationship_id: r.relationship_id}}]->(t)
                    SET rel.predicate = r.predicate, rel.raw_predicate = r.raw_predicate,
                        rel.confidence = r.confidence, rel.datasource = r.datasource,
                        rel.occurrence_time = r.occurrence_time, rel.description = r.description,
                        rel.attributes = r.attributes,
                        rel.created_at = datetime()
                    SET rel.datasources = {union_rel_sources}
                    """
                else:
                    query = f"""
                    UNWIND $relationships AS r
                    MATCH (s:Entity {{id: r.subject_id}})
                    MATCH (t:Entity {{id: r.object_id}})
                    MERGE (s)-[rel:{rel_type} {{relationship_id: r.relationship_id}}]->(t)
                    ON CREATE SET rel.created_at = datetime(), rel.datasource = r.datasource
                    SET rel.predicate = r.predicate, rel.raw_predicate = r.raw_predicate,
                        rel.confidence = r.confidence,
                        rel.occurrence_time = r.occurrence_time, rel.description = r.description,
                        rel.attributes = r.attributes
                    SET rel.datasources = {union_rel_sources}
                    """
                neo4j_conn.execute_query(query, {"relationships": payload})
                written += len(rows)

            if not defer_cache:
                graph_performance.clear_cache("graph:edges:*")

            logger.info(f"[add_relationships] 批量添加关系完成，成功: {written}，兜底: {fallback_count}")
            return {"status": "success", "count": written, "fallback_count": fallback_count}
        except Exception as e:
            logger.error(f"[add_relationships] 批量添加关系失败: {str(e)}")
            raise

    # ── 写入 · 占位符容错 ──

    def upsert_relationships(self, rows: List[Dict[str, Any]], source_tag: str = "",
                             defer_cache: bool = False, default_confidence: float = 1.0) -> int:
        """语义行 → 受控写入（唯一归一化应用点）：两端尚未落地也能写入

        与 add_relationships 的差异：端点 MERGE（不存在则建 _placeholder 占位实体，
        等后续真实数据 MERGE 回填同一 id），并支持关系级 source_tag（r.source）。
        供数据库 junction 批导入、CDC junction/FK 写入共用，谓词归一化只在这里发生。

        Args:
            rows: 语义行列表
                {subject, object, predicate(原始谓词), datasource,
                 description, attributes(dict/str, 可选), confidence(可选)}
            source_tag: 关系来源标识，如 'junction_import' / 'cdc_fk'（空则不设 r.source）
            defer_cache: 批量导入静默期
            default_confidence: 行未显式给 confidence 时的默认值
        """
        from models.ids import compute_entity_id

        if not rows:
            return 0

        try:
            groups: Dict[str, List[Dict[str, Any]]] = {}
            for raw in rows:
                subject = str(raw.get("subject", "")).strip()
                target = str(raw.get("object", "")).strip()
                if not subject or not target:
                    continue
                raw_predicate = raw.get("predicate", "")
                rel_id, predicate, hit = canonical_rel_id(subject, raw_predicate, target)
                if not hit:
                    logger.debug(
                        f"[upsert_relationships] 谓词兜底归一: '{raw_predicate}' -> '{predicate}'"
                    )
                attrs = raw.get("attributes", {})
                attrs_str = attrs if isinstance(attrs, str) else (
                    db_json_dumps(attrs) if attrs else "{}"
                )
                groups.setdefault(predicate, []).append({
                    "src_id": compute_entity_id(subject), "src_name": subject,
                    "tgt_id": compute_entity_id(target), "tgt_name": target,
                    "rel_id": rel_id,
                    "predicate": predicate,
                    "raw_predicate": raw_predicate if raw_predicate != predicate else "",
                    "description": raw.get("description", ""),
                    "attributes": attrs_str,
                    "datasource": raw.get("datasource", ""),
                    "confidence": raw.get("confidence", default_confidence),
                })

            written = 0
            for predicate, batch in groups.items():
                rel_type = cypher_rel_type(predicate)
                source_set = f", r.source = '{source_tag}'" if source_tag else ""
                neo4j_conn.execute_query(
                    f"UNWIND $batch AS item "
                    f"MERGE (s:Entity {{id: item.src_id}}) "
                    f"ON CREATE SET s.name = item.src_name, s._placeholder = true "
                    f"MERGE (t:Entity {{id: item.tgt_id}}) "
                    f"ON CREATE SET t.name = item.tgt_name, t._placeholder = true "
                    f"MERGE (s)-[r:{rel_type} {{relationship_id: item.rel_id}}]->(t) "
                    f"ON CREATE SET r.datasource = item.datasource "
                    f"SET r.predicate = item.predicate, r.raw_predicate = item.raw_predicate"
                    f"{source_set}, "
                    f"r.description = item.description, r.attributes = item.attributes, "
                    f"r.confidence = item.confidence "
                    f"SET r.datasources = {union_sources('r', 'item.datasource')}",
                    {"batch": batch}
                )
                written += len(batch)

            if not defer_cache:
                graph_performance.clear_cache("graph:edges:*")
            logger.info(f"[upsert_relationships] 占位符容错批写完成: {written} 条")
            return written
        except Exception as e:
            logger.error(f"[upsert_relationships] 批写失败: {e}")
            raise

    # ── 更新 ──

    def update_relationship(self, relationship_id: str, props: Dict[str, Any]) -> bool:
        """更新关系属性（confidence/description 等）

        predicate 不可经本接口变更：边类型是创建时确定的关系标识，
        改谓词请走「删除 + 重新添加」。
        """
        try:
            if 'predicate' in props:
                logger.warning("[update_relationship] predicate 不可更新，请删除后按新谓词重建")
                return False
            query = """
            MATCH ()-[r {relationship_id: $id}]-()
            SET r += $props
            RETURN r.relationship_id as id
            """
            result = neo4j_conn.execute_query(query, {"id": relationship_id, "props": props})
            graph_performance.clear_cache("graph:edges:*")
            return len(result) > 0
        except Exception as e:
            logger.error(f"更新关系失败: {e}")
            return False

    # ── 删除 ──

    def recycle_datasource(self, datasource_prefix: str,
                           defer_cache: bool = False) -> int:
        """摘除某来源对全部边的佐证，佐证清空则删除边

        同一条关系可被多个来源佐证（relationship_id 由 s_p_o 决定，与来源无关），
        因此只删除本来源不再佐证的边，其他来源仍在的边保留。
        """
        try:
            query = f"""
            MATCH ()-[r]->()
            WHERE {match_prefix('r', '$prefix')}
            SET r.datasources = {strip_prefix('r')}
            SET r.datasource = coalesce(head(r.datasources), '')
            WITH r WHERE size(coalesce(r.datasources, [])) = 0
            DELETE r
            RETURN count(r) AS deleted
            """
            result = neo4j_conn.execute_query(query, {"prefix": datasource_prefix})
            deleted = result[0].get('deleted', 0) if result else 0

            if not defer_cache:
                graph_performance.clear_cache("graph:edges:*")
            logger.info(f"[recycle_datasource] 回收数据源 '{datasource_prefix}' 的边，删除 {deleted} 条")
            return deleted
        except Exception as e:
            logger.error(f"[recycle_datasource] 边回收失败: {e}")
            raise

    def delete_relationship(self, relationship_id: str) -> bool:
        """删除单条关系（按 relationship_id 泛型匹配，不限边类型）"""
        try:
            query = """
            MATCH ()-[r {relationship_id: $id}]-()
            DELETE r
            RETURN count(r) as deleted
            """
            result = neo4j_conn.execute_query(query, {"id": relationship_id})
            deleted = result[0]['deleted'] if result else 0
            graph_performance.clear_cache("graph:edges:*")
            logger.info(f"[delete_relationship] 删除关系: {relationship_id}, 命中 {deleted} 条")
            return deleted > 0
        except Exception as e:
            logger.error(f"删除关系失败: {e}")
            return False

    # ── 治理统计（只读聚合，供 ontology/governance 使用）──

    def predicate_usage(self) -> Dict[str, int]:
        """各受控谓词的边数；兜底谓词的占比由此算出"""
        result = neo4j_conn.execute_query(
            "MATCH ()-[r]->() RETURN r.predicate AS predicate, count(r) AS count")
        return {(r['predicate'] or ''): r['count'] for r in result}

    def raw_predicate_variants(self, limit: int = 200) -> List[Dict[str, Any]]:
        """原始谓词 → 归一后谓词的分布，用于发现词表该补哪些别名"""
        result = neo4j_conn.execute_query(
            """
            MATCH ()-[r]->() WHERE r.raw_predicate IS NOT NULL AND r.raw_predicate <> ''
            RETURN r.predicate AS predicate, r.raw_predicate AS raw_predicate,
                   count(r) AS count
            ORDER BY count DESC LIMIT $limit
            """, {"limit": limit})
        return [{'predicate': r['predicate'], 'raw_predicate': r['raw_predicate'],
                 'count': r['count']} for r in result]

    def endpoint_type_pairs(self) -> List[Dict[str, Any]]:
        """(谓词, 主语类型, 宾语类型) 三元组计数，供定义域/值域校验"""
        result = neo4j_conn.execute_query(
            """
            MATCH (s:Entity)-[r]->(t:Entity)
            RETURN r.predicate AS predicate, s.type AS subject_type,
                   t.type AS object_type, count(r) AS count
            """)
        return [{'predicate': r['predicate'], 'subject_type': r['subject_type'],
                 'object_type': r['object_type'], 'count': r['count']} for r in result]

    def count_missing_provenance(self) -> int:
        """无来源佐证的边数 —— 来源不可追溯的存量数据"""
        result = neo4j_conn.execute_query(
            "MATCH ()-[r]->() WHERE size(coalesce(r.datasources, [])) = 0 RETURN count(r) AS count")
        return result[0]['count'] if result else 0


# 模块级单例 —— 调用方直接 import 使用，不再经 GraphManager 转发
rel_repo = RelationshipRepository()
