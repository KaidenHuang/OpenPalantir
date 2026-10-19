# API 接口文档 | API Reference

## 基础信息

- **Base URL**: `http://localhost:8000`
- **Content-Type**: `application/json`
- **API 文档 (Swagger)**: `http://localhost:8000/docs`
- **API 文档 (ReDoc)**: `http://localhost:8000/redoc`
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
  "domain": "general",
  "session_id": "sess_abc123",
  "scope": { "datasource": "DOC://uuid/手册.pdf", "node_id": "00000007", "title": "第3章" }
}
```

`scope` 可选：把提问限定在某篇文档 / 某个摘要树节点（Wiki 页「就本页提问」入口即携带此参数），检索命中会回落到该作用域内。

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

**Response 附加字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `decision_mode` | string | 固定值 `"agentic_rag"` |
| `response_type` | string | `"normal"`（Agentic 循环）或 `"simple"`（快速意图） |
| `confidence` | float | 0.0–1.0 置信度评分 |
| `needs_human_review` | bool | 置信度 < 0.7 时为 true |
| `metadata.total_turns` | int | ReAct 循环实际轮数 |
| `metadata.total_tool_calls` | int | 工具调用总次数 |
| `metadata.total_time_ms` | float | 总耗时（毫秒） |
| `metadata.observations_count` | int | 观察记录条数 |

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
  "database": "mydb",
  "domain": "workforce"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tables` | string[] | 否 | 仅分析这些表 |
| `ignore_tables` | string[] | 否 | 跳过的表名模式 |
| `database` | string | 否 | 指定库名 |
| `domain` | string | 否 | 本体域包名，决定 LLM 标注使用的实体/关系词表，默认 `general` |

### `POST /connections/{connection_id}/import`
图谱导入（阶段2，创建异步任务）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `batch_size` | int | 否 | 批处理大小，默认 5000 |
| `row_limit` | int | 否 | 单表行数上限，0=不限制（默认 1000） |
| `auto_start_cdc` | bool | 否 | 导入完成后自动启动 CDC 增量同步，默认 false |

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

### `POST /api/sources/{source_id}/summarize`
为源内某个文件生成摘要树（异步任务 `document_generate_summary`），并记录当时的 `content_hash`（源文件 MD5，失效判定的指纹）。

**Request Body**: `{"file": "章节/红楼梦.txt"}` → `{"task_id", "message"}`；文件缺失/路径越界/类型不支持 → 400。

### `POST /api/sources/{source_id}/extract`
从已生成的摘要树抽取实体与关系写入图谱（谓词按本体词表归一化）。

### `POST /api/sources/{source_id}/refresh`
重跑一篇文档：重新生成摘要 → 回收本来源的图谱佐证 → 重新抽取 → Wiki 下游刷新（异步任务 `document_refresh`，顺序保证 LLM 失败时旧数据完好）。

**Request Body**:
```json
{ "file": "章节/红楼梦.txt", "force": false, "domain": "general", "parallelism": 8 }
```
→ `{"task_id", "message"}`。

### `GET /api/sources/{source_id}/stale`
列出该源中内容已变更或已删除的文档（`changed` / `removed`），供前端提示重新生成。

**Response**: `{"status", "source_id", "stale": [{source_id, file, status, ...}]}`

### `GET /api/sources/{source_id}/summary?file=`
获取指定文件已生成的摘要树。

### `GET /api/sources/{source_id}/browse?prefix=`
浏览文档源目录（列出文件与子目录）。

### `GET /api/sources/{source_id}/entities?file=`
获取该文件已抽取的实体与关系。

### `POST /api/sources/{source_id}/restore`
恢复已软删除的文档源。

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

## 10. CDC 增量同步接口 | CDC

所有接口前缀：`/api/cdc`

### `POST /{connection_id}/start`
启动增量同步。启动前自动执行断流检测，若发现事件间隙则返回 `gap_detected` 状态并建议重新全量导入。

**Request Body**:
```json
{
  "database_name": "mydb",
  "topic_prefix": "openpalantir"
}
```

**Response** (正常启动):
```json
{
  "status": "running",
  "message": "CDC 增量同步已启动"
}
```

**Response** (检测到断流):
```json
{
  "status": "gap_detected",
  "message": "Redis Stream 中存在事件间隙...",
  "suggestion": "请先执行全量导入重建基线，再启动增量同步"
}
```

### `POST /{connection_id}/stop`
停止增量同步。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `database_name` | string | 是 | 数据库名（Query 参数） |

### `POST /{connection_id}/pause`
暂停增量同步（停止并标记状态为 `paused`）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `database_name` | string | 是 | 数据库名（Query 参数） |

### `GET /{connection_id}/status`
查询单个连接的同步状态。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `database_name` | string | 是 | 数据库名（Query 参数） |

**Response**:
```json
{
  "connection_id": "uuid",
  "database_name": "mydb",
  "status": "running",
  "events_processed": 1523,
  "last_event_ts": 1717200000000,
  "last_error": null
}
```

### `GET /statuses`
查询所有连接的 CDC 同步状态列表。

---

## 11. Wiki 接口 | Wiki

所有接口前缀：`/api/wiki`。页面 kind 为 `document`（文档页）/ `topic`（跨文档主题页）/ `entity`（图谱实体页）/ `answer`（问答沉淀页）。

### `GET /pages?kind=&status=`
列出页面。`status` 取 `draft` / `published`。

### `GET /pages/{page_id}`
页面详情：Markdown 正文 + `source_refs` 引用锚点（`node_id` 指向摘要树节点）。

### `PUT /pages/{page_id}`
编辑页面（人工编辑是内容资产的一等公民）。

**Request Body**:
```json
{ "title": "可选新标题", "content": "新的 Markdown 正文" }
```

### `POST /pages/{page_id}/status`
切换发布状态，`status` 仅接受 `draft` / `published`，否则 400。

### `DELETE /pages/{page_id}`
删除页面。

### `POST /publish_answer`
把一次问答的高质量回答带引用发布为 Wiki 页（经人工确认后回流内容）。

**Request Body**:
```json
{
  "question": "X 的定义是什么？",
  "answer": "……",
  "citations": [{"node_id": "00000007", "datasource": "DOC://...", "title": "……"}]
}
```
`answer` 为空 → 400。

### `POST /generate`
创建 Wiki 生成异步任务，返回 `{"task_id": ...}`（进度经 `/api/task/{task_id}` 查询）。

**Request Body**（三选一，前两者优先）:
```json
{ "datasource": "DOC://uuid/章节.pdf", "entity_id": "…", "scope": "all|topics|entities" }
```
`scope` 非法值 → 400。

---

## 12. 本体接口 | Ontology

所有接口前缀：`/api/ontology`。本体包是 YAML 文本，`domain` 参数即包名。

### `GET /domains`
列出全部域包及规模：`{name, description, object_type_count, link_type_count}`。

### `GET /packs/{domain}`
导出该域包 YAML（`{"domain", "yaml"}`），导出的文本可原样回导入。域不存在 → 404。

### `POST /packs`
导入社区/自定义本体包。

**Request Body**:
```json
{ "yaml": "name: logistics\nobject_types: [...]\nlink_types: [...]", "persist": true }
```
- 校验不过（重复 key、`parent`/`domain`/`range` 类型不存在、`inverse` 未定义）→ 400，且不注册、不影响运行中词表。
- `persist=true` 落盘 `backend/data/ontology_packs/{name}.yaml`，重启后仍在；基底包 `general` 禁止覆盖 → 400。
- `yaml` 缺失或空白 → 400。
- 成功后注册表版本自增，抽取与标注 prompt 的新词表**立即生效**，无需重启。

### `POST /reload`
从磁盘重新加载 `ontology/packs/` 与 `data/ontology_packs/`（手工改包文件后调用），返回最新 `domains`。

### `GET /report?domain=&limit=&with_pack=`
治理报告（只读聚合，不写图谱）：

| 字段 | 内容 |
|------|------|
| `domains` | 当前生效的域包列表 |
| `vocabulary` | 边总量、按谓词分布、兜底「其他」数量与占比、从未使用的词表项、词表外谓词 |
| `object_types` | 实体类型分布、非法类型、未使用类型 |
| `domain_range_violations` | 违反定义域/值域的 (谓词, 主语类型, 宾语类型) 组合及允许范围 |
| `structure_issues` | 游离实体、占位实体、无来源佐证的实体/边计数 |
| `alias_candidates` | 同一受控谓词下的原始谓词变体排行（提示该补哪些别名） |
| `findings` | 可读的治理结论列表 |
| `pack` | 仅当 `with_pack=true` 且给了 `domain` 时返回该包 YAML |

`limit` 范围 1~500（默认 50）。

---

## 13. 错误码

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
