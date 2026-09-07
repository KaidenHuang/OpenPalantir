"""
SeedRetriever — 轻量级级联种子检索

在 Agentic 循环开始前做一次快速检索，为 LLM 提供初始上下文。
策略：文档/数据库摘要 → 提取 datasource_uri → 过滤 Neo4j 图检索
"""
import re
from typing import List

from decision_engine.agentic.types import SeedResult
from decision_engine.contracts import AnalyzedQuery
from decision_engine.retrievers.document_summary_retriever import DocumentSummaryRetriever
from decision_engine.retrievers.database_summary_retriever import DatabaseSummaryRetriever
from system.logger import logger

# 尝试导入 jieba 分词，不可用时降级为正则分割
try:
    import jieba
    jieba.setLogLevel(20)  # 抑制 jieba 初始化日志
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

# 中文停用词：常见疑问词、代词、语气词等无检索价值的词
_STOP_WORDS = frozenset({
    "什么", "哪些", "几个", "多少", "如何", "怎么", "怎样",
    "为什么", "是否", "能否", "可以", "请问", "当前", "目前",
    "现在", "最近", "所有", "一些", "这个", "那个", "哪个",
    "我们", "你们", "他们", "它们", "自己", "其他",
    "帮我", "看看", "分析", "查一下", "告诉", "说说",
    "一下", "一个", "有没有", "有哪", "在哪", "是在",
    "都有", "都是", "之间", "关于", "以及", "还有",
    "需要", "希望", "想要", "知道", "了解", "查看",
    "情况", "问题", "进行", "通过", "对于", "根据",
})


class SeedRetriever:
    """轻量级级联种子检索

    在海量数据下（百万实体），全局搜索噪声大且慢。
    级联过滤将检索范围缩小到相关文档/数据库对应的实体子集。
    """

    MAX_DOC_RESULTS = 5
    MAX_DB_RESULTS = 5
    MAX_ENTITIES = 20
    MAX_SOURCE_FILTERS = 5

    def __init__(self):
        self._doc_retriever = DocumentSummaryRetriever()
        self._db_retriever = DatabaseSummaryRetriever()

    @staticmethod
    def _tokenize(question: str) -> List[str]:
        """中文分词：jieba 优先，降级为正则分割 + 去停用词"""
        if _HAS_JIEBA:
            tokens = jieba.lcut(question)
        else:
            tokens = re.split(r'[的，。,．？?！!、\s:：；;]+', question)

        keywords = []
        for t in tokens:
            t = t.strip()
            if len(t) >= 2 and t not in _STOP_WORDS:
                keywords.append(t)
        return keywords

    def retrieve(self, question: str) -> SeedResult:
        """用问题执行级联检索，返回种子结果"""
        keywords = self._tokenize(question)
        query = AnalyzedQuery(entities=keywords, intent="general")

        # 阶段 1：文档 + 数据库摘要检索
        doc_evidence = []
        db_evidence = []
        try:
            doc_evidence = self._doc_retriever.retrieve(query, {})
        except Exception as e:
            logger.warning(f"[seed] 文档检索失败: {e}")
        try:
            db_evidence = self._db_retriever.retrieve(query, {})
        except Exception as e:
            logger.warning(f"[seed] 数据库检索失败: {e}")

        # 阶段 2：提取 datasource_uri（文档 + 数据库）
        all_uris = list(dict.fromkeys(
            ev.metadata["datasource"] for ev in doc_evidence + db_evidence
            if ev.metadata.get("datasource")
        ))[:self.MAX_SOURCE_FILTERS]

        # 阶段 3：用 URI 过滤图检索（文档和数据库对应的实体）
        entities = []
        if all_uris:
            try:
                from knowledge_graph.graph_manager import graph_manager
                for uri in all_uris:
                    found = graph_manager.search_entities_by_datasource(uri, limit=20)
                    entities.extend(found)
            except Exception as e:
                logger.warning(f"[seed] 图检索失败: {e}")

        # 阶段 4：按相关性排序并截断
        doc_top = sorted(
            doc_evidence, key=lambda e: e.relevance_score, reverse=True,
        )[:self.MAX_DOC_RESULTS]
        db_top = sorted(
            db_evidence, key=lambda e: e.relevance_score, reverse=True,
        )[:self.MAX_DB_RESULTS]
        entities_top = entities[:self.MAX_ENTITIES]

        logger.info(
            f"[seed] 种子检索完成: "
            f"文档={len(doc_top)}, 数据库={len(db_top)}, 实体={len(entities_top)}"
        )

        return SeedResult(
            doc_summaries=doc_top,
            db_summaries=db_top,
            related_entities=entities_top,
            total_sources=len(all_uris),
        )
