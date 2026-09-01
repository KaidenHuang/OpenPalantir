---
name: get_entity_detail
description: 获取指定实体的详细信息，包括属性、关联关系数量等。输入实体名称，返回实体的完整属性。
category: graph
parameters:
  - name: entity_name
    type: string
    description: 实体名称
    required: true
---

# 实体详情

获取指定实体的详细信息，包括所有属性、关联关系数量和最近的关联关系列表。

## 使用场景

- 需要了解某个实体的完整信息时使用
- 用户询问某个组织/人物的详细背景时使用
- 作为路径分析的起点