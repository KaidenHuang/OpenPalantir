---
name: analyze_centrality
description: 分析知识图谱的节点中心性，识别关键节点。支持 degree（度中心性）、betweenness（介数中心性）、closeness（接近中心性）、pagerank。
category: analysis
parameters:
  - name: centrality_type
    type: string
    description: 中心性类型（degree/betweenness/closeness/pagerank，默认全部）
    required: false
  - name: top_n
    type: integer
    description: 返回前N个节点（默认10）
    required: false
---

# 中心性分析

分析知识图谱的节点中心性，识别网络中的关键节点。

## 使用场景

- 识别组织中的核心人物或关键部门
- 发现供应链中的关键节点
- 评估节点在网络中的影响力