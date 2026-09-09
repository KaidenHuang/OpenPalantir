"""
种子检索工具函数 — 中文分词（供内置工具复用）

SeedRetriever 类已移除，其功能由 list_summaries / get_summary_detail 内置工具替代。
"""
import re
from typing import List

# 尝试导入 jieba 分词，不可用时降级为正则分割
try:
    import jieba
    jieba.setLogLevel(20)  # 抑制 jieba 初始化日志
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

# 中文停用词：常见疑问词、代词、语气词等无检索价值的词
_STOP_WORDS = frozenset({
    "什么", "哪些", "几个", "多少", "如何", "怎么", "怎样",
    "为什么", "是否", "能否", "可以", "请问", "当前", "目前",
    "现在", "最近", "所有", "一些", "这个", "那个", "哪个",
    "我们", "你们", "他们", "它们", "自己", "其他",
    "帮我", "看看", "分析", "查一下", "告诉", "说说",
    "一下", "一个", "有没有", "有哪", "在哪", "是在",
    "都有", "都是", "之间", "关于", "以及", "还有",
    "需要", "希望", "想要", "知道", "了解", "查看",
    "情况", "问题", "进行", "通过", "对于", "根据",
})


def _tokenize_question(question: str) -> List[str]:
    """中文分词：jieba 优先，降级为正则分割 + 去停用词"""
    if _HAS_JIEBA:
        tokens = jieba.lcut(question)
    else:
        tokens = re.split(r'[的，。,．？?！!、\s:：；;]+', question)

    keywords = []
    for t in tokens:
        t = t.strip()
        if len(t) >= 2 and t not in _STOP_WORDS:
            keywords.append(t)
    return keywords
