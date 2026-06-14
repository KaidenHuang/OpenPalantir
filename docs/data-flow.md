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

决策引擎是系统最高层的能力，整合图谱+数据库+文档三类信息源，为用户提供自然语言问答。

```
[用户提问] → [POST /api/decision/ask]
                          ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 1: QueryAnalyzer 查询分析                                │
  │  ├─ LLM 解析用户意图 (intent)                                  │
  │  ├─ 识别问题域 (domain)                                       │
  │  ├─ 提取关键实体 (entities)                                    │
  │  ├─ 拆分子问题 (sub_questions)                                 │
  │  └─ 确定检索策略 (required_sources: [graph|database|document]) │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 2: PluginRegistry 路由到领域插件                           │
  │  ├─ 根据 domain 查找注册的插件 (如 workforce_plugin)             │
  │  └─ 若无匹配 → 使用通用插件                                     │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 3: RetrievalOrchestrator 多源检索                        │
  │  ├─ GraphRetriever       → Cypher 查询图谱实体+关系             │
  │  ├─ DatabaseRetriever    → SQL 查询源数据库                     │
  │  └─ DocumentRetriever    → 搜索文档摘要树                        │
  │ 输出: RawEvidence[{source_type, content, relevance_score}]    │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 4: EvidenceFusion 证据融合排序                             │
  │  ├─ 基于 relevance_score 排序                                   │
  │  ├─ 去重 (同源相似内容合并)                                      │
  │  └─ 生成 citation 引用标记                                      │
  │ 输出: EvidenceItem[{evidence_id, summary, citation}]         │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 5: ContextBuilder 构建 LLM 上下文                          │
  │  ├─ 组装 System Prompt (角色 + 指令)                            │
  │  ├─ 填入检索证据 (EvidenceItem 序列化)                           │
  │  ├─ 填入对话历史 (ConversationTurn[])                          │
  │  └─ token 数量估算 (避免超出 LLM 上下文窗口)                       │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 6: LLMReasoner 推理                                      │
  │  ├─ 调用 LLM API 生成结构化回答                                  │
  │  └─ 解析为 DecisionAnswer {summary, options, recommendation,  │
  │                           work_orders[]}                     │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 7: ConversationManager 会话管理                            │
  │  ├─ 记录本轮对话 (ConversationTurn)                              │
  │  ├─ 更新会话历史                                                │
  │  └─ session_id 关联多轮对话                                     │
  └─────────────────────────────────────────────────────────────┘
                          ↓
  [返回 DecisionResponse 给前端]
```

### 插件化架构

```
plugin_registry.py
  ├─ register(name, plugin_class)
  └─ resolve(domain) → plugin_instance

plugins/
  ├─ base_decision_plugin.py   ← 抽象基类 (定义 run(request) 接口)
  └─ workforce_plugin.py       ← 人力资源领域插件 (示例)
```

扩展新领域只需：
1. 继承 `BaseDecisionPlugin`
2. 实现 `run(request)` 方法
3. 调用 `plugin_registry.register("domain_name", MyPlugin)`

---

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
