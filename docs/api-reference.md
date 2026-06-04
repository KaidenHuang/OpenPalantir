# API 接口文档 | API Reference

## 基础信息

- **Base URL**: `http://localhost:8001`
- **Content-Type**: `application/json`
- **API 文档 (Swagger)**: `http://localhost:8001/docs`
- **API 文档 (ReDoc)**: `http://localhost:8001/redoc`
- **响应格式**:

```json
{
  "status": "success",
  "data": { ... }
}
```

```json
{
  "detail": "错误描述"
}
```

---

## 1. 系统接口 | System

### `GET /`
服务根路径，返回运行状态。

**Response**:
```json
{"message": "分析决策系统API服务运行中"}
```

### `GET /api/system/health`
健康检查。

**Response**:
```json
{
  "status": "healthy",
  "timestamp": 1717200000.0,
  "service": "OpenPalantir",
  "version": "1.0.0"
}
```

### `GET /api/system/info`
系统信息。

### `GET /api/system/config`
当前运行配置（密码等敏感信息已脱敏）。

### `GET /api/system/metrics`
Prometheus 格式的监控指标。

---

## 2. 图谱接口 | Graph

所有接口前缀：`/api/graph`

### `GET /nodes`
节点/实体列表（分页+搜索+类型过滤）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page` | int | 否 | 页码，默认 1 |
| `limit` | int | 否 | 每页条数，默认 10，最大 1000 |
| `entity_type` | string | 否 | 实体类型过滤 |
| `query` | string | 否 | 搜索关键词 |

**Response**:
```json
{
  "status": "success",
  "data": {
    "entities": [{ "id": "...", "name": "习近平", "type": "人物", ... }],
    "pagination": {
      "total_count": 1500,
      "total_pages": 150,
      "current_page": 1,
      "page_size": 10
    }
  }
}
```

### `GET /nodes/{entity_id}`
获取节点/实体详情。

### `PUT /nodes/{entity_id}`
更新实体属性。

**Request Body**:
```json
{
  "name": "新名称",
  "type": "人物",
  "description": "描述信息",
  "attributes": { "key": "value" }
}
```

### `DELETE /nodes/{entity_id}`
删除实体及其所有关系。

### `POST /nodes/search`
实体搜索（POST 方式，支持更复杂搜索）。

**Request Body**:
```json
{
  "query": "习近平",
  "limit": 10,
  "page": 1,
  "entity_type": "人物"
}
```

### `GET /edges`
获取所有关系/边列表。

### `GET /edges/{relationship_id}`
获取指定关系详情。

### `DELETE /edges/{relationship_id}`
删除指定关系。

### `GET /entities/stats`
实体统计信息（各类型数量分布等）。

### `GET /edges/search?query=xxx`
关系搜索。

---

## 3. 分析引擎接口 | Analysis

所有接口前缀：`/api/analysis`

### `POST /path`
路径分析。

**Request Body**:
```json
{
  "source_entity": "实体A",
  "target_entity": "实体B",
  "k": 1,
  "weighted": false
}
```

**Response**:
```json
{
  "source": "实体A",
  "target": "实体B",
  "paths": [["实体A", "中间节点", "实体B"]],
  "path_lengths": [2],
  "total_paths": 1
}
```

### `POST /community`
社区发现（Louvain 算法）。

**Response**:
```json
{
  "communities": [
    { "id": 0, "nodes": ["节点1", "节点2"], "size": 2, "modularity": 0.65 }
  ],
  "modularity": 0.65
}
```

### `POST /centrality`
中心性分析。

**Request Body**:
```json
{
  "centrality_types": ["degree", "betweenness", "eigenvector", "pagerank"]
}
```

**Response**:
```json
{
  "degree_centrality": { "节点A": 0.85, "节点B": 0.42 },
  "betweenness_centrality": { ... },
  ...
}
```

### `POST /trend`
趋势分析。

**Request Body**:
```json
{
  "time_range": "30d",
  "metrics": ["entity_count", "relationship_count"]
}
```

### `POST /report`
生成分析报告。

**Request Body**:
```json
{
  "analysis_type": "community|centrality|trend",
  "format": "html"
}
```

---

## 4. 决策引擎接口 | Decision

所有接口前缀：`/api/decision`

### `POST /ask`
智能决策问答（核心接口）。

**Request Body**:
```json
{
  "question": "公司当前的人力资源分布情况如何？",
  "domain": "workforce",
  "connection_id": "optional-uuid",
  "context": {},
  "session_id": "sess_abc123"
}
```

**Response**:
```json
{
  "domain": "workforce",
  "intent": "hr_distribution_analysis",
  "session_id": "sess_abc123",
  "analyzed_query": {
    "domain": "workforce",
    "intent": "...",
    "entities": ["公司", "人力资源"],
    "sub_questions": ["..."],
    "reasoning": "..."
  },
  "evidence": [
    {
      "evidence_id": "...",
      "source_type": "database|graph|document",
      "source_name": "...",
      "summary": "...",
      "relevance_score": 0.95
    }
  ],
  "evidence_citations": [
    { "citation": "...", "source_type": "graph", "source_id": "..." }
  ],
  "answer": {
    "summary": "...",
    "situation_analysis": "...",
    "key_issues": [],
    "options": [],
    "recommendation": "...",
    "work_orders": [
      {
        "title": "...",
        "priority": "P1",
        "owner_role": "...",
        "steps": ["步骤1", "步骤2"],
        "acceptance_criteria": ["..."],
        "due_hint": "..."
      }
    ]
  }
}
```

### `GET /session/{session_id}`
获取会话历史，用于页面重载时恢复对话。

---

## 5. 数据库管理接口 | Database

所有接口前缀：`/api/database`

### `POST /test-connection`
测试数据库连接配置（不保存）。

**Request Body**:
```json
{
  "name": "生产数据库",
  "type": "mysql|postgresql|sqlite",
  "host": "localhost",
  "port": 3306,
  "database": "mydb",
  "username": "root",
  "password": "xxx",
  "description": "可选描述"
}
```

### `POST /connections`
创建数据库连接配置并保存。

### `GET /connections`
获取所有数据库连接列表。

### `GET /connections/{connection_id}`
获取指定连接详情。

### `PUT /connections/{connection_id}`
更新连接配置。

**Request Body** (所有字段可选):
```json
{
  "name": "新名称",
  "host": "new-host"
}
```

### `DELETE /connections/{connection_id}`
删除连接配置。

### `GET /connections/{connection_id}/databases`
获取数据库服务器上的所有数据库列表（含分析状态）。

### `POST /connections/{connection_id}/analyze`
分析数据库 Schema（阶段1）。

**Request Body**:
```json
{
  "tables": ["users", "orders"],
  "ignore_tables": ["tmp_*"],
  "database": "mydb"
}
```

### `POST /connections/{connection_id}/import`
图谱导入（阶段2，创建异步任务）。

### `GET /connections/{connection_id}/tables`
获取已分析的表列表。

### `GET /connections/{connection_id}/tables/{table_name}`
获取指定表的 Schema 详情（含 LLM 标注）。

---

## 6. 文档源接口 | Source

### `POST /api/sources`
创建文档源。

**Request Body**:
```json
{
  "name": "红楼梦",
  "path": "/data/books/红楼梦.txt",
  "source_type": "local|s3"
}
```

### `GET /api/sources`
获取所有文档源列表。

### `GET /api/sources/{source_id}`
获取文档源详情。

### `PUT /api/sources/{source_id}`
更新文档源信息。

### `DELETE /api/sources/{source_id}`
软删除文档源。

### `POST /api/sources/{source_id}/process`
处理文档（异步任务）：解析文本 → 生成摘要树 → 提取实体和关系 → 写入图谱。

### `GET /api/sources/{source_id}/summary`
获取文档摘要树。

### `GET /api/sources/{source_id}/tasks`
获取文档相关的所有任务。

---

## 7. 文件系统接口 | Filesystem

所有接口前缀：`/api/filesystem`

### `GET /browse?path=/data/documents`
浏览文件系统。空路径返回驱动器列表（Windows）或根目录。

**Response**:
```json
{
  "path": "/data/documents",
  "items": [
    { "name": "novel.txt", "path": "/data/documents/novel.txt", "is_dir": false, "size": 1024 },
    { "name": "reports", "path": "/data/documents/reports", "is_dir": true, "size": 0 }
  ]
}
```

---

## 8. 模型管理接口 | Model

所有接口前缀：`/api/model`

### `GET /models`
获取所有 LLM 模型配置。

### `GET /models/{model_id}`
获取单个模型详情。

### `PUT /models/{model_id}`
更新模型配置。

**Request Body**:
```json
{
  "name": "硅基流动",
  "type": "cloud",
  "api_url": "https://api.siliconflow.cn/v1",
  "api_key": "sk-xxx",
  "models": ["deepseek-ai/DeepSeek-V3"],
  "enabled": true
}
```

### `PUT /models/{model_id}/toggle`
启用/禁用模型。

### `POST /models/{model_id}/test`
测试模型连接。

**Response**:
```json
{
  "success": true,
  "message": "连接测试成功",
  "latency_ms": 320
}
```

---

## 9. 任务管理接口 | Task

所有接口前缀：`/api/task`

### `GET /tasks`
获取所有任务列表（支持状态筛选）。

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态筛选：pending/running/completed/failed |
| `page` | int | 页码 |
| `limit` | int | 每页条数 |

### `GET /tasks/{task_id}`
获取任务详情（含执行日志）。

### `POST /tasks`
手动创建任务。

### `DELETE /tasks/{task_id}`
删除任务记录。

### `GET /tasks/stats`
任务统计（各状态数量、平均执行时间等）。

### `POST /tasks/{task_id}/cancel`
取消运行中的任务。

---

## 10. 错误码

| HTTP 状态码 | 说明 |
|------------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

所有错误响应遵循格式：
```json
{
  "detail": "具体错误描述"
}
```
