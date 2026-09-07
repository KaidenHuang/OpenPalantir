# 业务逻辑与数据流 | Business Logic & Data Flow

本文档描述 OpenPalantir 的核心业务流程和数据流转。

---

## 1. 文档分析流程

这是系统最核心的流程，将非结构化文档转化为结构化知识图谱。

```
[用户选择文档源] → [POST /api/sources/{id}/process] → 创建异步任务
                                                          ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ 阶段1：文档解析                                              │
  │ DocumentProcessor.process_document(path)                     │
  │  ├─ .txt  → 直接读取文本                                     │
  │  ├─ .pdf  → PyPDF2 逐页提取                                  │
  │  ├─ .docx → python-docx 段落提取                             │
  │  ├─ .md   → markdown 解析                                    │
  │  └─ .jpg/.png → pytesseract OCR 识别                         │
  │ 输出: {content: "全文文本", metadata: {file_type, word_count}} │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ 阶段2：摘要树生成 (PageIndex)                                  │
  │ PageIndex 将长文本分层处理：                                    │
  │  ├─ 文本分段 → 逐段 LLM 摘要                                   │
  │  ├─ 摘要聚类 → 形成层级树结构                                   │
  │  ├─ 标题检测 → 识别章节标题                                     │
  │  └─ 保存到 data/summaries/DOC/{uuid}/                        │
  │ 输出: 多层级摘要树 JSON (node_id: 00000001 → 00000002 → ...)    │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ 阶段3：实体提取与关系抽取                                       │
  │ LLMEntityEnhancer.extract_entities_and_relationships(text)    │
  │  ├─ 可选启用模型 → 调用 LLM API                                │
  │  ├─ Prompt: 识别 人物/组织/地点/事件/概念 实体                   │
  │  ├─ 同时提取实体间关系: {subject, predicate, object}             │
  │  ├─ JSON 响应自动修复（处理 LLM 输出格式问题）                     │
  │  └─ 输出: entities[{name, type, confidence}] + relationships[] │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ 阶段4：写入图谱                                               │
  │ EntityDataStore.save_all(entities, relationships)            │
  │  ├─ entity_id = MD5(name + type)                             │
  │  ├─ relationship_id = MD5(subject + predicate + object)       │
  │  ├─ 批量 MERGE 到 Neo4j (使用 Cypher UNWIND)                   │
  │  └─ 创建/更新全文索引                                          │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  [Neo4j 图谱就绪] → 可供分析引擎和决策引擎查询
```

### 长文本处理策略

- 文本按长度自动分块（chunk_size 可配置）
- 每块独立调用 LLM 提取实体
- 结果去重合并（基于 entity_id 唯一性）
- 分块间关系通过实体名称模糊匹配补全

---

## 2. 数据库导入流程（两阶段）

### 2.1 阶段1：Schema 分析

```
[用户填写连接配置] → [POST /api/database/connections] → 保存连接信息到 SQLite
                                                          ↓
[选择目标数据库] → [POST /api/database/connections/{id}/analyze]
                                                          ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ 1. DatabaseDialect 连接源数据库                                │
  │    ├─ MySQL: pymysql → information_schema                    │
  │    ├─ PostgreSQL: psycopg2 → pg_catalog                      │
  │    └─ SQLite: sqlite3 → sqlite_master                        │
  │ 2. 提取 Schema: 表名 →列名 →数据类型 →主键 →外键                │
  │ 3. SchemaAnnotator (LLM) 标注每列的业务语义                     │
  │    ├─ Prompt: "分析以下表结构的业务含义..."                       │
  │    └─ 输出: 每列的中文描述 + 实体类型推断                         │
  │ 4. 保存到 DatabaseTable (SQLite) + 生成概要 JSON                │
  │    └─ 路径: data/summaries/DBS/{conn_uuid}/{db_name}.json     │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  [Schema 分析结果展示在 DatabaseManagement 页面]
```

### 2.2 阶段2：图谱导入

```
[用户选择目标表] → [POST /api/database/connections/{id}/import] → 创建异步任务
                                                                    ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ 1. 读取本地 Schema (从 SQLite 缓存的 DatabaseTable)            │
  │ 2. 连接源 DB，逐表查询 (SELECT * LIMIT 1000)                   │
  │ 3. 每行构建实体:                                               │
  │    ├─ name: {表名}:{主键值1}:{主键值2}...                       │
  │    ├─ type: 从 SchemaAnnotator 标注的类型或默认"其他"             │
  │    ├─ attributes: 所有列值 (JSON)                              │
  │    └─ datasource_id: DBS://{uuid}/{db}/{table}               │
  │ 4. 外键匹配构建关系:                                            │
  │    ├─ 表内自引用: FK 指向同一表 → 行间关系                        │
  │    ├─ 跨表引用: FK 指向其他表 → 跨表行间关系                       │
  │    └─ 关系类型: "RELATES_TO" (默认) 或从 FK 名称推断              │
  │ 5. EntityDataStore.save_all() 批量写入 Neo4j                   │
  │    └─ 每个实体最多 50 个跨表关系对 (MAX_CROSS_PRODUCT_PAIRS)      │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  [数据库行数据作为图谱节点就绪]
```

### 实体命名规则

| 场景 | 格式 | 示例 |
|------|------|------|
| 单主键表 | `{表名}:{PK值}` | `users:42` |
| 复合主键表 | `{表名}:{PK1}:{PK2}` | `order_items:1001:5` |
| 无主键表 | 使用首列作为代理键 | `logs:2024-01-01` |

### 2.3 阶段3：增量同步（CDC，基于 Debezium）

全量导入完成后，可启动 Debezium 增量同步，实时捕获源数据库变更并同步到图谱。

```
[全量导入完成] → [POST /api/cdc/{connection_id}/start]
                              ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ 前置检查: check_stream_continuity()                          │
  │  ├─ 比对 Redis Stream 最旧消息 ID 与上次消费位点              │
  │  ├─ 有间隙 → 返回 gap_detected，建议重新全量导入              │
  │  └─ 无间隙 → 继续启动                                        │
  └─────────────────────────────────────────────────────────────┘
                              ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ Debezium Server (Quarkus 独立进程)                           │
  │  ├─ snapshot.mode=never: 跳过初始快照，仅消费增量变更         │
  │  ├─ 从全量导入前捕获的 binlog/WAL 位点开始监听                │
  │  │   - MySQL: SHOW MASTER STATUS → binlog file + position    │
  │  │   - PostgreSQL: pg_current_wal_lsn() → WAL LSN           │
  │  ├─ 变更事件写入 Redis Streams                               │
  │  │   key: openpalantir.{db_name}.{table_name}               │
  │  └─ 支持连接器: MySQL, PostgreSQL, Oracle, SQL Server        │
  └─────────────────────────────────────────────────────────────┘
                              ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ CDCConsumer (后台线程, 每个连接一个)                          │
  │  ├─ XREADGROUP 消费 Redis Streams (阻塞读取, 3s超时)         │
  │  ├─ 断点续传: 加载 last_message_id → 从上次位点继续           │
  │  ├─ 指数退避: Redis 连接错误时最大重试 30s                    │
  │  └─ 每条消息处理后立即 ACK (操作幂等)                         │
  └─────────────────────────────────────────────────────────────┘
                              ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ EventProcessor (Debezium 事件 → Neo4j 操作)                  │
  │  ├─ 解析 Debezium 2.x 信封格式 (schema.payload 解包)         │
  │  ├─ 事件类型映射:                                             │
  │  │   c (CREATE) → MERGE 实体 (upsert)                        │
  │  │   r (READ/SNAPSHOT) → MERGE 实体                          │
  │  │   u (UPDATE) → MERGE 实体 (更新属性)                       │
  │  │   d (DELETE) → DELETE 实体 + 关联关系                      │
  │  ├─ 实体 ID 一致性:                                          │
  │  │   {表名}:{PK值1}:{PK值2} → MD5 哈希                       │
  │  │   与全量导入使用相同方案，确保命中同一 Neo4j 节点           │
  │  ├─ 外键关系差量同步:                                         │
  │  │   1. 查询现有 RELATED_TO 边 (source='cdc_fk')             │
  │  │   2. 计算当前行应有的 FK 关系集合                          │
  │  │   3. 删除不再存在的关系 (stale)                            │
  │  │   4. 创建新增的关系                                        │
  │  └─ 占位节点: FK 目标未见时创建空节点，后续 INSERT 会 MERGE    │
  └─────────────────────────────────────────────────────────────┘
                              ↓
  [Neo4j 图谱实时同步] → 增量更新与全量导入数据无缝融合
```

#### 生命周期管理

```
全量导入 (auto_start_cdc=true)
    → CDC 启动 (running)
    → 暂停 (pause → paused)
    → 恢复 (start → running)
    → 停止 (stop → stopped)

应用关闭时:
    main.py shutdown hook → cdc_manager.shutdown_all()
    → 逐个停止所有 consumer 线程 (30s 超时 join)
    → 持久化最终消费位点到 SQLite
```

#### SchemaCache 初始化

CDCConsumer 启动时从 SQLite 加载 Schema 元数据（由阶段1 Schema 分析填充）：
- 表列表、列名、数据类型
- 主键列（无主键时回退到首列）
- 外键定义（用于关系同步）
- 生成 Redis Stream key: `{topic_prefix}.{database_name}.{table_name}`

---

## 3. 决策引擎流程

决策引擎整合图谱+数据库+文档三类信息源，通过统一的 AgenticEngine ReAct 循环提供自然语言问答。

### 3.1 决策主流程

`DecisionKernel.run()` 是全局入口，编排会话→记忆→意图判断→Agentic 循环→证据构建的完整流程：

```
[POST /api/decision/ask]
       ↓
┌─ 1. 会话管理 ─────────────────────────────────────────────┐
│  ConversationManager.get_or_create(session_id, domain)    │
│  ├─ 已有会话 → 返回                                        │
│  └─ 新会话 → 生成 sess_{uuid4.hex[:12]} 并持久化到 JSON     │
└──────────────────────────────────────────────────────────┘
       ↓
┌─ 2. 记忆注入 ─────────────────────────────────────────────┐
│  短期记忆：SQLite 关键词匹配 + 时间衰减，上限 5 条           │
│  长期记忆：MEMORY.md（偏好 + 重要决策，≤10 条）              │
│  └─ hash 去重：相同内容不重复注入                             │
└──────────────────────────────────────────────────────────┘
       ↓
┌─ 3. 快速意图判断 (quick_check_intent) ────────────────────┐
│  规则匹配 5 种社交意图：                                     │
│  ├─ greeting (你好/您好/hello)                              │
│  ├─ identity (你是谁/你叫什么)                               │
│  ├─ capability (你能做什么/你会什么)                          │
│  ├─ farewell (再见/拜拜)                                    │
│  └─ thanks (谢谢/感谢)                                      │
│  命中 → 直接返回简单响应，跳过 Agentic 循环                   │
│  未命中 → 进入 AgenticEngine.run()                          │
└──────────────────────────────────────────────────────────┘
       ↓
┌─ 4. AgenticEngine.run() (详见 §3.2) ─────────────────────┐
│  种子检索 → 构建 Prompt → ReAct 循环 → 返回 AgenticResult   │
└──────────────────────────────────────────────────────────┘
       ↓
┌─ 5. 会话保存 + 记忆提取 ──────────────────────────────────┐
│  ConversationManager.add_turn() 记录本轮                    │
│  MemoryExtractor.extract_async() 异步提取记忆候选            │
│  ├─ 单 worker 线程串行处理                                   │
│  └─ 超限时 LLM 提炼合并                                     │
└──────────────────────────────────────────────────────────┘
       ↓
┌─ 6. 证据构建 ────────────────────────────────────────────┐
│  AgenticEngine.build_evidence(observations)               │
│  └─ 将工具观察记录转换为 EvidenceItem 列表                   │
└──────────────────────────────────────────────────────────┘
       ↓
[返回 DecisionResponse]
```

### 3.2 AgenticEngine ReAct 循环

`AgenticEngine`（`decision_engine/agentic/engine.py`）是系统的核心推理引擎，一个 ReAct 循环处理所有场景。

#### Phase A: 种子检索

```
SeedRetriever.retrieve(question)
  ├─ jieba 中文分词 + 停用词过滤
  ├─ 文档摘要检索 (data/summaries/DOC/) — 关键词匹配 JSON 文件
  ├─ 数据库摘要检索 (data/summaries/DBS/) — 关键词匹配 JSON 文件
  ├─ 提取 datasource_uri → 过滤 Neo4j 图检索（仅检索相关数据源）
  └─ 组装 SeedResult 作为初始上下文
```

#### Phase B: 构建 System Prompt

```
_build_system_prompt(ctx, tool_defs)
  ├─ 角色定义 + 四步工作流指令（思考→行动→反思→综合）
  ├─ 可用工具描述（Skill + MCP，OpenAI function-calling 格式）
  ├─ 种子上下文（Phase A 的 SeedResult）
  ├─ 对话历史（最近 3 轮 ConversationTurn）
  └─ 记忆注入（短期 + 长期）
```

#### Phase C: ReAct 循环（MAX_TURNS=10）

```
LOOP (最多 10 轮):
  1. LLM call_with_tools(messages, tools)
     ├─ 本地模型 → Ollama /api/chat
     └─ 云端模型 → OpenAI-compatible /chat/completions

  2. 无 tool_calls → LLM 认为信息充足
     └─ 解析 JSON → DecisionAnswer → 返回 AgenticResult

  3. 有 tool_calls → 逐个执行
     └─ ToolRegistry.execute(name, params)
        ├─ Skill → skill_registry.execute()
        └─ MCP   → mcp_manager.execute()
     └─ 结果追加为 Observation + tool message

  4. 上下文压缩（每 3 条观察触发）
     └─ AgenticContext.compress(messages)

  5. 反思提示（每 2 轮插入）
     └─ "当前信息是否充足？不足则继续调用工具。"

达到最大轮数 → 强制综合（置信度上限 0.5）
```

#### 置信度评估

- 0.0–1.0 量化置信度
- 低于 0.7（CONFIDENCE_THRESHOLD）自动标记 `needs_human_review=true`
- 强制综合时置信度上限 0.5
- 元评论检测安全网：检测 LLM 输出描述性文字而非实际数据

### 3.3 上下文管理策略

`AgenticContext`（`decision_engine/agentic/context.py`）管理 LLM 上下文窗口，防止超出 token 限制：

| 策略 | 触发条件 | 行为 |
|------|---------|------|
| 观察截断 | 单条 Observation 生成时 | summary 限 500 字符 |
| 滚动压缩 | observations ≥ 3 条 | 最早 3 条压缩为 running_summary |
| 消息重建 | 压缩后 | 保留最近 2 组完整 assistant+tool 消息，其余折叠 |

### 3.4 内置 Skill 体系（3 个）

每个 Skill 是一个目录，包含 `SKILL.md`（YAML frontmatter）和 `executor.py`（`execute(params) -> dict`），由 `SkillLoader` 自动加载并转换为 OpenAI function-calling 格式。

| Skill | 功能 |
|-------|------|
| `analyze_path` | 实体间最短路径分析 |
| `analyze_centrality` | 中心性分析（度/介数/紧密度/PageRank/特征向量） |
| `analyze_community` | 社区检测（Louvain 算法） |

### 3.5 外部 MCP 工具

通过配置 `config/mcp_servers.json` 连接外部 MCP Server，其工具自动纳入 AgenticEngine 的工具列表。

```json
{
  "servers": [
    {"name": "filesystem", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]},
    {"name": "web_search", "transport": "http",
     "url": "http://search-service:9000/mcp"}
  ]
}
```

工具命名约定：`{server}__{tool}`（如 `filesystem__read_file`），避免跨 Server 冲突。

### 3.6 双层记忆系统

```
┌─ 短期记忆 (SQLite) ──────────────────────────────────────┐
│  表: short_term_memories                                  │
│  TTL: 7 天自动过期                                        │
│  检索: 关键词匹配 + 域过滤 + 时间衰减 + 重要性排序           │
│  上限: 每次查询 5 条                                       │
└──────────────────────────────────────────────────────────┘

┌─ 长期记忆 (MEMORY.md) ───────────────────────────────────┐
│  两类: preferences (用户偏好) + decisions (重要决策)        │
│  上限: 10 条 / 300 字                                     │
│  注入: hash 去重，相同内容不重复注入                         │
└──────────────────────────────────────────────────────────┘

┌─ 记忆提取 (MemoryExtractor) ─────────────────────────────┐
│  触发: 每轮对话结束后异步执行                               │
│  方式: LLM 从对话中提取记忆候选                             │
│  超限: 调用 LLM 提炼合并                                   │
│  执行: 单 worker 线程串行处理                               │
└──────────────────────────────────────────────────────────┘
```

## 4. 异步任务管理流程

所有耗时操作都通过任务管理系统异步执行。

```
[API 接收请求] → 创建 Task(id=uuid4, type=..., status=pending)
                          ↓
              task_manager.submit(task_id, func, *args)
                          ↓
              ┌─ Celery Worker 执行 ─┐
              │  status → running    │
              │  执行 func(*args)    │ ← 实时输出日志到 task.log
              │  成功 → completed     │
              │  失败 → failed       │
              └─────────────────────┘
                          ↓
              [前端轮询 GET /api/task/{id} 获取状态]
```

### 任务类型

| 类型 | 触发接口 | 执行内容 |
|------|---------|---------|
| `document_process` | `POST /api/sources/{id}/process` | 文档解析+摘要+实体提取+图谱写入 |
| `database_import` | `POST /api/database/connections/{id}/import` | Schema 分析 (P1) / 行级导入 (P2) + 可选 CDC 启动 |
| `entity_extraction` | 文档处理子任务 | 对指定文本块提取实体和关系 |
| `analysis_report` | `POST /api/analysis/report` | 生成 HTML/PDF 分析报告 |

### 任务状态机

```
pending → running → completed
                ↘ failed (可重试)
```

---

## 5. LLM 调用流程

```
[配置模型 (ModelManagement)] → 保存到 SQLite (model_info 表)
                                      ↓
[任意模块需要 LLM] → ModelService.get_enabled_model()
                                      ↓
                  ModelClient(model_config)
                    ├─ type=local  → POST http://localhost:11434/api/chat (Ollama)
                    └─ type=cloud  → POST {api_url}/v1/chat/completions (OpenAI-compatible)
                                      ↓
                  自动重试 (max_retries=3, exponential backoff)
                  自动 JSON 修复 (提取 {...} 片段, 修复截断/转义错误)
                                      ↓
                  [返回解析结果]
```
