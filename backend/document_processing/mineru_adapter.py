"""
MinerU PDF 结构提取适配器

使用 MinerU (magic-pdf) 一步完成 PDF 文本提取和章节结构解析，
输出 PageIndex 兼容的树结构，零 LLM 调用。

通过 magic-pdf CLI 调用，避免 Python 版本兼容性问题。
"""

import re
import os
import tempfile
import subprocess
import uuid
from typing import List
from system.logger import logger


def extract_pdf_with_mineru(pdf_path: str) -> str:
    """
    使用 MinerU CLI 提取 PDF，返回结构化 Markdown。

    MinerU 内部完成：文本提取 + 布局分析 + 阅读顺序 + 表格识别 + 公式识别
    """
    output_dir = os.path.join(tempfile.gettempdir(), f'mineru_{uuid.uuid4().hex[:8]}')
    os.makedirs(output_dir, exist_ok=True)

    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]

    cmd = [
        'python', '-m', 'magic_pdf.tools.cli',
        '-p', pdf_path,
        '-o', output_dir,
        '-m', 'auto',
        '-l', 'zh',
    ]

    logger.info(f"MinerU CLI: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        logger.error(f"MinerU CLI 失败: {result.stderr}")
        raise RuntimeError(f"MinerU 解析失败: {result.stderr}")

    # MinerU 输出结构: {output_dir}/{pdf_name}/{method}/{pdf_name}.md
    md_file = None
    for root, dirs, files in os.walk(output_dir):
        for f in files:
            if f.endswith('.md'):
                md_file = os.path.join(root, f)
                break

    if not md_file:
        raise RuntimeError(f"MinerU 未生成 Markdown 文件，输出目录: {output_dir}")

    with open(md_file, 'r', encoding='utf-8') as f:
        md_content = f.read()

    # 清理临时文件
    import shutil
    shutil.rmtree(output_dir, ignore_errors=True)

    return md_content


def markdown_headers_to_tree(markdown_content: str) -> list:
    """
    解析 Markdown 标题 (# ## ###) 构建树结构。

    输入: MinerU 输出的 Markdown 文本
    输出: [{title, level, text, nodes}, ...]

    例:
      # 第一章
      ## 1.1 概述
      正文内容...
      ## 1.2 详情
      更多内容...

      → [
          {title: "第一章", level: 1, text: "...", nodes: [
              {title: "1.1 概述", level: 2, text: "正文内容..."},
              {title: "1.2 详情", level: 2, text: "更多内容..."},
          ]}
        ]
    """
    lines = markdown_content.split('\n')
    header_pattern = r'^(#{1,6})\s+(.+)$'

    nodes = []
    for i, line in enumerate(lines):
        match = re.match(header_pattern, line.strip())
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            nodes.append({'title': title, 'level': level, 'line_num': i + 1})

    if not nodes:
        # 无标题时，整个文档作为一个节点
        title = lines[0].strip()[:50] if lines and lines[0].strip() else "文档"
        return [{'title': title, 'level': 1, 'text': markdown_content.strip()}]

    # 提取每个节点的文本内容
    for i, node in enumerate(nodes):
        start = node['line_num']
        end = nodes[i + 1]['line_num'] - 1 if i + 1 < len(nodes) else len(lines)
        node['text'] = '\n'.join(lines[start:end]).strip()

    # 复用 page_index_md.py 已有的 build_tree_from_nodes
    from pageindex.page_index_md import build_tree_from_nodes
    return build_tree_from_nodes(nodes)


def extract_pdf_structure(pdf_path: str) -> list:
    """
    PDF 结构提取主入口。

    Returns:
        tree_structure: PageIndex 兼容的树结构 [{title, level, text, nodes}, ...]
        每个节点的 text 字段已由 MinerU 填充。
    """
    markdown_content = extract_pdf_with_mineru(pdf_path)
    tree = markdown_headers_to_tree(markdown_content)

    node_count = _count_nodes(tree)
    logger.info(f"MinerU 提取完成: {node_count} 个节点, Markdown 长度: {len(markdown_content)}")
    return tree


def _count_nodes(tree: list) -> int:
    """统计树中节点总数"""
    count = 0
    for node in tree:
        count += 1
        if 'nodes' in node:
            count += _count_nodes(node['nodes'])
    return count