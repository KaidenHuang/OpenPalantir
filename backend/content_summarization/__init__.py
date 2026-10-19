"""文档摘要模块 —— 结构发现后的 LLM 摘要环节（与内容提取解耦）"""
from .summarizer import (
    DEFAULT_SUMMARY_TOKEN_THRESHOLD,
    summarize_document,
)

__all__ = ["summarize_document", "DEFAULT_SUMMARY_TOKEN_THRESHOLD"]
