"""
关系仓库 — 封装 Neo4j RELATED_TO 边的全部 CRUD 操作

从 GraphManager 中拆出，职责单一：关系增删改查。
GraphManager 作为薄门面委托调用本模块。
"""
from typing import List, Dict, Any
from config.neo4j_config import neo4j_conn
from system.logger import logger


class RelationshipRepository:
    """Neo4j RELATED_TO 边 CRUD"""

    # ── 查询 ──

    def get_edges(self, limit: int = 5000, performance=None) -> List[Dict[str, Any]]:
        """获取图谱边"""
        try:
            safe_limit = min(max(1, limit), 50000)
            logger.info(f"[get_edges] 开始获取图谱边, limit={safe_limit}")

            if safe_limit == 5000 and performance:
                cached = performance.get_cached_graph_data("edges:all")
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
                    'type': record.get('type', 'REL'),
                    'confidence': record.get('confidence', 0.5),
                    'subject_id': record.get('subject_id'),
                    'object_id': record.get('object_id'),
                    'occurrence_time': record.get('occurrence_time'),
                    'description': record.get('description'),
                    'relationship_id': record.get('relationship_id')
                })

            if safe_limit == 5000 and performance:
                performance.cache_graph_data("edges:all", edges)

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
            MATCH (s:Entity)-[r:RELATED_TO]->(t:Entity)
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
                    'predicate': r.get('predicate', 'RELATES_TO'),
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
            MATCH (s:Entity)-[r:RELATED_TO]->(t:Entity)
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
                    'predicate': r.get('predicate', 'RELATES_TO'),
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

    def add_relationship(self, relationship: Dict[str, Any],
                         performance=None) -> Dict[str, Any]:
        """添加单条关系"""
        try:
            subject = relationship.get("subject")
            object_name = relationship.get("object")
            predicate = relationship.get("predicate", "RELATES_TO")
            relationship_id = relationship.get("relationship_id")
            logger.info(f"[add_relationship] 开始添加关系: {subject} -{predicate}-> {object_name}, ID: {relationship_id}")

            params = {
                'source': subject,
                'target': object_name,
                'predicate': predicate,
                'relationship_id': relationship_id,
                'confidence': relationship.get('confidence', 0.5),
                'subject_id': relationship.get('subject_id', ''),
                'object_id': relationship.get('object_id', ''),
                'occurrence_time': relationship.get('occurrence_time'),
                'description': relationship.get('description')
            }

            query = """
            MATCH (s:Entity {name: $source})
            MATCH (t:Entity {name: $target})
            MERGE (s)-[r:RELATED_TO {relationship_id: $relationship_id}]->(t)
            SET r.predicate = $predicate, r.confidence = $confidence,
                r.subject_id = $subject_id, r.object_id = $object_id,
                r.occurrence_time = $occurrence_time, r.description = $description
            RETURN type(r) as type
            """
            neo4j_conn.execute_query(query, params)

            if performance:
                performance.clear_cache("graph:edges:*")

            logger.info(f"[add_relationship] 添加关系成功: {subject} -{predicate}-> {object_name}")
            return {"status": "success", "predicate": predicate}
        except Exception as e:
            logger.error(f"[add_relationship] 添加关系失败: {str(e)}")
            raise

    def add_relationships(self, relationships: List[Dict[str, Any]],
                          use_create: bool = False, defer_cache: bool = False,
                          performance=None) -> Dict[str, Any]:
        """批量添加关系（UNWIND + CREATE/MERGE）"""
        try:
            logger.info(f"[add_relationships] 开始批量添加关系，数量: {len(relationships)}, use_create={use_create}")

            if not relationships:
                logger.info("[add_relationships] 没有需要添加的关系")
                return {"status": "success", "count": 0}

            rel_list = []
            for rel in relationships:
                rel_list.append({
                    'subject_id': rel.get('subject_id', ''),
                    'object_id': rel.get('object_id', ''),
                    'predicate': rel.get("predicate", "RELATES_TO"),
                    'relationship_id': rel.get("relationship_id", ""),
                    'confidence': rel.get('confidence', 0.5),
                    'occurrence_time': rel.get('occurrence_time'),
                    'description': rel.get('description')
                })

            if use_create:
                query = """
                UNWIND $relationships AS r
                MATCH (s:Entity {id: r.subject_id})
                MATCH (t:Entity {id: r.object_id})
                CREATE (s)-[rel:RELATED_TO {relationship_id: r.relationship_id}]->(t)
                SET rel.predicate = r.predicate, rel.confidence = r.confidence,
                    rel.occurrence_time = r.occurrence_time, rel.description = r.description
                """
            else:
                query = """
                UNWIND $relationships AS r
                MATCH (s:Entity {id: r.subject_id})
                MATCH (t:Entity {id: r.object_id})
                MERGE (s)-[rel:RELATED_TO {relationship_id: r.relationship_id}]->(t)
                SET rel.predicate = r.predicate, rel.confidence = r.confidence,
                    rel.occurrence_time = r.occurrence_time, rel.description = r.description
                """
            neo4j_conn.execute_query(query, {"relationships": rel_list})

            if performance and not defer_cache:
                performance.clear_cache("graph:edges:*")

            logger.info(f"[add_relationships] 批量添加关系完成，成功: {len(relationships)}")
            return {"status": "success", "count": len(relationships), "failed_count": 0}
        except Exception as e:
            logger.error(f"[add_relationships] 批量添加关系失败: {str(e)}")
            raise

    # ── 更新 ──

    def update_relationship(self, relationship_id: str, props: Dict[str, Any],
                            performance=None) -> bool:
        """更新关系属性（predicate/confidence/description 等）"""
        try:
            query = """
            MATCH ()-[r:RELATED_TO {relationship_id: $id}]-()
            SET r += $props
            RETURN r.relationship_id as id
            """
            result = neo4j_conn.execute_query(query, {"id": relationship_id, "props": props})
            if performance:
                performance.clear_cache("graph:edges:*")
            return len(result) > 0
        except Exception as e:
            logger.error(f"更新关系失败: {e}")
            return False

    # ── 删除 ──

    def delete_relationship(self, relationship_id: str,
                            performance=None) -> bool:
        """删除单条关系"""
        try:
            query = """
            MATCH ()-[r:RELATED_TO {relationship_id: $id}]-()
            DELETE r
            """
            result = neo4j_conn.execute_query(query, {"id": relationship_id})
            if performance:
                performance.clear_cache("graph:edges:*")
            logger.info(f"[delete_relationship] 删除关系: {relationship_id}")
            return True
        except Exception as e:
            logger.error(f"删除关系失败: {e}")
            return False
