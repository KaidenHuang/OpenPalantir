"""
文档摘要生成 —— 唯一的 LLM 环节

吃 content_extraction 的 ExtractedDocument，产出摘要树 dict
（落盘 JSON 的 structure 字段契约）：
  叶子节点: {title, node_id, page_start, page_end, summary, text}
  父节点:   {title, node_id, page_start, page_end, prefix_summary, nodes}

LLM 单节点失败时不打断任务：降级为使用原文作为摘要并记 warning；
完全没有可用模型时抛 RuntimeError（由任务层判定为模型未配置）。
"""
import asyncio
from typing import Any, Dict, List, Optional

from system.logger import logger
from .llm import call_llm_async, count_tokens, get_model_config, load_prompt
from .tree_utils import aggregate_text, convert_sections, flatten, page_span
from content_extraction import ExtractedDocument

_NODE_SUMMARY_PROMPT = """\
# 节点摘要生成任务

## 任务描述
根据给定的文档片段，生成该片段的摘要描述，说明该部分涵盖的主要内容。

## 语言一致性要求
输出语言必须与输入文本的语言保持一致。如果输入是中文，输出必须使用中文；如果输入是英文，输出必须使用英文。

## 输入文本
{text}

## 输出要求
直接返回摘要描述，不要包含任何其他文本。"""

_DOC_DESCRIPTION_PROMPT = """\
# 文档描述生成任务

## 任务描述
你是一个文档描述生成专家。请根据给定的文档结构，为该文档生成一句话描述，使该文档能够与其他文档区分开来。

## 语言一致性要求
输出语言必须与输入文本的语言保持一致。如果输入是中文，输出必须使用中文；如果输入是英文，输出必须使用英文。

## 文档结构
{structure}

## 输出要求
直接返回一句话描述，不要包含任何其他文本。"""

DEFAULT_SUMMARY_TOKEN_THRESHOLD = 200


async def _summarize_text(text: str, model_config: Dict[str, Any], threshold: int) -> str:
    """单段文本 → 摘要；短文本不做 LLM（直接原文，与旧行为一致）；失败降级为原文"""
    if count_tokens(text) < threshold:
        return text
    try:
        prompt = load_prompt("prompt_summary_node.md", _NODE_SUMMARY_PROMPT).replace("{text}", text)
        summary = (await call_llm_async(model_config, prompt)).strip()
        return summary or text
    except Exception as e:
        logger.warning(f"[summary_generation] 节点摘要 LLM 调用失败，降级为原文: {e}")
        return text


def _description_tree(nodes: List[dict]) -> List[dict]:
    """给文档描述用的骨架树：title + summary + 层级，不带正文"""
    skeleton = []

    def _walk(list_):
        for node in list_:
            entry = {
                "title": node["title"],
                "node_id": node["node_id"],
                "summary": node.get("summary") or "",
            }
            children = node.get("children") or []
            if children:
                entry["nodes"] = _walk(children)
            skeleton.append(entry)

    _walk(nodes)
    return skeleton


async def _generate_doc_description(nodes: List[dict], model_config: Dict[str, Any]) -> str:
    try:
        import json

        prompt = (
            load_prompt("prompt_doc_description.md", _DOC_DESCRIPTION_PROMPT)
            .replace("{structure}", json.dumps(_description_tree(nodes), ensure_ascii=False, indent=2))
        )
        return (await call_llm_async(model_config, prompt)).strip()
    except Exception as e:
        logger.warning(f"[summary_generation] 文档描述生成失败，降级为空描述: {e}")
        return ""


def _emit(nodes: List[dict]) -> List[dict]:
    """内部节点 → 落盘结构：叶子带 summary+text，父带 prefix_summary+nodes"""
    out: List[dict] = []
    for node in nodes:
        page_start, page_end = page_span(node)
        entry = {
            "title": node["title"],
            "node_id": node["node_id"],
            "page_start": page_start,
            "page_end": page_end,
        }
        if node["children"]:
            entry["prefix_summary"] = node.get("summary", "")
            entry["nodes"] = _emit(node["children"])
        else:
            entry["summary"] = node.get("summary", "")
            entry["text"] = node["own_text"]
        out.append(entry)
    return out


async def _summarize(extracted: ExtractedDocument, model_config: Dict[str, Any],
                     threshold: int, generate_doc_description: bool) -> Dict[str, Any]:
    tree = convert_sections(extracted)
    flat = flatten(tree)

    tasks = [_summarize_text(aggregate_text(node), model_config, threshold) for node in flat]
    summaries = await asyncio.gather(*tasks)

    for node, summary in zip(flat, summaries):
        node["summary"] = summary

    structure = _emit(tree)
    doc_description = ""
    if generate_doc_description:
        doc_description = await _generate_doc_description(tree, model_config)

    return {
        "doc_name": extracted.doc_name,
        "format": extracted.format,
        "page_count": extracted.page_count,
        "structure": structure,
        "doc_description": doc_description,
    }


def summarize_document(extracted: ExtractedDocument,
                       model_config: Optional[Dict[str, Any]] = None,
                       summary_token_threshold: int = DEFAULT_SUMMARY_TOKEN_THRESHOLD,
                       generate_doc_description: bool = True) -> dict:
    """ExtractedDocument → 摘要树 dict（落盘前的完整结果 dict）

    Raises:
        RuntimeError: 模型管理中没有可用模型
    """
    if model_config is None:
        model_config = get_model_config()
    if not model_config:
        raise RuntimeError("没有可用的模型，请先在模型管理中配置并激活模型")

    return asyncio.run(_summarize(extracted, model_config,
                                  summary_token_threshold, generate_doc_description))
