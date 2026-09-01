---
name: analyze_path
description: 分析知识图谱中两个实体之间的关联路径。输入起始和目标实体名称，返回它们之间的最短路径。
category: analysis
parameters:
  - name: source_entity
    type: string
    description: 起始实体名称
    required: true
  - name: target_entity
    type: string
    description: 目标实体名称
    required: true
  - name: k
    type: integer
    description: 返回路径数量（默认1）
    required: false
---

# 路径分析

分析知识图谱中两个实体之间的关联路径，揭示它们之间的连接方式。

## 使用场景

- 需要了解两个实体如何关联时使用
- 分析供应链、资金链、组织关系等间接关系时使用
- 发现隐藏的中间节点时使用