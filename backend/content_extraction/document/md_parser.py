"""
Markdown 章节解析 —— PDF（pymupdf4llm 输出）与 MD 转换共用的建树核心

输入是分页文本列表 [(page, markdown)]，page 为 None 表示无页码概念；
输出是章节 forest，标题层级由 `#` 数量决定，正文挂到当前章节。
"""
import re
from typing import List, Optional, Tuple

from .models import Section

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_CODE_FENCE_RE = re.compile(r"^(```|~~~)")

# 首个标题之前出现的正文挂到这个隐式章节
PREAMBLE_TITLE = "（开头）"

Pages = List[Tuple[Optional[int], str]]


def parse_markdown_sections(pages: Pages) -> List[Section]:
    """把按页组织（或整篇）的 markdown 解析为章节树

    章节正文只含本节文本；页码取该节标题所在页，正文跨页时刷新
    page_end（父节的页码区间在摘要阶段聚合）。
    """
    roots: List[Section] = []
    stack: List[Section] = []
    in_code = False

    for page, content in pages:
        page_no = page + 1 if page is not None else None
        for line in content.splitlines():
            stripped = line.strip()
            if _CODE_FENCE_RE.match(stripped):
                in_code = not in_code
                _append_text(roots, stack, line, page_no)
                continue
            if in_code:
                _append_text(roots, stack, line, page_no)
                continue
            m = _HEADER_RE.match(stripped)
            if m:
                level = len(m.group(1))
                while stack and stack[-1].level >= level:
                    stack.pop()
                node = Section(title=m.group(2).strip(), level=level,
                               page_start=page_no, page_end=page_no)
                if stack:
                    stack[-1].children.append(node)
                else:
                    roots.append(node)
                stack.append(node)
            else:
                _append_text(roots, stack, line, page_no)

    return _strip_empty(roots)


def _stack_for_text(roots: List[Section], stack: List[Section]) -> List[Section]:
    """正文必须挂在某个章节上：还没有任何章节时挂到隐式「开头」章节"""
    if not stack:
        if not roots or roots[0].title != PREAMBLE_TITLE:
            node = Section(title=PREAMBLE_TITLE, level=1)
            roots.insert(0, node)
            stack.append(node)
    return stack


def _append_text(roots: List[Section], stack: List[Section], line: str, page_no: Optional[int]):
    stack = _stack_for_text(roots, stack)
    node = stack[-1]
    node.text = f"{node.text}\n{line}" if node.text else line
    if page_no is not None:
        node.page_end = page_no
        if node.page_start is None:
            node.page_start = page_no


def _strip_empty(roots: List[Section]) -> List[Section]:
    """剪掉无标题文本的空壳章节（无 title 且无 text 且无子节）"""
    result = []
    for node in roots:
        node.children = _strip_empty(node.children)
        if node.title or node.text.strip() or node.children:
            result.append(node)
    return result


def single_section(doc_name: str, text: str, page_count: Optional[int] = None) -> List[Section]:
    """无结构可解析时的兜底：整个文档视作一个章节"""
    section = Section(title=doc_name, level=1, text=text.strip())
    if page_count is not None:
        section.page_start, section.page_end = 1, page_count
    return [section]
