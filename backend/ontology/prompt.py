"""
本体 → 提示词片段渲染 — 抽取/标注 prompt 统一从注册表生成类型枚举

文档抽取（prompt_combined_template.md）与 DB 标注（prompt_schema_annotate.md）
共用同一词表渲染，保证两条导入路径对齐同一本体。
缓存按注册表版本号失效，社区包导入/reload 后新词表立刻进 prompt。
"""
from typing import Dict, Tuple

from .registry import ontology_registry

_cache: Dict[Tuple[int, str], Dict[str, str]] = {}


def _render(domain: str) -> Dict[str, str]:
    obj_lines = []
    for o in ontology_registry.object_types(domain):
        desc = o.description or o.display_name
        line = f"- {o.key}: {desc}"
        if o.parent:
            line += f"（{o.parent} 的子类型）"
        obj_lines.append(line)

    link_lines = []
    for l in ontology_registry.link_types(domain):
        line = f"- {l.key}: {l.description or l.display_name}"
        hints = []
        if l.domain:
            hints.append(f"主语类型 {'/'.join(l.domain)}")
        if l.range:
            hints.append(f"宾语类型 {'/'.join(l.range)}")
        if l.symmetric:
            hints.append("无向")
        if hints:
            line += f"（{'; '.join(hints)}）"
        link_lines.append(line)

    # 属性词表：来自各 ObjectType 声明的 properties（key 限定在实体类型内）
    prop_lines = []
    for o in ontology_registry.object_types(domain):
        for p in o.properties:
            desc = p.description or p.data_type
            prop_lines.append(f"- {o.key}.{p.key}: {desc}")

    return {
        "entity_types": "\n".join(obj_lines),
        "link_types": "\n".join(link_lines),
        "property_types": "\n".join(prop_lines) or "（无预声明属性）",
    }


def prompt_sections(domain: str = "general") -> Dict[str, str]:
    """返回 {'entity_types', 'link_types', 'property_types'} 提示词片段（按注册表版本 + 域缓存）"""
    domain = domain or "general"
    key = (ontology_registry.version, domain)
    cached = _cache.get(key)
    if cached:
        return cached
    rendered = _render(domain)
    _cache[key] = rendered
    return rendered


def clear_cache() -> None:
    _cache.clear()
