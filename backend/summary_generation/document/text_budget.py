"""摘要环节的输入预算 —— 把每次 LLM 调用的输入压在模型窗口内

窗口大小来自模型配置（探测得到或手填，见 model_management.context_probe）；
预留出输出生成与 prompt 模板的额度，剩下的才是单条内容可用的预算。
超预算的内容按句子边界切块，块本身仍超预算时硬切并留痕，绝不静默丢尾部。
"""
import re
from typing import Any, Dict, List

from system.logger import logger
from .llm import SUMMARY_OUTPUT_TOKENS, count_tokens

# prompt 模板、子章节标题行等固定开销
PROMPT_OVERHEAD_TOKENS = 200
# 单个节点最少要能装下这么多内容，否则预算本身就没意义
MIN_BUDGET_TOKENS = 256

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？\n])")


def input_budget(model_config: Dict[str, Any],
                 output_reserve: int = SUMMARY_OUTPUT_TOKENS) -> int:
    """单次调用的内容预算（token）

    output_reserve 必须等于该次调用真正发给模型的 max_tokens：一次批量标注要返回
    一整批结果，输出额度比节点摘要大得多，还按 2048 反推就会把超出窗口的输入派给
    模型，而 Ollama 固定 num_ctx 时掐的是**输入尾部**（后出现的表格先被吃掉），
    表现为"标注缺失 + 名称对不上"，日志里一句窗口压力的字样都不会有。
    """
    from model_management.model_client import DEFAULT_CONTEXT_LENGTH

    context = int(model_config.get("context_length") or DEFAULT_CONTEXT_LENGTH)
    return max(MIN_BUDGET_TOKENS, context - output_reserve - PROMPT_OVERHEAD_TOKENS)


def char_step(text: str, budget: int) -> int:
    """按该文本自身的 token/字符比例，换算预算对应的字符数（至少 1）"""
    return max(1, int(len(text) * budget / count_tokens(text)))


def split_to_budget(text: str, budget: int) -> List[str]:
    """按句子边界切成若干段，每段估算 token 不超过预算；无法切的超长单句交给 truncate_to_budget"""
    if count_tokens(text) <= budget:
        return [text]
    sentences = [s for s in _SENTENCE_SPLIT.split(text) if s and s.strip()]
    if not sentences:
        return [text]
    parts: List[str] = []
    current = ""
    for sentence in sentences:
        if count_tokens(sentence) > budget:
            # 单句超预算：先收尾当前段，再把这句硬切成多条独立段
            if current:
                parts.append(current)
                current = ""
            step = char_step(sentence, budget)
            for i in range(0, len(sentence), step):
                parts.append(sentence[i:i + step])
            continue
        if current and count_tokens(current + sentence) > budget:
            parts.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        parts.append(current)
    return parts


def truncate_to_budget(text: str, budget: int) -> str:
    """硬截到预算内并留痕：只在切块归并仍压不下来时使用"""
    if count_tokens(text) <= budget:
        return text
    step = char_step(text, budget)
    logger.warning(f"[summary_generation] 内容归并后仍超预算（{count_tokens(text)}>"
                   f"{budget} token），截断保留前 {step} 字符")
    return text[:step]
