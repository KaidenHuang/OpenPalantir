from typing import Dict, List, Optional

from system.logger import logger
from decision_engine.contracts import AnalyzedQuery, RawEvidence
from decision_engine.retrievers.base_retriever import BaseRetriever

from knowledge_graph.graph_manager import graph_manager


class GraphRetriever(BaseRetriever):
    source_type = "graph"

    def retrieve(self, query: AnalyzedQuery, context: Dict) -> List[RawEvidence]:
        results: List[RawEvidence] = []

        doc_filters = context.get("doc_source_filters", None)
        entity_types = context.get("entity_types", None)
        if doc_filters:
            doc_results = self._retrieve_document_entities(query, context, doc_filters, entity_types)
            results.extend(doc_results)
        elif entity_types:
            doc_results = self._retrieve_document_entities(query, context, None, entity_types)
            results.extend(doc_results)

        db_table_filters = context.get("db_table_filters", None)
        if db_table_filters:
            db_results = self._retrieve_database_entities(context, db_table_filters)
            results.extend(db_results)

        if not doc_filters and not entity_types and not db_table_filters:
            results = self._legacy_retrieve(query, context)

        logger.info(f"[retriever][graph] 图谱检索共提取 {len(results)} 条结果")
        return results

    def _retrieve_document_entities(self, query: AnalyzedQuery, context: Dict,
                                     source_filters: Optional[List[str]],
                                     entity_types: Optional[List[str]]) -> List[RawEvidence]:
        results: List[RawEvidence] = []

        if source_filters:
            # ── 按 datasource 查实体（有 URI 前缀时精确查找，跳过全文本搜索）──
            seen_entities = set()
            seen_rels: set = set()
            for ds_uri in source_filters:
                entities = graph_manager.search_entities_by_datasource(ds_uri, limit=100)
                if entity_types:
                    entities = [e for e in entities if e.get("type") in entity_types]

                ds_entity_names = set()
                for entity in entities:
                    name = entity.get("name", "")
                    if not name or name in seen_entities:
                        continue
                    seen_entities.add(name)
                    ds_entity_names.add(name)
                    results.append(self._make_entity_evidence(entity, 0.9, "document"))

                rels_before = len(seen_rels)
                batch_names = list(ds_entity_names)[:50]
                if batch_names:
                    edges = self._query_edges_batch(batch_names, seen_rels, [ds_uri])
                    results.extend(edges)
                rels_added = len(seen_rels) - rels_before

                logger.info(
                    f"[retriever][graph][doc] 文档「{ds_uri}」：提取 {len(entities)} 个实体"
                    + (f"，关联 {rels_added} 条关系" if rels_added else "，无关联关系")
                )

            return results

        # ── 无 datasource URI：回退到 fulltext 搜索（保留 entity_types）──
        question = context.get("question", "")
        entities = graph_manager.search_entities(
            query=question, limit=15,
            source_filters=None,
            entity_types=entity_types,
        )

        seen_entities = set()
        for entity in entities:
            name = entity.get("name", "")
            if not name or name in seen_entities:
                continue
            seen_entities.add(name)
            entity_type = entity.get("type", "")
            description = entity.get("description", "")
            similarity = entity.get("similarity", 0)

            score = min(1.0, similarity + 0.5)
            if query.entities and any(e.lower() == name.lower() for e in query.entities):
                score = 1.0

            results.append(self._make_entity_evidence(entity, score, "document"))

        seen_rels: set = set()
        batch_names = list(seen_entities)[:50]
        rels_count = 0
        if batch_names:
            edges = self._query_edges_batch(batch_names, seen_rels)
            results.extend(edges)
            rels_count = len(edges)

        logger.info(f"[retriever][graph][doc] 文本搜索到 {len(seen_entities)} 个实体，关联 {rels_count} 条关系")
        return results

    def _retrieve_database_entities(self, context: Dict,
                                     db_table_filters: List[Dict]) -> List[RawEvidence]:
        results: List[RawEvidence] = []

        dbs_names = [f.get("table_name", "") or f.get("datasource_uri", "").split("/")[-1] for f in db_table_filters]
        logger.info(f"[retriever][graph][db] 准备查询 {len(db_table_filters)} 张数据库表：{', '.join(dbs_names)}")
        for table_filter in db_table_filters:
            datasource_uri = table_filter.get("datasource_uri", "")
            table_name = table_filter.get("table_name", "")
            if not datasource_uri:
                continue

            entities = graph_manager.search_entities_by_datasource(datasource_uri, limit=100)

            seen_in_table = set()
            for entity in entities:
                name = entity.get("name", "")
                if not name:
                    continue
                entity_type = entity.get("type", "")
                description = entity.get("description", "")

                results.append(self._make_entity_evidence(entity, 0.8, "database", {"table": table_name}))
                seen_in_table.add(name)

            rels_before = len([r for r in results if r.source_type == 'graph_relation'])
            seen_rels: set = set()
            batch_names = list(seen_in_table)[:50]
            if batch_names:
                edges = self._query_edges_batch(batch_names, seen_rels, None)
                results.extend(edges)
            rels_added = len([r for r in results if r.source_type == 'graph_relation']) - rels_before

            logger.info(
                f"[retriever][graph][db] 数据库表「{datasource_uri}」：提取 {len(entities)} 行数据"
                + (f"，关联 {rels_added} 条关系" if rels_added else "，无关联关系")
            )

        return results

    def _legacy_retrieve(self, query: AnalyzedQuery, context: Dict) -> List[RawEvidence]:
        results: List[RawEvidence] = []
        datasource_prefixes = context.get("source_filters", None)
        question = context.get("question", "")

        entities = graph_manager.search_entities(
            query=question, limit=15, source_filters=datasource_prefixes
        )
        logger.info(f"[retriever][graph] 全局搜索实体：找到 {len(entities)} 个")

        seen_entities = set()
        for entity in entities:
            name = entity.get("name", "")
            score = min(1.0, entity.get("similarity", 0) + 0.5)
            if query.entities and any(e.lower() == name.lower() for e in query.entities):
                score = 1.0
            results.append(self._make_entity_evidence(entity, score))
            seen_entities.add(name)

        entity_hints = context.get("entity_hints", [])
        entity_names = query.entities or list(seen_entities)
        if not entity_names:
            entity_names = entity_hints or self._extract_names(question)

        seen_rels: set = set()
        for name in entity_names[:5]:
            edges = self._query_edges(name, seen_rels, datasource_prefixes)
            if edges:
                results.extend(edges)
                continue
            edges = self._query_edges_by_prefix(name, seen_rels, datasource_prefixes)
            if edges:
                results.extend(edges)
                continue
            table_name = name.split(":")[0] if ":" in name else ""
            if table_name and table_name != name:
                edges = self._query_edges(table_name, seen_rels, datasource_prefixes)
                if not edges:
                    edges = self._query_edges_by_prefix(table_name, seen_rels, datasource_prefixes)
                results.extend(edges)

        return results

    def _query_edges_by_prefix(self, prefix: str, seen: set, datasource_prefixes: Optional[List[str]] = None) -> List[RawEvidence]:
        cypher = "MATCH (n:Entity)-[r]-(m)"
        params = {"prefix": prefix}

        conditions = ["n.name STARTS WITH $prefix"]
        if datasource_prefixes:
            conditions.append("ANY(p IN $prefixes WHERE n.datasource STARTS WITH p OR m.datasource STARTS WITH p)")
            params["prefixes"] = datasource_prefixes

        cypher += " WHERE " + " AND ".join(conditions)
        cypher += """
        RETURN n.name as source, m.name as target, r.predicate as type,
               r.confidence as confidence, r.relationship_id as relationship_id,
               r.description as description
        LIMIT 30
        """
        try:
            edges = graph_manager.query_graph(cypher, params=params)
            results = []
            for edge in edges:
                ev = self._make_relation_evidence(edge, seen, prefix)
                if ev:
                    results.append(ev)
            return results
        except Exception as e:
            logger.warning(f"[retriever][graph] 按名称前缀查关系失败，前缀「{prefix}」，原因：{e}")
            return []

    def _query_edges(self, name: str, seen: set, datasource_prefixes: Optional[List[str]] = None) -> List[RawEvidence]:
        cypher = "MATCH (n {name: $name})-[r]-(m)"
        params = {"name": name}

        if datasource_prefixes:
            cypher += " WHERE ANY(prefix IN $prefixes WHERE n.datasource STARTS WITH prefix OR m.datasource STARTS WITH prefix)"
            params["prefixes"] = datasource_prefixes

        cypher += """
        RETURN n.name as source, m.name as target, r.predicate as type,
               r.confidence as confidence, r.relationship_id as relationship_id,
               r.description as description
        LIMIT 30
        """
        try:
            edges = graph_manager.query_graph(cypher, params=params)
            results = []
            for edge in edges:
                ev = self._make_relation_evidence(edge, seen, name)
                if ev:
                    results.append(ev)
            return results
        except Exception as e:
            logger.warning(f"[retriever][graph] 按名称查关系失败，名称「{name}」，原因：{e}")
            return []

    def _query_edges_batch(self, names: List[str], seen: set,
                           datasource_prefixes: Optional[List[str]] = None) -> List[RawEvidence]:
        if not names:
            return []

        cypher = "MATCH (n:Entity)-[r]-(m)"
        params: Dict = {"names": names}

        conditions = ["n.name IN $names"]
        if datasource_prefixes:
            conditions.append(
                "ANY(prefix IN $prefixes WHERE n.datasource STARTS WITH prefix OR m.datasource STARTS WITH prefix)"
            )
            params["prefixes"] = datasource_prefixes

        cypher += " WHERE " + " AND ".join(conditions)
        cypher += """
        RETURN n.name as source, m.name as target, r.predicate as type,
               r.confidence as confidence, r.relationship_id as relationship_id,
               r.description as description
        LIMIT 200
        """
        try:
            edges = graph_manager.query_graph(cypher, params=params)
            results = []
            for edge in edges:
                ev = self._make_relation_evidence(edge, seen, "batch")
                if ev:
                    results.append(ev)
            return results
        except Exception as e:
            sample = names[:3]
            logger.warning(f"[retriever][graph] 批量查关系失败，涉及 {len(names)} 个实体（如「{sample[0]}」），原因：{e}")
            return []

    @staticmethod
    def _make_entity_evidence(entity: dict, score: float, source_kind: str = "",
                               extra_metadata: dict = None) -> RawEvidence:
        name = entity.get("name", "")
        metadata = {"name": name, "type": entity.get("type", "")}
        if source_kind:
            metadata["source_kind"] = source_kind
        if extra_metadata:
            metadata.update(extra_metadata)
        return RawEvidence(
            source_type="entity",
            source_id=entity.get("entity_id", name),
            content={"name": name, "type": entity.get("type", ""),
                     "description": entity.get("description", ""),
                     "confidence": entity.get("confidence", 0),
                     "datasource": entity.get("datasource", "")},
            relevance_score=score,
            metadata=metadata,
        )

    @staticmethod
    def _make_relation_evidence(edge: dict, seen: set, source_id_prefix: str = "edge") -> Optional[RawEvidence]:
        rel_id = edge.get("relationship_id", "")
        if rel_id and rel_id in seen:
            return None
        if rel_id:
            seen.add(rel_id)
        return RawEvidence(
            source_type="graph_relation",
            source_id=rel_id or f"{source_id_prefix}-{len(seen)}",
            content={"source": edge.get("source", ""), "target": edge.get("target", ""),
                     "predicate": edge.get("type", ""), "description": edge.get("description", "")},
            relevance_score=0.7,
            metadata={"source": edge.get("source", ""), "target": edge.get("target", "")},
        )

    @staticmethod
    def _extract_names(question: str) -> List[str]:
        import re
        names = []
        for token in re.split(r'[，。？！.,?!、；:\s]+', question):
            clean = token.strip()
            if clean and len(clean) > 1:
                names.append(clean)
        return names[:5]
