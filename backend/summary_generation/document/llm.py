"""摘要模块的 LLM 调用层 —— 走 ModelClient，模型配置默认从模型管理取"""
import asyncio
import os
from typing import Any, Dict, Optional, Tuple

# 中英文 token 数的轻量估算比例（不依赖 tokenizer 的字符数近似）
_CHINESE_CHAR_RATIO = 1.5
_ENGLISH_CHAR_RATIO = 4.0

# 节点摘要很短，给输出留 2048 足够；留得多，本地小模型也扛得住
SUMMARY_OUTPUT_TOKENS = 2048


def count_tokens(text: str) -> int:
    """估算文本 token 数（无需 tokenizer 依赖）"""
    if not text:
        return 0
    chinese = sum(1 for c in text if "一" <= c <= "鿿")
    other = len(text) - chinese
    return int(chinese * _CHINESE_CHAR_RATIO + other / _ENGLISH_CHAR_RATIO) + 1


def get_model_config() -> Optional[Dict[str, Any]]:
    """从模型管理取可用模型配置；没有可用模型返回 None"""
    from config.database import SessionLocal
    from model_management import ModelService

    db = SessionLocal()
    try:
        model_config = ModelService.get_available_model(db)
        if not model_config:
            return None
        model_name = (
            model_config.get("model_name")
            or (model_config.get("models") or [None])[0]
        )
        model_config["model_name"] = model_name
        return model_config
    finally:
        db.close()


async def call_llm_async(model_config: Dict[str, Any], prompt: str) -> str:
    """单次 LLM 调用，返回纯文本响应（ModelClient 自带重试）

    走 call_text 而非 JSON 出口：节点摘要就是一段白话，本地模型若被强加 format=json
    会把摘要写成带引号的 JSON 字符串，直接落进库和界面里。
    """
    from model_management import ModelClient

    client = ModelClient(model_config)
    return await asyncio.to_thread(client.call_text, prompt, "你是一个AI助手。", 0,
                                   SUMMARY_OUTPUT_TOKENS)


async def call_llm_json_async(model_config: Dict[str, Any], prompt: str,
                              max_tokens: int) -> Tuple[Optional[Dict[str, Any]], bool]:
    """表格分支的 JSON 出口：(解析结果, 输出是否被 max_tokens 截断)

    两个信号必须分开拿：截断说明拆批重发有用，解析失败但没截断说明模型吐的是
    不合格式的文本，加额度或拆批都没用 —— 调用方据此才能决定「拆批重试」还是「降级无标注」。
    """
    from model_management import ModelClient

    client = ModelClient(model_config)
    return await asyncio.to_thread(client.call_json_ex, prompt, None, 0, max_tokens)


def load_prompt(filename: str) -> str:
    """读取 prompts/ 下的模板；缺失直接抛 FileNotFoundError，由应用启动暴露"""
    path = os.path.join(os.path.dirname(__file__), "prompts", filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
