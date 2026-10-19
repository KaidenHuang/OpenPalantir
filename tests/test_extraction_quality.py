"""
抽取质量基线（golden set 评测）

对 examples/docs 三篇示例文档做了人工标注（tests/golden/extraction_v1.json），
用来度量 LLMEntityEnhancer 的实体/关系抽取质量，并把结果落成可读报告。
两条测试的分工：

- test_golden_labels_are_in_controlled_ontology：金标本身必须落在受控本体词表内，
  且标注的名称确实出现在源文档中。不依赖模型，任何环境都会执行。
- test_extraction_meets_quality_floor：真实调用模型抽取并打分，
  没有可用模型时整体 skip，不阻塞 CI。

打分口径：
- 实体召回按规范化名称精确匹配金标必须项；类型正确率只在召回到的实体上统计。
- 名称覆盖率（precision 侧代理）：预测名称只要能对上金标或 optional 清单
  （允许互为子串）就算已知，对不上的算越界。
- 关系拆成两个指标：结构召回只看实体对（方向无关），谓词正确率只在结构命中的
  关系上统计归一化谓词是否落在金标可接受 key 集合。分开是为了区分
  「模型没发现这条关系」和「本体词表不够用」。
"""
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "extraction_v1.json"
REPORT_PATH = _ROOT / "logs" / "extraction_quality.json"

# 回归下限：低于此值说明 prompt/本体改动让抽取明显退化。
# 谓词正确率与越界率只报告不设限，等首轮真实数据出来后再收紧。
MIN_ENTITY_RECALL = 0.60
MIN_RELATION_RECALL = 0.50

_WHITESPACE = re.compile(r"\s+")


def _norm(name: Any) -> str:
    return _WHITESPACE.sub("", str(name or "")).lower()


def _load_golden() -> list[dict[str, Any]]:
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)["docs"]


def _doc_text(golden: dict[str, Any]) -> str:
    with open(_ROOT / golden["file"], encoding="utf-8") as f:
        return f.read()


GOLDEN_DOCS = _load_golden()
GOLDEN_IDS = [Path(d["file"]).name for d in GOLDEN_DOCS]


def _type_index(domain: str) -> dict[str, str]:
    """本体 key / 显示名 → key，用于把模型返回的 t 归一到受控 key"""
    from ontology.registry import ontology_registry

    index: dict[str, str] = {}
    for obj in ontology_registry.object_types(domain):
        index[obj.key] = obj.key
        index[_norm(obj.display_name)] = obj.key
    return index


@pytest.fixture(scope="module")
def enhancer():
    """真实模型客户端；无可用模型时跳过全部评测"""
    try:
        from config.database import SessionLocal
        from model_management import ModelService

        db = SessionLocal()
        try:
            config = ModelService.get_available_model(db)
        finally:
            db.close()
    except Exception as exc:  # 数据库不可用也算「没有模型」
        pytest.skip(f"读取模型配置失败: {exc}")

    if not config:
        pytest.skip("模型管理中没有可用模型，跳过抽取质量评测")

    from entity_extraction.document.extractor import LLMEntityEnhancer

    instance = LLMEntityEnhancer(model_config=config)
    probe = instance.model_client.call_json(
        prompt='只返回 JSON：{"ok":true}', temperature=0, max_tokens=32
    )
    if not probe:
        pytest.skip("模型探活失败：服务无响应或不可用")
    return instance


@pytest.mark.unit
def test_golden_labels_are_in_controlled_ontology():
    """金标用的类型与谓词必须在本体词表内，标注名称必须真实出现在文档里"""
    from ontology.registry import ontology_registry

    for golden in GOLDEN_DOCS:
        domain = golden["domain"]
        valid_types = {o.key for o in ontology_registry.object_types(domain)}
        valid_links = {link.key for link in ontology_registry.link_types(domain)}
        text = _norm(_doc_text(golden))

        required_names = [_norm(e["n"]) for e in golden["entities"]]
        assert len(required_names) == len(set(required_names)), f"{domain} 金标实体名重复"

        for entity in golden["entities"]:
            unknown = set(entity["t"]) - valid_types
            assert not unknown, f"{entity['n']} 的类型不在 {domain} 本体: {unknown}"
            assert _norm(entity["n"]) in text, f"金标实体 {entity['n']} 不在文档中"

        for name in golden.get("optional", []):
            assert _norm(name) in text, f"可选实体 {name} 不在文档中"

        for relation in golden["relations"]:
            unknown = set(relation["p"]) - valid_links
            assert not unknown, f"{relation['s']}→{relation['o']} 的谓词不在词表: {unknown}"
            assert _norm(relation["s"]) in text and _norm(relation["o"]) in text


def _score(golden: dict[str, Any], entities: list[dict],
           relationships: list[dict]) -> dict[str, Any]:
    from ontology.predicates import normalize_predicate

    domain = golden["domain"]
    type_index = _type_index(domain)

    predicted_names: list[str] = []
    for entity in entities:
        name = _norm(entity.get("n"))
        if name and name not in predicted_names:
            predicted_names.append(name)

    known_names = [_norm(e["n"]) for e in golden["entities"]] + [_norm(n) for n in golden.get("optional", [])]

    hits: list[str] = []
    misses: list[str] = []
    type_correct = 0
    for entity in golden["entities"]:
        name = _norm(entity["n"])
        if name not in predicted_names:
            misses.append(entity["n"])
            continue
        hits.append(entity["n"])
        resolved = [type_index.get(_norm(e.get("t"))) for e in entities if _norm(e.get("n")) == name]
        if any(key and key in entity["t"] for key in resolved):
            type_correct += 1

    unknown_names = [
        name for name in predicted_names
        if not any(name == known or name in known or known in name for known in known_names)
    ]
    off_taxonomy_types = [
        f"{_norm(e.get('n'))}:{e.get('t')}" for e in entities
        if type_index.get(_norm(e.get("t"))) is None
    ]

    # 预测关系按无向实体对归组，保留归一化后的谓词
    predicted_pairs: dict[frozenset, list[dict[str, str]]] = {}
    fallback_predicates: list[str] = []
    for relation in relationships:
        subject, obj = _norm(relation.get("s")), _norm(relation.get("o"))
        if not subject or not obj:
            continue
        key, in_vocab = normalize_predicate(str(relation.get("p") or ""))
        if not in_vocab:
            fallback_predicates.append(f"{subject}-{relation.get('p')}-{obj}")
        predicted_pairs.setdefault(frozenset((subject, obj)), []).append(
            {"key": key, "s": subject, "o": obj}
        )

    structural_hits: list[str] = []
    relation_misses: list[str] = []
    predicate_correct = 0
    direction_correct = 0
    for relation in golden["relations"]:
        subject, obj = _norm(relation["s"]), _norm(relation["o"])
        found = predicted_pairs.get(frozenset((subject, obj)))
        label = f"{relation['s']}→{relation['o']}"
        if not found:
            relation_misses.append(label)
            continue
        structural_hits.append(label)
        if any(item["key"] in relation["p"] for item in found):
            predicate_correct += 1
        if any(item["key"] in relation["p"] and item["s"] == subject and item["o"] == obj
               for item in found):
            direction_correct += 1

    def _ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0

    return {
        "domain": domain,
        "predicted_entity_count": len(predicted_names),
        "predicted_relationship_count": len(relationships),
        "entity_recall": _ratio(len(hits), len(golden["entities"])),
        "entity_hit": hits,
        "entity_miss": misses,
        "entity_type_accuracy": _ratio(type_correct, len(hits)),
        "name_coverage": _ratio(len(predicted_names) - len(unknown_names), len(predicted_names)),
        "unknown_names": unknown_names,
        "off_taxonomy_type_rate": _ratio(len(off_taxonomy_types), len(entities)),
        "off_taxonomy_types": off_taxonomy_types,
        "relation_recall": _ratio(len(structural_hits), len(golden["relations"])),
        "relation_hit": structural_hits,
        "relation_miss": relation_misses,
        "relation_predicate_accuracy": _ratio(predicate_correct, len(structural_hits)),
        "relation_direction_accuracy": _ratio(direction_correct, len(structural_hits)),
        "predicate_fallback_rate": _ratio(len(fallback_predicates), len(relationships)),
        "predicate_fallback_list": fallback_predicates,
    }


_RESULTS: dict[str, Any] = {}


def _dump_report() -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    overall = {
        "entity_recall": round(sum(r["entity_recall"] for r in _RESULTS.values()) / len(_RESULTS), 4),
        "relation_recall": round(sum(r["relation_recall"] for r in _RESULTS.values()) / len(_RESULTS), 4),
    }
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "golden_set": GOLDEN_PATH.name,
        "floors": {"min_entity_recall": MIN_ENTITY_RECALL, "min_relation_recall": MIN_RELATION_RECALL},
        "overall": overall,
        "docs": _RESULTS,
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("golden", GOLDEN_DOCS, ids=GOLDEN_IDS)
def test_extraction_meets_quality_floor(golden, enhancer):
    text = _doc_text(golden)
    result = enhancer.extract_entities_and_relationships(text, domain=golden["domain"])

    metrics = _score(golden, result.get("entities", []), result.get("relationships", []))
    doc_name = Path(golden["file"]).name
    _RESULTS[doc_name] = metrics
    _dump_report()

    print(f"\n[抽取质量] {doc_name} 实体召回 {metrics['entity_recall']:.2f} "
          f"漏: {metrics['entity_miss']}")
    print(f"[抽取质量] {doc_name} 关系结构召回 {metrics['relation_recall']:.2f} "
          f"漏: {metrics['relation_miss']} | 谓词正确率 {metrics['relation_predicate_accuracy']:.2f} "
          f"兜底率 {metrics['predicate_fallback_rate']:.2f}")
    print(f"[抽取质量] {doc_name} 类型正确率 {metrics['entity_type_accuracy']:.2f} "
          f"| 名称覆盖率 {metrics['name_coverage']:.2f} "
          f"| 越界名 {metrics['unknown_names']}")

    assert metrics["entity_recall"] >= MIN_ENTITY_RECALL, (
        f"实体召回 {metrics['entity_recall']:.2f} 低于下限 {MIN_ENTITY_RECALL}，"
        f"漏抽: {metrics['entity_miss']}"
    )
    assert metrics["relation_recall"] >= MIN_RELATION_RECALL, (
        f"关系结构召回 {metrics['relation_recall']:.2f} 低于下限 {MIN_RELATION_RECALL}，"
        f"漏抽: {metrics['relation_miss']}"
    )
