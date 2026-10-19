"""⑤ Wiki 生成 —— 把③的摘要与④的图谱沉淀为可读页面

document/  文档页（摘要树 → Markdown）与跨文档主题页
entity/    图谱实体页（实体档案 → 页面）
service.py 页面 CRUD + 生成编排 + 答案发布 + 孤儿页清理

本轮不含数据库侧页面（库表 Wiki），预留同级 database/ 扩展位。

生成按 source_hash 幂等：上游一变（摘要重写/实体属性变化）下游自动重生成；
LLM 不可用时降级为确定性拼装，保证页面永不空缺。
"""
from wiki_generation.service import wiki_service

__all__ = ["wiki_service"]
