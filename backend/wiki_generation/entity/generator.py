"""
Wiki 实体页生成 — 从 Neo4j 聚合实体的属性与双向关系，生成「实体档案」页面

实体页是本体层反哺 Wiki 的入口：某实体在所有文档/数据库中的出现 → 一页。
LLM 不可用时降级为确定性拼装（属性 + 关系清单）。
"""
import hashlib
import json
import os
import re
from typing import Dict, List, Optional

from system.logger import logger
from config.neo4j_config import neo4j_conn

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")

MAX_ENTITY_PAGES = 20
MIN_DEGREE = 2
MAX_RELATIONSHIPS = 60

ENT_SCHEME = "ENT://"


def entity_datasource(entity_id: str, name: str) -> str:
    """实体页的来源标识 —— 一个实体页对应图谱中的一个实体"""
    return f"{ENT_SCHEME}{entity_id}/{name}"


def parse_entity_datasource(datasource: str) -> str:
    """ENT://{entity_id}/{name} → entity_id；非实体页返回空串"""
    if not datasource.startswith(ENT_SCHEME):
        return ""
    return datasource[len(ENT_SCHEME):].partition("/")[0]

# 属性里不值得进正文的噪音字段
_HIDDEN_ATTRS = {"id", "name", "type", "description", "count", "confidence",
                 "byname", "datasource", "created_at", "updated_at", "_placeholder"}

ENTITY_PROJECTION = """       n.id AS entity_id, n.name AS name, n.type AS type,
       n.description AS description, n.byname AS byname,
       n.datasource AS datasource, n.attributes AS attributes,
       n.count AS mention_count"""

TOP_ENTITIES_CYPHER = f"""
MATCH (n:Entity)
WHERE n._placeholder IS NULL AND n.name IS NOT NULL
OPTIONAL MATCH (n)-[r]-()
WITH n, count(r) AS degree
WHERE degree >= $min_degree
RETURN {ENTITY_PROJECTION}, degree
ORDER BY degree DESC, n.count DESC
LIMIT $limit
"""

ENTITY_BY_ID_CYPHER = f"""
MATCH (n:Entity {{id: $id}})
OPTIONAL MATCH (n)-[r]-()
WITH n, count(r) AS degree
RETURN {ENTITY_PROJECTION}, degree
"""

EDGES_CYPHER = """
UNWIND $ids AS eid
MATCH (n:Entity {id: eid})-[r]-(m:Entity)
RETURN eid AS entity_id,
       startNode(r).id AS subject_id, startNode(r).name AS subject,
       endNode(r).id AS object_id, endNode(r).name AS object,
       type(r) AS predicate, r.raw_predicate AS raw_predicate,
       r.description AS description, r.occurrence_time AS occurrence_time,
       m.id AS other_id, m.name AS other_name, m.type AS other_type,
       m.datasource AS other_datasource
LIMIT 2000
"""


def _load_prompt(name: str, **kwargs) -> str:
    with open(os.path.join(PROMPTS_DIR, name), "r", encoding="utf-8") as f:
        text = f.read()
    for key, value in kwargs.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def _clean_llm_markdown(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:markdown)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_attributes(raw) -> Dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _visible_attributes(attrs: Dict) -> Dict:
    return {k: v for k, v in attrs.items()
            if k not in _HIDDEN_ATTRS and v not in (None, "", [])}


def _profile_from_row(row: dict) -> dict:
    return {
        "entity_id": row.get("entity_id") or "",
        "name": row.get("name") or "",
        "type": row.get("type") or "other",
        "description": row.get("description") or "",
        "byname": row.get("byname") or "",
        "datasource": row.get("datasource") or "",
        "mention_count": row.get("mention_count") or 0,
        "degree": row.get("degree") or 0,
        "attributes": _visible_attributes(_parse_attributes(row.get("attributes"))),
        "relationships": [],
    }


def _attach_edges(profiles: List[dict]) -> None:
    """批量拉取双向关系并挂到各档案上（每实体上限 MAX_RELATIONSHIPS 条）"""
    if not profiles:
        return
    by_id = {p["entity_id"]: p for p in profiles}
    try:
        edges = neo4j_conn.execute_query(
            EDGES_CYPHER, {"ids": list(by_id.keys())})
    except Exception as e:
        logger.warning(f"[wiki] 实体关系查询失败: {e}")
        return

    for e in edges:
        p = by_id.get(e.get("entity_id"))
        if not p or len(p["relationships"]) >= MAX_RELATIONSHIPS:
            continue
        other_id = e.get("other_id") or ""
        if other_id == p["entity_id"]:
            continue
        p["relationships"].append({
            "outbound": e.get("subject_id") == p["entity_id"],
            "predicate": e.get("predicate") or "其他",
            "raw_predicate": e.get("raw_predicate") or "",
            "other_id": other_id,
            "other_name": e.get("other_name") or "",
            "other_type": e.get("other_type") or "other",
            "other_datasource": e.get("other_datasource") or "",
            "description": e.get("description") or "",
            "occurrence_time": e.get("occurrence_time") or "",
        })


def collect_entity_profiles(limit: int = MAX_ENTITY_PAGES,
                            min_degree: int = MIN_DEGREE) -> List[dict]:
    """按度数选取实体并附带双向关系，返回档案列表"""
    try:
        rows = neo4j_conn.execute_query(TOP_ENTITIES_CYPHER,
                                        {"limit": limit, "min_degree": min_degree})
    except Exception as e:
        logger.warning(f"[wiki] 实体候选查询失败: {e}")
        return []

    profiles = [_profile_from_row(r) for r in rows if r.get("entity_id")]
    _attach_edges(profiles)
    return [p for p in profiles if p["relationships"]]


def collect_entity_profile(entity_id: str) -> Optional[dict]:
    """单个实体 → 档案（图谱页面按需建页时使用）"""
    try:
        rows = neo4j_conn.execute_query(ENTITY_BY_ID_CYPHER, {"id": entity_id})
    except Exception as e:
        logger.warning(f"[wiki] 实体档案查询失败 {entity_id}: {e}")
        return None
    if not rows:
        return None
    profile = _profile_from_row(rows[0])
    _attach_edges([profile])
    return profile


def _relationships_lines(profile: dict) -> List[str]:
    lines = []
    for rel in profile["relationships"]:
        raw = f"（原文：{rel['raw_predicate']}）" if rel["raw_predicate"] else ""
        if rel["outbound"]:
            head = f"- {profile['name']} → {rel['predicate']} → {rel['other_name']}{raw}"
        else:
            head = f"- {rel['other_name']} → {rel['predicate']} → {profile['name']}{raw}"
        detail = []
        if rel["description"]:
            detail.append(rel["description"])
        if rel["occurrence_time"]:
            detail.append(f"时间：{rel['occurrence_time']}")
        lines.append(head + ("；" + "，".join(detail) if detail else ""))
    return lines


def _fallback_content(profile: dict, rel_lines: List[str]) -> str:
    name = profile["name"]
    lines = [f"# {name}", ""]
    meta = [f"类型：{profile['type']}"]
    if profile["byname"]:
        meta.append(f"又称：{profile['byname']}")
    meta.append(f"关联数：{profile['degree']}")
    lines += [f"> {'，'.join(meta)}", ""]
    if profile["description"]:
        lines += [profile["description"], ""]

    attrs = profile["attributes"]
    if attrs:
        lines += ["## 属性", ""]
        lines += [f"- {k}：{v}" for k, v in attrs.items()]
        lines.append("")

    if rel_lines:
        lines += ["## 关联关系", ""] + rel_lines
    return "\n".join(lines).rstrip() + "\n"


def _build_refs(profile: dict) -> List[dict]:
    """引用来源：实体本身 + 各关联实体（携带其 datasource 便于跳转溯源）"""
    refs = [{"n": 1, "datasource": profile["datasource"],
             "node_id": profile["entity_id"], "title": profile["name"]}]
    seen = {profile["entity_id"]}
    for rel in profile["relationships"]:
        oid = rel["other_id"]
        if not oid or oid in seen:
            continue
        seen.add(oid)
        refs.append({"n": len(refs) + 1, "datasource": rel["other_datasource"],
                     "node_id": oid, "title": rel["other_name"]})
    return refs


def profile_fingerprint(profile: dict) -> str:
    """实体档案指纹 —— 关系或属性变化即失效"""
    parts = [profile["entity_id"], profile["type"], profile["description"],
             json.dumps(profile["attributes"], ensure_ascii=False, sort_keys=True)]
    for rel in profile["relationships"]:
        parts.append(f"{rel['predicate']}|{rel['other_id']}|{rel['description']}")
    return hashlib.md5("\n".join(parts).encode("utf-8")).hexdigest()


def generate_entity_page(profile: dict) -> Optional[dict]:
    """单个实体档案 → Wiki 页。返回 {title, content, refs, datasource, source_hash}"""
    name = profile.get("name", "")
    if not name:
        return None

    rel_lines = _relationships_lines(profile)
    attrs = profile["attributes"]

    prompt = _load_prompt(
        "prompt_entity_page.md",
        entity_name=name,
        entity_type=profile["type"],
        byname=profile["byname"] or "无",
        description=profile["description"] or "无",
        attributes="\n".join(f"- {k}：{v}" for k, v in attrs.items()) or "无",
        relationships="\n".join(rel_lines) or "无",
    )

    content = ""
    try:
        from model_management.model_client import get_model_client
        client = get_model_client()
        if client:
            content = _clean_llm_markdown(client.call_text(prompt, max_tokens=16384))
    except Exception as e:
        logger.warning(f"[wiki] 实体页 LLM 生成失败，降级拼装: {e}")

    if not content:
        content = _fallback_content(profile, rel_lines)

    return {
        "title": name,
        "kind": "entity",
        "content": content,
        "refs": _build_refs(profile),
        "datasource": entity_datasource(profile["entity_id"], name),
        "source_hash": profile_fingerprint(profile),
        "entity_id": profile["entity_id"],
    }


def generate_entity_pages(limit: int = MAX_ENTITY_PAGES,
                          min_degree: int = MIN_DEGREE) -> List[dict]:
    """图谱中的高连接度实体 → 实体页素材列表（供 WikiService 落库）"""
    results = []
    for profile in collect_entity_profiles(limit=limit, min_degree=min_degree):
        try:
            page = generate_entity_page(profile)
            if page:
                results.append(page)
        except Exception as e:
            logger.warning(f"[wiki] 实体页生成失败 {profile.get('name')}: {e}")
    return results


def generate_entity_page_by_id(entity_id: str) -> Optional[dict]:
    """指定实体 → 实体页素材（图谱侧按需建页）"""
    profile = collect_entity_profile(entity_id)
    if not profile:
        return None
    return generate_entity_page(profile)
