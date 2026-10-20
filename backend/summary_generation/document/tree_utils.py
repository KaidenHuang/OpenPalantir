"""章节树 → 摘要树的核心算法（node_id 分配、节点摘要输入组装、页码区间聚合）"""
from typing import List

from content_extraction import ExtractedDocument, Section
from content_extraction.document.models import KIND_TABLE


def convert_sections(extracted: ExtractedDocument) -> List[dict]:
    """章节 forest → 可变的节点 dict 树（DFS 分配 node_id）

    kind 是 ② 对「这一节是表格」的声明，必须随节点带到落盘结构，
    ③④ 的分派只认它，不按文件扩展名反推。
    """
    seq = [0]

    def _walk(section: Section) -> dict:
        node = {
            "title": section.title,
            "node_id": f"n{seq[0]}",
            "kind": section.kind,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "own_text": section.text,
        }
        seq[0] += 1
        node["children"] = [_walk(child) for child in section.children]
        return node

    return [_walk(s) for s in extracted.sections]


def is_table_tree(nodes: List[dict]) -> bool:
    """整棵树都是表格叶子 → 表格文档

    空树判 False：没有章节的文件不该因为 all([]) 为真而误入表格分支。
    """
    if not nodes:
        return False

    def _walk(list_: List[dict]) -> bool:
        return all(node["kind"] == KIND_TABLE and _walk(node["children"])
                   for node in list_)

    return _walk(nodes)


def flatten_by_depth(nodes: List[dict]) -> List[List[dict]]:
    """按层分组，深层在前 —— 父节点要用到子节点摘要，故自底向上逐层生成"""
    buckets: List[List[dict]] = []

    def _walk(list_, depth: int):
        for node in list_:
            while len(buckets) <= depth:
                buckets.append([])
            buckets[depth].append(node)
            _walk(node["children"], depth + 1)

    _walk(nodes, 0)
    return list(reversed(buckets))


def node_content(node: dict) -> str:
    """该节点摘要请求的输入：叶子取自身正文，父节点取自身正文 + 子节点摘要列表

    父节点不再重送子树全文（旧做法让全文按树深重复计入输入 token），
    改为消费已经生成的子节点摘要。
    """
    parts = []
    if node["own_text"]:
        parts.append(node["own_text"])
    lines = []
    for child in node["children"]:
        summary = (child.get("summary") or "").strip()
        if summary:
            lines.append(f"【{child['title']}】{summary}")
    if lines:
        parts.append("\n".join(lines))
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
