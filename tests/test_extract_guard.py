"""④ 零实体守卫改造的正反例

判据从「entity_count == 0 就失败」改成「批次全灭才失败」，
这是表格方案唯一动到既有失败语义之处，两组都要钉住：
  反例 批次全灭 → RuntimeError（任务失败）
  正例 合法空产出 → 正常返回且 entity_count == 0（任务成功）
"""
import json
from unittest.mock import MagicMock

import pytest

from entity_extraction.document.extractor import LLMEntityEnhancer
from entity_extraction.document.service import (
    DocumentExtractionService,
    guard_llm_available,
)

pytestmark = pytest.mark.unit


# ── guard_llm_available 判定表 ──────────────────────────


def test_guard_raises_when_all_batches_failed():
    result = {"entity_count": 0, "batch_total": 3, "batch_failed": 3}
    with pytest.raises(RuntimeError, match="全部调用失败"):
        guard_llm_available(result, "抽取")


def test_guard_allows_legit_empty_result():
    """0 实体 + 批次有成功 = 合法空产出（纯属性列表、③ 降级无标注），不能判失败"""
    result = {"entity_count": 0, "batch_total": 3, "batch_failed": 1}
    assert guard_llm_available(result, "抽取") is result


def test_guard_ignores_missing_batch_counts():
    """缺批次计数（旧调用方）时不报警，交回实体数以外的语义"""
    assert guard_llm_available({"entity_count": 0}, "抽取") == {"entity_count": 0}


def test_guard_partial_failure_with_entities_passes():
    assert guard_llm_available(
        {"entity_count": 7, "batch_total": 4, "batch_failed": 2}, "抽取"
    )["entity_count"] == 7


# ── LLMEntityEnhancer 的 batch_failed 语义 ──────────────


def _enhancer(responses):
    """绕过 __init__（不建真实模型客户端），只喂 call_json 的响应序列"""
    enhancer = LLMEntityEnhancer.__new__(LLMEntityEnhancer)
    responses = iter(responses)
    enhancer.model_client = MagicMock(call_json=lambda **kw: next(responses, None))
    return enhancer


def test_enhancer_none_is_failure_but_empty_object_is_not():
    """{} 是模型答「没有」，None 才是调用失败"""
    enhancer = _enhancer([{}])
    r = enhancer.extract_entities_and_relationships("这是一段足够短的正文。")
    assert r["entities"] == [] and r["batch_failed"] is False

    enhancer = _enhancer([None])
    r = enhancer.extract_entities_and_relationships("短文本没有实体。")
    assert r["batch_failed"] is True


def test_enhancer_split_half_needs_both_sides_failed():
    """返回空触发切半重试：一边成功一边失败仍有产出，不算批次失败"""
    text = "句子一。" * 600  # 2400 字符 > 2000，会切半
    enhancer = _enhancer([None, {"entities": [{"n": "甲", "t": "概念"}]}, None])
    result = enhancer.extract_entities_and_relationships(text)
    assert result["batch_failed"] is False
    assert len(result["entities"]) == 1

    enhancer = _enhancer([None, None, None])
    result = enhancer.extract_entities_and_relationships(text)
    assert result["batch_failed"] is True


def test_enhancer_chunking_all_chunks_failed_marks_batch_failed():
    enhancer = _enhancer([None, {"entities": [{"n": "甲", "t": "概念"}]}, None])
    result = enhancer.extract_entities_and_relationships("x" * 600, max_chunk_length=200)
    assert result["batch_failed"] is False  # 有一块成功
    assert len(result["entities"]) == 1

    enhancer = _enhancer([None, None, None])
    result = enhancer.extract_entities_and_relationships("x" * 600, max_chunk_length=200)
    assert result["batch_failed"] is True


# ── 批次计数在 extract_from_summary 汇总 ────────────────


@pytest.fixture
def summary_file(tmp_path):
    """两段各自成批的摘要 JSON（单段 >20000 字符，超过 merge_segments_iter 的块上限）"""
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({
        "structure": [
            {"title": "一", "text": "第一段正文。" * 2500, "summary": "甲"},
            {"title": "二", "text": "第二段正文。" * 2500, "summary": "乙"},
        ]
    }, ensure_ascii=False), encoding="utf-8")
    return str(path)


@pytest.fixture
def store_saves_everything(monkeypatch):
    import knowledge_graph.entity_data_store as store_mod

    monkeypatch.setattr(
        store_mod.EntityDataStore, "save_all",
        staticmethod(lambda entities, relationships, **kw: (len(entities), len(relationships))),
    )


def _patch_enhancer(monkeypatch, instance):
    import entity_extraction.document.extractor as extractor_mod

    monkeypatch.setattr(extractor_mod, "LLMEntityEnhancer", lambda model_config=None: instance)


def test_all_batches_failed_counts_every_batch(summary_file, store_saves_everything, monkeypatch):
    enhancer = MagicMock()
    enhancer.extract_entities_and_relationships.return_value = {
        "entities": [], "relationships": [], "batch_failed": True,
    }
    _patch_enhancer(monkeypatch, enhancer)

    result = DocumentExtractionService({"name": "fake"}).extract_from_summary(
        summary_path=summary_file, datasource="DOC://s/a.xlsx", parallelism=2,
    )
    assert (result["batch_total"], result["batch_failed"]) == (2, 2)
    assert result["entity_count"] == 0
    with pytest.raises(RuntimeError):
        guard_llm_available(result, "抽取")


def test_legit_empty_counts_zero_failures(summary_file, store_saves_everything, monkeypatch):
    enhancer = MagicMock()
    enhancer.extract_entities_and_relationships.return_value = {
        "entities": [], "relationships": [], "batch_failed": False,
    }
    _patch_enhancer(monkeypatch, enhancer)

    result = DocumentExtractionService({"name": "fake"}).extract_from_summary(
        summary_path=summary_file, datasource="DOC://s/a.xlsx", parallelism=2,
    )
    assert (result["batch_total"], result["batch_failed"]) == (2, 0)
    assert result["entity_count"] == 0
    assert guard_llm_available(result, "抽取") is result


def test_mixed_failure_keeps_entities_and_passes(summary_file, store_saves_everything, monkeypatch):
    results = iter([
        ({"entities": [{"n": "甲", "t": "概念"}], "relationships": [], "batch_failed": False}),
        ({"entities": [], "relationships": [], "batch_failed": True}),
    ])
    enhancer = MagicMock()
    enhancer.extract_entities_and_relationships.side_effect = lambda *a, **kw: next(results)
    _patch_enhancer(monkeypatch, enhancer)

    result = DocumentExtractionService({"name": "fake"}).extract_from_summary(
        summary_path=summary_file, datasource="DOC://s/a.xlsx", parallelism=1,
    )
    assert (result["batch_total"], result["batch_failed"]) == (2, 1)
    assert result["entity_count"] == 1
    guard_llm_available(result, "抽取")
