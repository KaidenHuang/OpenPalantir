from typing import Dict, List

from system.logger import logger
from decision_engine.contracts import AnalyzedQuery, RawEvidence
from decision_engine.retrievers.document_summary_retriever import DocumentSummaryRetriever
from decision_engine.retrievers.database_summary_retriever import DatabaseSummaryRetriever
from decision_engine.retrievers.graph_retriever import GraphRetriever


class RetrievalOrchestrator:
    def __init__(self):
        self.retrievers = {
            "document_summary": DocumentSummaryRetriever(),
            "database_summary": DatabaseSummaryRetriever(),
            "graph": GraphRetriever(),
        }

    def retrieve(self, query: AnalyzedQuery, context: Dict) -> List[RawEvidence]:
        all_evidence: List[RawEvidence] = []

        doc_evidence: List[RawEvidence] = []
        db_evidence: List[RawEvidence] = []
        try:
            doc_evidence = self.retrievers["document_summary"].retrieve(query, context)
        except Exception as e:
            logger.warning(f"[orchestrator] document_summary retriever failed: {e}")
        try:
            db_evidence = self.retrievers["database_summary"].retrieve(query, context)
        except Exception as e:
            logger.warning(f"[orchestrator] database_summary retriever failed: {e}")

        doc_source_filters = []
        doc_datasources_seen = set()
        doc_datasources = set()
        for ev in doc_evidence:
            ds = ev.metadata.get("datasource", "")
            if ds:
                doc_datasources.add(ds)
                if ds not in doc_datasources_seen:
                    doc_datasources_seen.add(ds)
                    doc_source_filters.append(ds)

        db_table_filters = []
        db_datasources_seen = set()
        db_datasources = set()
        for ev in db_evidence:
            ds = ev.metadata.get("datasource", "")
            if ds:
                db_datasources.add(ds)
                table = ev.metadata.get("table", "")
                if ds not in db_datasources_seen:
                    db_datasources_seen.add(ds)
                    db_table_filters.append({
                        "datasource_uri": ds,
                        "table_name": table,
                    })

        logger.info(
            f"[orchestrator] 文档检索：从 {len(doc_datasources)} 篇文档中匹配到 {len(doc_evidence)} 条相关内容"
            + (f" — {', '.join(sorted(doc_datasources))}" if doc_datasources else "")
        )
        if db_datasources:
            logger.info(
                f"[orchestrator] 数据库检索：从 {len(db_datasources)} 个表中匹配到 {len(db_evidence)} 条相关内容"
                f" — {', '.join(sorted(db_datasources))}"
            )

        all_evidence.extend(doc_evidence)
        all_evidence.extend(db_evidence)

        entity_types = list(set(query.entity_types.values())) if query.entity_types else []

        entity_type_names = entity_types if entity_types else "无"
        logger.info(f"[orchestrator] 图谱检索准备：文档数据源 {len(doc_source_filters)} 个，数据库表 {len(db_table_filters)} 张，实体类型过滤 {entity_type_names}")

        graph_evidence: List[RawEvidence] = []

        if doc_source_filters or entity_types or db_table_filters:
            enriched_context = {
                **context,
                "doc_source_filters": doc_source_filters,
                "entity_types": entity_types if entity_types else None,
                "db_table_filters": db_table_filters,
            }
            try:
                graph_evidence = self.retrievers["graph"].retrieve(query, enriched_context)
            except Exception as e:
                logger.warning(f"[orchestrator] graph retriever (split path) failed: {e}")
        else:
            source_filters = self._extract_source_filters(all_evidence)
            if source_filters:
                logger.info(f"[orchestrator] 全局检索（降级）：按数据源过滤 {source_filters}")
                enriched_context = {**context, "source_filters": source_filters}
            else:
                logger.info(f"[orchestrator] 全局检索（降级）：无过滤条件")
                enriched_context = context

            entity_hints = set()
            for ev in all_evidence:
                table_name = ev.metadata.get("table", "")
                if table_name:
                    entity_hints.add(table_name)
            if entity_hints:
                enriched_context["entity_hints"] = list(entity_hints)

            try:
                graph_evidence = self.retrievers["graph"].retrieve(query, enriched_context)
            except Exception as e:
                logger.warning(f"[orchestrator] graph retriever (fallback) failed: {e}")

        all_evidence.extend(graph_evidence)

        entity_count = 0
        relation_count = 0
        doc_entity_count = 0
        db_entity_count = 0
        for ev in graph_evidence:
            if ev.source_type == "entity":
                entity_count += 1
                sk = ev.metadata.get("source_kind", "")
                if sk == "document":
                    doc_entity_count += 1
                elif sk == "database":
                    db_entity_count += 1
            elif ev.source_type == "graph_relation":
                relation_count += 1

        logger.info(
            f"[orchestrator] 检索汇总：文档摘要 {len(doc_evidence)} 条 + 数据库概要 {len(db_evidence)} 条"
            f" + 文档实体 {doc_entity_count} 个 + 数据库实体 {db_entity_count} 个"
            f" + 关系 {relation_count} 条 = 共 {len(all_evidence)} 条"
        )
        return all_evidence

    @staticmethod
    def _extract_source_filters(evidence: List[RawEvidence]) -> List[str]:
        prefixes: set = set()
        for ev in evidence:
            source_uuid = ev.metadata.get("source_uuid", "")
            if source_uuid:
                if ev.source_type == "document_summary":
                    prefixes.add(f"DOC://{source_uuid}/")
                elif ev.source_type == "database_summary":
                    prefixes.add(f"DBS://{source_uuid}/")
        return sorted(prefixes)
