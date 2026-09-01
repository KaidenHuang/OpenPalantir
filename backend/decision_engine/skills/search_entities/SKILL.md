---
name: search_entities
description: 在知识图谱中搜索实体。输入搜索关键词，返回匹配的实体列表及其类型、描述、相似度。
category: graph
parameters:
  - name: query
    type: string
    description: 搜索关键词
    required: true
  - name: entity_type
    type: string
    description: 实体类型过滤（可选，如 person/organization/location/event/concept）
    required: false
  - name: limit
    type: integer
    description: 返回数量上限（默认10）
    required: false
---

# 实体搜索

在知识图谱中搜索实体。通过全文索引查找匹配的实体，返回实体名称、类型、描述和置信度。

## 使用场景

- 当用户询问某个组织、人物、地点或概念时使用
- 需要了解知识图谱中是否存在某个实体时使用
- 作为进一步分析（如查看实体详情、关联关系）的起点