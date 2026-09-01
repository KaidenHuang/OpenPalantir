---
name: query_database
description: 查询数据库表概要信息，了解表结构和业务含义。输入表名或关键词，返回匹配的数据库表概要。
category: database
parameters:
  - name: table_query
    type: string
    description: 表名或关键词
    required: true
  - name: limit
    type: integer
    description: 返回数量上限（默认5）
    required: false
---

# 数据库概要查询

查询已分析的数据库表概要信息，了解表结构、字段含义和业务用途。

## 使用场景

- 需要了解数据库中有哪些相关表时使用
- 分析数据资产和数据血缘时使用
- 补充图谱之外的数据库元数据时使用