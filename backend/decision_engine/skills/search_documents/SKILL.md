---
name: search_documents
description: 搜索文档摘要，查找与关键词相关的文档内容。输入搜索关键词，返回匹配的文档摘要列表。
category: document
parameters:
  - name: query
    type: string
    description: 搜索关键词
    required: true
  - name: limit
    type: integer
    description: 返回数量上限（默认5）
    required: false
---

# 文档搜索

搜索已分析的文档摘要，查找与关键词相关的文档内容。

## 使用场景

- 需要查找相关文档内容时使用
- 了解某个主题在文档中的覆盖情况时使用
- 补充图谱之外的文本信息时使用