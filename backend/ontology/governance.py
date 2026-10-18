"""
本体治理 — 词表使用统计与图谱合规检测

本体层上线不等于治理完成，必须能量化回答三件事：
1. 受控词表实际被用得怎么样（哪些 LinkType 从没出现过、多少边掉进兜底「其他」）；
2. 存量图谱哪里不合规（非法实体类型、非法谓词、定义域/值域越界、游离实体、无来源产出）；
3. 原始谓词该补哪些别名（兜底比例高的 raw_predicate 就是词表缺口）。

约束校验的口径取「所有域包该谓词 domain/range 的并集」，任一包声明不限则整体不限，
避免因为文档抽取时未指定 domain 而误报。
"""
from typing import Any, Dict, List, Optional, Tuple

from ontology.predicates import FALLBACK_PREDICATE
from ontology.registry import ontology_registry


def link_constraints() -> Dict[str, Dict[str, Any]]:
    """跨所有域包合并 LinkType 约束：{key: {domain, range, symmetric}}，空列表表示不限"""
    merged: Dict[str, Dict[str, Any]] = {}
    for domain in ontology_registry.domains():
        for link in ontology_registry.link_types(domain):
            entry = merged.setdefault(link.key, {"domain": [], "range": [], "unlimited_domain": False,
                                                 "unlimited_range": False})
            if not link.domain:
                entry["unlimited_domain"] = True
            else:
                entry["domain"] = sorted(set(entry["domain"]) | set(link.domain))
            if not link.range:
                entry["unlimited_range"] = True
            else:
                entry["range"] = sorted(set(entry["range"]) | set(link.range))
    return merged


def object_type_keys() -> List[str]:
    """所有域包声明过的 ObjectType key 并集"""
    keys: set = set()
    for domain in ontology_registry.domains():
        keys.update(o.key for o in ontology_registry.object_types(domain))
    return sorted(keys)


def vocabulary_usage() -> Dict[str, Any]:
    """谓词使用统计：分布、兜底占比、从未使用的词表项"""
    from knowledge_graph.graph_manager import graph_manager

    usage = graph_manager.predicate_usage()
    total = sum(usage.values())
    declared = ontology_registry.all_link_keys()
    fallback = usage.get(FALLBACK_PREDICATE, 0)
    return {
        "total_edges": total,
        "by_predicate": [{"predicate": p, "count": c,
                          "ratio": round(c / total, 4) if total else 0.0}
                         for p, c in sorted(usage.items(), key=lambda kv: -kv[1])],
        "fallback_count": fallback,
        "fallback_ratio": round(fallback / total, 4) if total else 0.0,
        "unused_link_types": [k for k in declared if usage.get(k, 0) == 0],
        "undeclared_predicates": [p for p in usage if p and p not in declared],
    }


def alias_candidates(limit: int = 20) -> List[Dict[str, Any]]:
    """被归一使用过的原始谓词排行 —— 词表别名的补充依据"""
    from knowledge_graph.graph_manager import graph_manager

    return [{"predicate": v["predicate"], "raw_predicate": v["raw_predicate"],
             "count": v["count"]} for v in graph_manager.raw_predicate_variants(limit)]


def type_usage_report() -> Dict[str, Any]:
    """实体类型分布与词表对照"""
    from knowledge_graph.graph_manager import graph_manager

    declared = object_type_keys()
    usage = graph_manager.type_usage()
    total = sum(usage.values())
    return {
        "total_entities": total,
        "by_type": [{"type": t, "count": c} for t, c in usage.items()],
        "illegal_types": [{"type": t, "count": c} for t, c in usage.items()
                          if t not in declared],
        "unused_types": [t for t in declared if usage.get(t, 0) == 0],
    }


def domain_range_violations(limit: int = 50) -> List[Dict[str, Any]]:
    """定义域/值域越界的边（按 谓词+类型组合 聚合计数）"""
    from knowledge_graph.graph_manager import graph_manager

    constraints = link_constraints()
    violations: List[Dict[str, Any]] = []
    for row in graph_manager.endpoint_type_pairs():
        entry = constraints.get(row["predicate"])
        if entry is None:
            continue
        subject_ok = (entry["unlimited_domain"] or not row["subject_type"]
                      or row["subject_type"] in entry["domain"])
        object_ok = (entry["unlimited_range"] or not row["object_type"]
                     or row["object_type"] in entry["range"])
        if subject_ok and object_ok:
            continue
        violations.append({
            "predicate": row["predicate"],
            "subject_type": row["subject_type"],
            "object_type": row["object_type"],
            "count": row["count"],
            "allowed_domain": [] if entry["unlimited_domain"] else entry["domain"],
            "allowed_range": [] if entry["unlimited_range"] else entry["range"],
        })
    violations.sort(key=lambda v: -v["count"])
    return violations[:limit]


def structure_issues(limit: int = 50) -> Dict[str, Any]:
    """图谱结构性问题：游离实体、未回填占位实体、来源缺失"""
    from knowledge_graph.graph_manager import graph_manager

    gaps = graph_manager.provenance_gaps()
    return {
        "isolated_entities": graph_manager.isolated_entities(limit),
        "placeholder_entities": graph_manager.placeholder_entities(limit),
        "entities_without_source": gaps["entities"],
        "edges_without_source": gaps["relationships"],
    }


def report(domain: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    """治理报告：词表使用 + 合规检测 + 可执行建议"""
    vocab = vocabulary_usage()
    types = type_usage_report()
    violations = domain_range_violations(limit)
    issues = structure_issues(limit)

    findings: List[str] = []
    if vocab["undeclared_predicates"]:
        findings.append(f"图谱中存在词表外的谓词: {vocab['undeclared_predicates']}")
    if vocab["fallback_ratio"] > 0.2:
        findings.append(f"兜底谓词「{FALLBACK_PREDICATE}」占比 "
                        f"{vocab['fallback_ratio']:.0%}，词表覆盖不足，按 alias_candidates 补别名")
    if types["illegal_types"]:
        findings.append(f"非法实体类型: {[t['type'] for t in types['illegal_types']]}")
    if violations:
        findings.append(f"{len(violations)} 类边违反定义域/值域约束")
    if issues["isolated_entities"]:
        findings.append(f"{len(issues['isolated_entities'])} 个游离实体未建立任何关系")
    if issues["entities_without_source"] or issues["edges_without_source"]:
        findings.append("存在无来源佐证的实体/边，无法参与按来源回收")
    if not findings:
        findings.append("图谱与本体一致，未发现治理项")

    result = {
        "domains": ontology_registry.domains(),
        "vocabulary": vocab,
        "object_types": types,
        "domain_range_violations": violations,
        "structure_issues": issues,
        "alias_candidates": alias_candidates(),
        "findings": findings,
    }
    if domain:
        result["pack"] = ontology_registry.export_pack(domain)
    return result


def pack_summary(domain: str) -> Tuple[str, int, int]:
    """(包名, ObjectType 数, LinkType 数)"""
    pack = ontology_registry.pack(domain)
    return pack.name, len(pack.object_types), len(pack.link_types)
