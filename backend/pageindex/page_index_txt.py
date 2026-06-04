import os
import re
from .utils import *
from .page_index_md import build_tree_from_nodes, generate_summaries_for_structure_md
from system.logger import logger


async def txt_to_tree(txt_path, if_add_node_summary='no', summary_token_threshold=None,
                      model=None, if_add_doc_description='no', if_add_node_text='no',
                      if_add_node_id='yes'):
    """为纯文本文档生成 PageIndex 树结构，按段落分割。"""
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    line_count = len(lines)

    # 按空行分割段落
    paragraphs = re.split(r'\n\s*\n', content.strip())
    node_list = []
    current_line = 1

    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue

        # 计算段落的起始行号
        para_start_line = current_line

        # 计算这个段落占了多少行
        para_lines = para.count('\n') + 1
        current_line += para_lines + 1  # +1 for blank line separator

        node_list.append({
            'title': f'段落 {i + 1}',
            'text': para,
            'level': 1,
            'line_num': para_start_line,
        })

    if not node_list:
        # 空文件或无法分割
        node_list.append({
            'title': os.path.splitext(os.path.basename(txt_path))[0],
            'text': content.strip(),
            'level': 1,
            'line_num': 1,
        })

    logger.info(f"Building tree from {len(node_list)} paragraphs")
    tree_structure = build_tree_from_nodes(node_list)

    if if_add_node_id == 'yes':
        write_node_id(tree_structure)

    if if_add_node_summary == 'yes':
        tree_structure = format_structure(tree_structure,
                                          order=['title', 'node_id', 'line_num', 'summary', 'text', 'nodes'])

        logger.info("Generating summaries for each paragraph")
        tree_structure = await generate_summaries_for_structure_md(
            tree_structure, summary_token_threshold=summary_token_threshold, model=model)

        if if_add_node_text == 'no':
            tree_structure = format_structure(tree_structure,
                                              order=['title', 'node_id', 'line_num', 'summary', 'nodes'])

        if if_add_doc_description == 'yes':
            logger.info("Generating document description")
            clean_structure = create_clean_structure_for_description(tree_structure)
            doc_description = generate_doc_description(clean_structure, model=model)
            return {
                'doc_name': os.path.splitext(os.path.basename(txt_path))[0],
                'doc_description': doc_description,
                'line_count': line_count,
                'structure': tree_structure,
            }
    else:
        if if_add_node_text == 'yes':
            tree_structure = format_structure(tree_structure,
                                              order=['title', 'node_id', 'line_num', 'summary', 'text', 'nodes'])
        else:
            tree_structure = format_structure(tree_structure,
                                              order=['title', 'node_id', 'line_num', 'summary', 'nodes'])

    return {
        'doc_name': os.path.splitext(os.path.basename(txt_path))[0],
        'line_count': line_count,
        'structure': tree_structure,
    }
