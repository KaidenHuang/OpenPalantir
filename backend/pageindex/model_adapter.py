"""
PageIndex 模型适配器

从模型管理系统获取可用的模型配置，全局注入到 PageIndex 的 LLM 调用接口。
PageIndex 内部通过 utils.py 的 set_model_config() 接收配置。

提供同步和异步两种入口，同步版本用于独立脚本，异步版本用于 FastAPI 路由。
"""

import asyncio
from typing import Optional, Dict, Any

from config.database import SessionLocal
from model_management import ModelService
from system.logger import logger


def get_model_config() -> Optional[Dict[str, Any]]:
    """
    从模型管理系统获取可用模型的配置字典。

    Returns:
        可直接传递给 ModelClient 的配置字典，
        如果没有可用模型，返回 None。
    """
    db = SessionLocal()
    try:
        model_config = ModelService.get_available_model(db)
        if not model_config:
            logger.error("PageIndex: 模型管理中没有可用的模型")
            return None

        model_name = (
            model_config.get('model_name')
            or (model_config.get('models') or [None])[0]
            or 'qwen2.5:7b'
        )
        model_config['model_name'] = model_name

        logger.info(f"PageIndex 使用模型: name={model_config.get('name')}, "
                    f"type={model_config.get('type')}, model={model_name}")
        return model_config
    finally:
        db.close()


# ── PDF ──────────────────────────────────────────────────────────────────────

def generate_pageindex_pdf(pdf_path: str) -> dict:
    """
    同步方式：为 PDF 文档生成 PageIndex 树结构。

    Raises:
        RuntimeError: 没有可用模型时抛出
    """
    async def _run():
        return await generate_pageindex_pdf_async(pdf_path)

    try:
        loop = asyncio.get_running_loop()
        # 已有事件循环（如在 FastAPI 中），创建新事件循环在线程中运行
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _run()).result()
    except RuntimeError:
        # 没有运行中的事件循环
        return asyncio.run(_run())


async def generate_pageindex_pdf_async(pdf_path: str) -> dict:
    """
    异步方式：为 PDF 文档生成 PageIndex 树结构。

    Raises:
        RuntimeError: 没有可用模型时抛出
    """
    model_config = get_model_config()
    if not model_config:
        raise RuntimeError("没有可用的模型，请先在模型管理中配置并激活模型")

    from .utils import set_model_config, clear_model_config
    from .page_index import page_index_main_async
    from .utils import ConfigLoader

    set_model_config(model_config)
    try:
        opt = ConfigLoader().load({
            'model': model_config['model_name'],
            'if_add_node_summary': 'yes',
            'if_add_doc_description': 'yes',
            'if_add_node_text': 'yes',
            'if_add_node_id': 'yes',
        })
        return await page_index_main_async(pdf_path, opt)
    finally:
        clear_model_config()


# ── Markdown ─────────────────────────────────────────────────────────────────

def generate_pageindex_md(md_path: str) -> dict:
    """
    同步方式：为 Markdown 文档生成 PageIndex 树结构。

    Raises:
        RuntimeError: 没有可用模型时抛出
    """
    async def _run():
        return await generate_pageindex_md_async(md_path)

    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _run()).result()
    except RuntimeError:
        return asyncio.run(_run())


async def generate_pageindex_md_async(md_path: str) -> dict:
    """
    异步方式：为 Markdown 文档生成 PageIndex 树结构。

    Raises:
        RuntimeError: 没有可用模型时抛出
    """
    model_config = get_model_config()
    if not model_config:
        raise RuntimeError("没有可用的模型，请先在模型管理中配置并激活模型")

    from .utils import set_model_config, clear_model_config
    from .page_index_md import md_to_tree

    set_model_config(model_config)
    try:
        return await md_to_tree(
            md_path=md_path,
            if_thinning=False,
            if_add_node_summary='yes',
            summary_token_threshold=200,
            model=model_config['model_name'],
            if_add_doc_description='yes',
            if_add_node_text='yes',
            if_add_node_id='yes',
        )
    finally:
        clear_model_config()


# ── TXT ──────────────────────────────────────────────────────────────────────

def generate_pageindex_txt(txt_path: str) -> dict:
    """
    同步方式：为 TXT 文档生成 PageIndex 树结构。
    """
    async def _run():
        return await generate_pageindex_txt_async(txt_path)

    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _run()).result()
    except RuntimeError:
        return asyncio.run(_run())


async def generate_pageindex_txt_async(txt_path: str) -> dict:
    """
    异步方式：为 TXT 文档生成 PageIndex 树结构。

    Raises:
        RuntimeError: 没有可用模型时抛出
    """
    model_config = get_model_config()
    if not model_config:
        raise RuntimeError("没有可用的模型，请先在模型管理中配置并激活模型")

    from .utils import set_model_config, clear_model_config
    from .page_index_txt import txt_to_tree

    set_model_config(model_config)
    try:
        import os
        try:
            _size = os.path.getsize(txt_path)
        except OSError:
            _size = 0
        logger.info(f"[TXT] txt_path={txt_path}, size={_size}")
        result = await txt_to_tree(
            txt_path=txt_path,
            if_add_node_summary='yes',
            summary_token_threshold=200,
            model=model_config['model_name'],
            if_add_doc_description='yes',
            if_add_node_text='yes',
            if_add_node_id='yes',
        )
        logger.info(f"[TXT] result structure nodes={len(result.get('structure',[]))}")
        return result
    finally:
        clear_model_config()
