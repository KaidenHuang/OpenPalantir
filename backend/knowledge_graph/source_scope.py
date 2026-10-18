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
