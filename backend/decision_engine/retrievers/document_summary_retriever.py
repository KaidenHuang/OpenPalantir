import json
import os
from typing import Dict, List

from system.logger import logger
from decision_engine.contracts import AnalyzedQuery, RawEvidence
from decision_engine.retrievers.base_retriever import BaseRetriever


class DocumentSummaryRetriever(BaseRetriever):
    source_type = "document_summary"

    def retrieve(self, query: AnalyzedQuery, context: Dict) -> List[RawEvidence]:
        results: List[RawEvidence] = []
        keywords = set(query.entities) | set(query.constraints.get("keywords", []))
        keywords.update(q for q in query.sub_questions if len(q) > 2)

        for file_path in self.glob_summary_files("DOC"):
            try:
                evidence = self._search_file(file_path, keywords, query)
                results.extend(evidence)
            except Exception as e:
                logger.warning(f"[retriever][document] error reading {file_path}: {e}")

        logger.info(f"[retriever][document] 文档摘要匹配到 {len(results)} 条相关内容")
        return results

    def _search_file(self, file_path: str, keywords: set, query: AnalyzedQuery) -> List[RawEvidence]:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        results: List[RawEvidence] = []
        doc_name = data.get("doc_name", os.path.basename(file_path))
        doc_desc = data.get("doc_description", "")

        source_uuid = self.extract_uuid_from_path(file_path, "DOC")

        # 从 JSON 文件名还原原始文档名（去掉 .json 后缀，保留 .txt 等原始扩展名）
        json_filename = os.path.basename(file_path)
        original_filename = json_filename[:-5] if json_filename.endswith(".json") else json_filename

        score = self.calc_score(doc_desc, keywords)
        if score > 0:
            doc_datasource = f"DOC://{source_uuid}/{original_filename}" if source_uuid else ""
            results.append(RawEvidence(
                source_type=self.source_type,
                source_id=doc_name,
                content={"doc_name": doc_name, "doc_description": doc_desc},
                relevance_score=score,
                metadata={"doc_name": doc_name, "type": "doc_description",
                          "source_uuid": source_uuid, "datasource": doc_datasource},
            ))

        for node in data.get("structure", []):
            self._walk_nodes(node, doc_name, keywords, results, source_uuid=source_uuid,
                             original_filename=original_filename)

        return results

    def _walk_nodes(self, node: dict, doc_name: str, keywords: set, results: List[RawEvidence],
                    depth: int = 0, source_uuid: str = "", original_filename: str = ""):
        if depth > 10:
            return
        title = node.get("title", "")
        summary = node.get("summary", "")

        score = self.calc_score(summary, keywords)
        if score > 0:
            doc_datasource = f"DOC://{source_uuid}/{original_filename}" if source_uuid else ""
            results.append(RawEvidence(
                source_type=self.source_type,
                source_id=f"{doc_name}/{title}",
                content={"title": title, "node_id": node.get("node_id", ""),
                         "line_num": node.get("line_num", ""), "summary": summary},
                relevance_score=score,
                metadata={"doc_name": doc_name, "title": title, "node_id": node.get("node_id", ""),
                          "source_uuid": source_uuid, "datasource": doc_datasource},
            ))

        for child in node.get("nodes", []):
            self._walk_nodes(child, doc_name, keywords, results, depth + 1, source_uuid, original_filename)
