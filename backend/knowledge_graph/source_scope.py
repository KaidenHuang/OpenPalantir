"""
来源归属 Cypher 片段 —— 实体与关系来源的统一匹配口径

节点/边都有两级来源：datasource（主来源，展示与检索用）与 datasources（全部佐证来源）。
按来源过滤或回收必须走 datasources，否则被多来源佐证的节点/边只会归到主来源名下，
重跑其中一个来源就会连带删掉其他来源的佐证。
"""


def match_prefix(node: str, param: str = "$ds") -> str:
    """节点是否归属于某来源 URI 前缀（如 DOC://{id}/ 或 DBS://{conn}/{db}）"""
    return f"ANY(d IN coalesce({node}.datasources, []) WHERE d STARTS WITH {param})"


def match_either(node: str, param: str = "$ds") -> str:
    """整串相等或前缀匹配（调用方无法区分传入的是完整 URI 还是前缀时使用）"""
    return f"ANY(d IN coalesce({node}.datasources, []) WHERE d = {param} OR d STARTS WITH {param})"


def match_any_prefix(node: str, param: str = "$prefixes") -> str:
    """节点/边是否归属于前缀列表中的任一来源"""
    return (
        f"ANY(p IN {param} WHERE "
        f"ANY(d IN coalesce({node}.datasources, []) WHERE d STARTS WITH p))"
    )


def union_sources(node: str, src: str) -> str:
    """SET <node>.datasources = <并集表达式> —— 追加来源 URI 并去重，空来源不改动"""
    return (
        f"CASE WHEN {src} IS NULL OR {src} = '' THEN coalesce({node}.datasources, []) "
        f"WHEN {src} IN coalesce({node}.datasources, []) THEN {node}.datasources "
        f"ELSE coalesce({node}.datasources, []) + [{src}] END"
    )


def strip_prefix(node: str, param: str = "$prefix") -> str:
    """SET <node>.datasources = <移除该前缀后的来源列表>"""
    return f"[d IN coalesce({node}.datasources, []) WHERE NOT d STARTS WITH {param}]"


def strip_stale_evidence(node: str) -> str:
    """SET <node>.datasources = <移除该来源旧代产出的佐证列表>

    佐证条目形态 `{URI}@{content_hash}`（代际标记）：
    - 不是本来源前缀 → 保留（其他来源的佐证不动）
    - 是本来源前缀且 hash == $hash → 保留（本次刷新刚写入的新代佐证）
    - 其余（本来源的旧代条目、以及历史遗留的无 @ 纯 URI 条目）→ 摘除
    配套属性：Cypher 中以 STARTS WITH 判断前缀，hash 以 `@` 后缀精确匹配。
    """
    return (
        f"[d IN coalesce({node}.datasources, []) "
        f"WHERE NOT d STARTS WITH $prefix OR d ENDS WITH ('@' + $hash)]"
    )


def pure_uri(node: str) -> str:
    """从佐证条目还原展示用纯 URI（去掉 `@hash` 代缀）—— 常用于 datasource 主字段重算"""
    return f"split(coalesce(head({node}.datasources), ''), '@')[0]"
