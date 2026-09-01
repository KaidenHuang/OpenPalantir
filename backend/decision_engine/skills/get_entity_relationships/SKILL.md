---
name: get_entity_relationships
description: 获取指定实体的所有关联关系（入边+出边）。输入实体名称，返回该实体与其他实体的关系列表。
category: graph
parameters:
  - name: entity_name
    type: string
    description: 实体名称
    required: true
---

# 实体关系查询

获取指定实体的所有关联关系，包括入边和出边，返回关系类型、关联实体名称和置信度。

## 使用场景

- 需要了解某个实体与哪些其他实体有关联时使用
- 分析实体在网络中的连接情况时使用
- 探索实体间的间接关系时使用