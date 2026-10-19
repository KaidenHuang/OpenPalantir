"""④ 实体抽取（文档侧）—— 分块与去重的纯函数行为

验证：
1. 摘要树摊平成正文段，超长段按句子切分
2. 小段合并成大块，且不超过 max_chunk
3. 跨批次去重时实体属性被合并（D5：不因先抽到的块没写属性而丢属性）
"""
import pytest

from entity_extraction.document.chunker import (
    dedupe_extraction,
    iter_segments,
    merge_segments_iter,
    split_text,
)


pytestmark = pytest.mark.unit


def test_iter_segments_flattens_tree_and_splits_long_text():
    tree = [
        {"title": "甲", "text": "短正文"},
        {
            "title": "父",
            "nodes": [
                {"title": "乙", "text": "超长" * 30},
                {"title": "丙", "text": "另一段"},
            ],
        },
    ]
    segments = list(iter_segments(tree, max_chunk=50))
    titles = [t for t, _ in segments]
    assert "甲" in titles and "另一段" in [s for _, s in segments]
    assert any(t.startswith("乙(切") for t in titles)
    assert all(len(s) <= 50 for _, s in segments)


def test_merge_segments_respects_max_chunk():
    segments = [("a", "x" * 600), ("b", "y" * 600), ("c", "z" * 400)]
    chunks = list(merge_segments_iter(segments, max_chunk=1500, min_size=1000))
    assert all(len(c) <= 1500 for c in chunks)
    assert sum(len(c) for c in chunks) == 1600
    assert len(chunks) == 2  # a+b 合并，c 单独成块


def test_split_text_splits_on_sentence_boundaries():
    text = "第一句。" + "第二句。" * 20
    parts = list(split_text(text, max_chunk=30))
    assert len(parts) > 1
    assert all(len(p) <= 30 for p in parts)
    assert "".join(parts) == text


def test_dedupe_merges_entity_attributes_across_chunks():
    all_entities = [
        {"n": "张三", "t": "人物", "c": 1},
        {"n": "张三", "t": "人物", "c": 3, "a": {"职位": "工程师"}, "d": "技术负责人"},
        {"n": "张三", "t": "人物", "c": 1, "a": {"部门": "技术部", "职位": "主管"}},
        {"n": "李四", "t": "人物"},
    ]
    all_relationships = [
        {"s": "张三", "p": "认识", "o": "李四"},
        {"s": "张三", "p": "认识", "o": "李四"},
    ]
    entities, relationships = dedupe_extraction(all_entities, all_relationships)

    assert len(entities) == 2
    assert len(relationships) == 1
    zhang = next(e for e in entities if e["n"] == "张三")
    # 先到的块没写属性、后到的块写了 → 属性补齐而非丢弃
    assert zhang["a"] == {"部门": "技术部", "职位": "工程师"}
    assert zhang["c"] == 3
    assert zhang["d"] == "技术负责人"


def test_dedupe_keeps_later_description_when_first_empty():
    entities, _ = dedupe_extraction(
        [{"n": "A", "t": "T"}, {"n": "A", "t": "T", "d": "说明"}], [])
    assert len(entities) == 1
    assert entities[0]["d"] == "说明"
