"""
embedding 混合检索工具单元测试

测试 embedding_utils：向量缓存、降级、余弦计算、混合重排。
LLM/embedding 客户端与 SQLite 均被隔离（Stub + temp_db fixture）。
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

import pytest

from decision_engine.retrievers import embedding_utils as eu
# 确保 embedding_cache 表注册进 Base.metadata（temp_db 建表用）
from models.embedding import EmbeddingCache  # noqa: F401


class EmbedStub:
    def __init__(self, vectors=None, fail=False):
        self.vectors = vectors
        self.fail = fail
        self.embed_calls = 0
        self.config = SimpleNamespace(embedding_model="bge-m3")

    def embed(self, texts):
        self.embed_calls += 1
        if self.fail:
            return None
        if self.vectors is not None:
            return self.vectors
        return [[1.0, 0.0] for _ in texts]


@pytest.fixture()
def embed_env(temp_db, monkeypatch):
    import config.database
    monkeypatch.setattr(config.database, "SessionLocal", temp_db)

    def _patch(client):
        monkeypatch.setattr("model_management.model_client.get_model_client",
                            lambda: client)
        return client
    return _patch


class TestCosine:

    def test_identical(self):
        assert eu.cosine_similarity([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)

    def test_orthogonal(self):
        assert eu.cosine_similarity([1, 0], [0, 1]) == 0.0

    def test_mismatch_or_empty(self):
        assert eu.cosine_similarity([1, 2], [1, 2, 3]) == 0.0
        assert eu.cosine_similarity([], [1]) == 0.0

    def test_negative_clamped_in_semantic_scores(self, embed_env):
        stub = EmbedStub(vectors=[[1.0, 0.0], [-1.0, 0.0]])
        embed_env(stub)
        scores = eu.semantic_scores("q", ["反向文本"])
        assert scores == [0.0]


class TestEmbedTexts:

    def test_cache_hit_avoids_second_embed(self, embed_env):
        stub = EmbedStub()
        embed_env(stub)
        first = eu.embed_texts(["甲", "乙"])
        second = eu.embed_texts(["甲", "乙"])

        assert first == [[1.0, 0.0], [1.0, 0.0]]
        assert second == first
        assert stub.embed_calls == 1

    def test_partial_cache_hit(self, embed_env):
        stub = EmbedStub()
        embed_env(stub)
        eu.embed_texts(["甲"])
        eu.embed_texts(["甲", "乙"])
        assert stub.embed_calls == 2  # 第二次仅请求缺失的"乙"

    def test_no_client_returns_none(self, embed_env):
        embed_env(None)
        assert eu.embed_texts(["甲"]) is None

    def test_embed_failure_returns_none(self, embed_env):
        stub = EmbedStub(fail=True)
        embed_env(stub)
        assert eu.embed_texts(["甲"]) is None

    def test_empty_input(self, embed_env):
        stub = EmbedStub()
        embed_env(stub)
        assert eu.embed_texts([]) == []
        assert stub.embed_calls == 0


class TestHybridRank:

    def test_fallback_to_keyword_scores(self, embed_env):
        embed_env(None)  # embedding 不可用
        items = [SimpleNamespace(t="a", s=0.2), SimpleNamespace(t="b", s=0.9),
                 SimpleNamespace(t="c", s=0.5)]
        ranked = eu.hybrid_rank("查询", items,
                                text_of=lambda i: i.t, score_of=lambda i: i.s)
        assert [i.t for i in ranked] == ["b", "c", "a"]

    def test_semantic_blend_reorders(self, embed_env):
        # query=[1,0]；"远"与 query 正交但关键词分高，"近"与 query 近似但关键词分低
        stub = EmbedStub(vectors=[[1.0, 0.0], [0.0, 1.0], [0.99, 0.01]])
        embed_env(stub)
        items = [SimpleNamespace(t="远", s=0.9), SimpleNamespace(t="近", s=0.5)]
        ranked = eu.hybrid_rank("查询", items,
                                text_of=lambda i: i.t, score_of=lambda i: i.s)
        assert [i.t for i in ranked] == ["近", "远"]

    def test_top_k_limit(self, embed_env):
        embed_env(None)
        items = [SimpleNamespace(t=str(i), s=i / 10) for i in range(5)]
        ranked = eu.hybrid_rank("q", items,
                                text_of=lambda i: i.t, score_of=lambda i: i.s, top_k=2)
        assert len(ranked) == 2
        assert ranked[0].t == "4"

    def test_empty_items(self, embed_env):
        assert eu.hybrid_rank("q", [], text_of=str, score_of=str) == []
