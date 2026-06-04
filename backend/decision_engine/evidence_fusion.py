import hashlib
import json as json_lib
from typing import Dict, List

from decision_engine.contracts import AnalyzedQuery, EvidenceItem, RawEvidence

SOURCE_PRIORITY = {
    "database_summary": 4,
    "document_summary": 3,
    "entity": 2,
    "graph_relation": 1,
}
MAX_EVIDENCE_PER_TYPE = 999


class EvidenceFusion:
    def fuse(self, raw: List[RawEvidence], query: AnalyzedQuery) -> List[EvidenceItem]:
        seen: set = set()
        unique: List[RawEvidence] = []
        for ev in raw:
            h = self._content_hash(ev.content)
            if h not in seen:
                seen.add(h)
                unique.append(ev)

        for ev in unique:
            score = ev.relevance_score
            score += SOURCE_PRIORITY.get(ev.source_type, 0) * 0.05
            if query.entities and any(e.lower() in str(ev.content).lower() for e in query.entities):
                score += 0.2
            ev.relevance_score = min(score, 1.0)

        unique.sort(key=lambda e: e.relevance_score, reverse=True)

        grouped: Dict[str, List[RawEvidence]] = {}
        for ev in unique:
            grouped.setdefault(ev.source_type, []).append(ev)

        result: List[EvidenceItem] = []
        for source_type, items in grouped.items():
            for i, ev in enumerate(items[:MAX_EVIDENCE_PER_TYPE]):
                source_name = ev.metadata.get("doc_name", "") or ev.metadata.get("table", "") or ev.metadata.get("db_name", "") or ev.metadata.get("name", "")
                result.append(EvidenceItem(
                    evidence_id=f"{source_type}-{i}",
                    source_type=source_type,
                    source_name=source_name,
                    summary=self._pick_summary(ev),
                    payload=ev.content,
                    relevance_score=ev.relevance_score,
                    citation=self._make_citation(source_type, source_name, ev.metadata),
                ))

        result.sort(key=lambda e: e.relevance_score, reverse=True)
        return result

    @staticmethod
    def _pick_summary(ev: RawEvidence) -> str:
        summary = (ev.content.get("summary", "")
                   or ev.metadata.get("summary", "")
                   or ev.metadata.get("description", "")
                   or ev.content.get("description", ""))
        if summary:
            return summary
        if ev.source_type == "graph_relation":
            s = ev.content.get("source", "")
            t = ev.content.get("target", "")
            p = ev.content.get("predicate", "关联")
            return f"{s} → {t}（{p}）" if s and t else str(ev.content)[:200]
        return ""

    @staticmethod
    def _content_hash(content: Dict) -> str:
        raw = json_lib.dumps(content, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()

    @staticmethod
    def _make_citation(source_type: str, name: str, metadata: Dict) -> str:
        if source_type == "document_summary":
            label = metadata.get("datasource", "") or name
            return f"[文档: {label}]"
        elif source_type == "database_summary":
            label = metadata.get("datasource", "") or name
            return f"[数据库: {label}]"
        elif source_type == "entity":
            return f"[实体: {name}]"
        elif source_type == "graph_relation":
            return f"[关系: {metadata.get('source', '')}→{metadata.get('target', '')}]"
        return name
