"""摘要模块的 LLM 调用层 —— 走 ModelClient，模型配置默认从模型管理取"""
import asyncio
from typing import Any, Dict, Optional

from system.logger import logger

# 中英文 token 数的轻量估算比例（不依赖 tokenizer 的字符数近似）
_CHINESE_CHAR_RATIO = 1.5
_ENGLISH_CHAR_RATIO = 4.0


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
    """单次 LLM 调用，返回纯文本响应（ModelClient 自带重试）"""
    from model_management import ModelClient

    client = ModelClient(model_config)
    return await asyncio.to_thread(client.call_raw, prompt)


def call_llm(model_config: Dict[str, Any], prompt: str) -> str:
    """同步形态的 LLM 调用（脚本/调试用）"""
    from model_management import ModelClient

    client = ModelClient(model_config)
    return client.call_raw(prompt)


def load_prompt(filename: str, fallback: str) -> str:
    """加载 prompts/ 下的模板文件，缺失时用 fallback"""
    import os

    path = os.path.join(os.path.dirname(__file__), "prompts", filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning(f"[summary_generation] prompt 文件缺失，使用兜底模板: {path}")
        return fallback
