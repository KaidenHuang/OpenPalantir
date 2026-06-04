import json
import os
from typing import Dict, List

from system.logger import logger
from decision_engine.contracts import AnalyzedQuery, RawEvidence
from decision_engine.retrievers.base_retriever import BaseRetriever


class DatabaseSummaryRetriever(BaseRetriever):
    source_type = "database_summary"

    def retrieve(self, query: AnalyzedQuery, context: Dict) -> List[RawEvidence]:
        results: List[RawEvidence] = []
        keywords = set(query.entities) | {query.intent, query.domain}
        keywords.update(str(v) for v in query.constraints.values() if isinstance(v, str))

        for file_path in self.glob_summary_files("DBS"):
            try:
                evidence = self._search_file(file_path, keywords, query)
                results.extend(evidence)
            except Exception as e:
                logger.warning(f"[retriever][database] error reading {file_path}: {e}")

        logger.info(f"[retriever][database] 数据库概要匹配到 {len(results)} 条相关内容")
        return results

    def _search_file(self, file_path: str, keywords: set, query: AnalyzedQuery) -> List[RawEvidence]:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        results: List[RawEvidence] = []
        business_domain = data.get("business_domain", "")
        db_name = data.get("db_name", "")

        source_uuid = self.extract_uuid_from_path(file_path, "DBS")

        if query.domain and business_domain and query.domain in business_domain:
            db_datasource = f"DBS://{source_uuid}/{db_name}" if source_uuid and db_name else ""
            results.append(RawEvidence(
                source_type=self.source_type,
                source_id=db_name or os.path.basename(file_path),
                content={"db_name": db_name, "db_description": data.get("db_description", ""),
                         "business_domain": business_domain},
                relevance_score=0.8,
                metadata={"business_domain": business_domain, "source_uuid": source_uuid,
                          "db_name": db_name, "datasource": db_datasource},
            ))

        for node in data.get("structure", []):
            self._walk_tables(node, keywords, results, source_uuid, db_name)

        return results

    def _walk_tables(self, node: dict, keywords: set, results: List[RawEvidence],
                      source_uuid: str = "", db_name: str = ""):
        table_name = node.get("table_name", "")
        summary = node.get("summary", "")
        entity_type = node.get("entity_type", "")

        search_text = f"{table_name} {summary} {entity_type}"
        score = self.calc_score(search_text, keywords)
        if score > 0:
            table_datasource = f"DBS://{source_uuid}/{db_name}/{table_name}" if source_uuid and db_name else ""
            results.append(RawEvidence(
                source_type=self.source_type,
                source_id=table_name,
                content={"table_name": table_name, "description": node.get("description", ""),
                         "summary": summary, "entity_type": entity_type,
                         "keys": node.get("keys", [])},
                relevance_score=score,
                metadata={"table": table_name, "entity_type": entity_type,
                          "source_uuid": source_uuid, "db_name": db_name,
                          "datasource": table_datasource},
            ))
