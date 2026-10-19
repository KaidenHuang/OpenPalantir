"""章节树 → 摘要树的核心算法（node_id 分配、子树正文聚合、页码区间聚合）"""
from typing import List, Optional

from content_extraction import ExtractedDocument, Section


def convert_sections(extracted: ExtractedDocument) -> List[dict]:
    """章节 forest → 可变的节点 dict 树（DFS 分配 node_id）"""
    seq = [0]

    def _walk(section: Section) -> dict:
        node = {
            "title": section.title,
            "node_id": f"n{seq[0]}",
            "page_start": section.page_start,
            "page_end": section.page_end,
            "own_text": section.text,
        }
        seq[0] += 1
        node["children"] = [_walk(child) for child in section.children]
        return node

    return [_walk(s) for s in extracted.sections]


def flatten(nodes: List[dict]) -> List[dict]:
    """DFS 拍平"""
    flat: List[dict] = []

    def _walk(list_):
        for node in list_:
            flat.append(node)
            _walk(node["children"])

    _walk(nodes)
    return flat


def aggregate_text(node: dict) -> str:
    """子树正文聚合：自身正文 + 全部后代正文（父节点摘要与树导航语义与旧管线一致）"""
    parts = []
    if node["own_text"]:
        parts.append(node["own_text"])
    for child in node["children"]:
        text = aggregate_text(child)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def page_span(node: dict) -> tuple:
    """章节的页码区间：覆盖自身正文与全部后代的 min/max"""
    starts = [node["page_start"]] if node["page_start"] is not None else []
    ends = [node["page_end"]] if node["page_end"] is not None else []
    for child in node["children"]:
        child_start, child_end = page_span(child)
        if child_start is not None:
            starts.append(child_start)
        if child_end is not None:
            ends.append(child_end)
    return (min(starts) if starts else None, max(ends) if ends else None)


def page_label(start: Optional[int], end: Optional[int]) -> str:
    """页码区间 → 展示文本：p3 / p3-7；无页码为空"""
    if start is None:
        return ""
    if end is None or end == start:
        return f"p{start}"
    return f"p{start}-{end}"
