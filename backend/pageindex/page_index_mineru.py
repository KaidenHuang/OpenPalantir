import asyncio
import os
from io import BytesIO
from .utils import *
from system.logger import logger


async def page_index_builder_from_structure(doc, structure, opt):
    """
    从 MinerU 提取的结构构建 PageIndex 树。

    MinerU 已提供文本内容，此函数仅负责：
    - 添加 node_id
    - 生成摘要（LLM）
    - 生成文档描述（LLM）
    """
    if opt.if_add_node_id == 'yes':
        write_node_id(structure)

    if opt.if_add_node_summary == 'yes':
        await generate_summaries_for_structure(structure, model=opt.model)

    structure = format_structure(
        structure,
        order=['title', 'node_id', 'summary', 'text', 'nodes']
    )

    result = {
        'doc_name': get_pdf_name(doc),
        'structure': structure,
    }

    if opt.if_add_doc_description == 'yes':
        clean_structure = create_clean_structure_for_description(structure)
        doc_description = generate_doc_description(clean_structure, model=opt.model)
        result['doc_description'] = doc_description

    return result


async def page_index_main_async(doc, opt=None):
    """
    PageIndex 主入口（异步）

    流程：MinerU 提取结构 → 添加摘要和描述
    """
    from document_processing.mineru_adapter import extract_pdf_structure

    is_valid_pdf = (
        (isinstance(doc, str) and os.path.isfile(doc) and doc.lower().endswith(".pdf"))
        or isinstance(doc, BytesIO)
    )
    if not is_valid_pdf:
        raise ValueError("Unsupported input type. Expected a PDF file path or BytesIO object.")

    logger.info('MinerU 提取 PDF 结构...')
    structure = extract_pdf_structure(doc)

    node_count = len(structure_to_list(structure)) if structure else 0
    logger.info(f"结构提取完成，共 {node_count} 个节点")

    return await page_index_builder_from_structure(doc, structure, opt)


def page_index_main(doc, opt=None):
    """PageIndex 主入口（同步）"""
    return asyncio.run(page_index_main_async(doc, opt))


def page_index(doc, model=None, **kwargs):
    """便捷入口（兼容旧接口）"""
    user_opt = {arg: value for arg, value in locals().items()
                if arg != "doc" and value is not None}
    opt = ConfigLoader().load(user_opt)
    return page_index_main(doc, opt)


# 兼容旧接口：page_index_builder 指向新函数
async def page_index_builder(doc, page_list, opt):
    """
    旧版 page_index_builder 的兼容包装。

    注意：page_list 参数已废弃，不再使用。
    结构提取已由 MinerU 完成，此函数直接调用新管线。
    """
    return await page_index_main_async(doc, opt)