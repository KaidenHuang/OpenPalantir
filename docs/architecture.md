# 系统架构设计 | System Architecture Design

## 1. 总体架构

OpenPalantir 采用经典的三层架构：前端展示层 → 后端业务层 → 存储层。

```
┌─ 前端 (React 18 + TypeScript + Vite) ─────────────────────┐
│  App.tsx → 8个标签页：文档/数据库/实体/图谱/任务/模型/分析/决策 │
│  组件 → Axios → 后端 REST API                               │
└────────────────────────────────────────────────────────────┘
         ↕ HTTP (JSON)
┌─ 后端 (FastAPI + Python 3.10+) ────────────────────────────┐
│  api/routes/ (9个路由模块) → task_manager (异步任务)         │
│  cdc/ → Debezium 增量同步 (CDC 消费 + 事件处理)              │
│  manager/service 层处理业务逻辑                              │
│  Prometheus 监控 + Celery 任务队列                           │
└────────────────────────────────────────────────────────────┘
         ↕
┌─ 存储层 ──────────────────────────────────────────────────┐
│  SQLite (应用元数据) | Neo4j (图关系)                        │
│  文件系统 (data/summaries/) + Redis (缓存/消息队列/CDC事件流) │
└────────────────────────────────────────────────────────────┘
         ↕
┌─ 外部服务 ────────────────────────────────────────────────┐
│  Debezium Server (Quarkus) → 源DB binlog/WAL → Redis       │
└────────────────────────────────────────────────────────────┘
```

### 关键设计原则

- **前后端分离**：后端独立处理全部业务逻辑，前端仅负责数据展示和用户交互。脱离 UI，后端仍可独立运行。
- **异步优先**：耗时操作（文档解析、实体提取、图谱导入）全部通过 Celery 异步任务执行，避免阻塞 API 响应。
- **Agentic RAG**：决策引擎采用统一的 ReAct 循环，LLM 自主决定何时检索、调用工具、分析并给出答案。
- **统一资源标识**：所有资源（文档、数据库表）通过 `ResourceIdentifier`（`{TYPE}://{UUID}/{PATH}`）统一标识和定位。

---

## 2. 后端模块架构

### 2.1 模块依赖关系

```
main.py (FastAPI 应用入口)
  ├─ system/system_integration.py     ← CORS、日志、监控、健康检查
  ├─ config/
  │   ├─ database.py                  ← SQLite (SQLAlchemy)
  │   └─ neo4j_config.py             ← Neo4j 连接配置
  ├─ models/                          ← ORM 模型层
  │   ├─ database.py                  ← DatabaseTable
  │   ├─ model.py                     ← ModelInfo (LLM配置)
  │   ├─ source.py                    ← DocumentSource
  │   ├─ task.py                      ← Task
  │   ├─ cdc.py                       ← CdcSyncState (CDC同步状态)
  │   └─ resource_identifier.py       ← 统一资源标识符
  ├─ api/routes/                      ← REST 路由层
  │   ├─ graph.py                     ← 实体 CRUD + 搜索
  │   ├─ analysis.py                  ← 路径/社区/中心性/趋势分析
  │   ├─ database.py                  ← 外部数据库连接管理
  │   ├─ decision.py                  ← 智能决策问答
  │   ├─ model.py                     ← LLM 模型配置管理
  │   ├─ source.py                    ← 文档源管理
  │   ├─ filesystem.py                ← 文件系统浏览
  │   ├─ cdc.py                       ← CDC 增量同步管理
  │   └─ api/task.py                  ← 异步任务管理
  ├─ knowledge_graph/                 ← 图谱管理层
  │   ├─ graph_manager.py             ← Neo4j 图操作（CRUD、搜索、批量优化）
  │   ├─ graph_partition.py           ← 图谱分区
  │   └─ graph_performance.py         ← 性能优化（缓存、索引）
  ├─ analysis_engine/                 ← 图分析引擎
  │   ├─ analyzer.py                  ← NetworkX 分析（路径/社区/中心性/趋势）
  │   └─ report_generator.py          ← HTML/PDF 报告生成
  ├─ decision_engine/                 ← 决策引擎
  │   ├─ decision_kernel.py           ← 决策内核（路由到 AgenticEngine）
  │   ├─ contracts.py                 ← 数据模型（Pydantic）
  │   ├─ conversation_manager.py      ← 多轮对话管理（JSON 文件持久化）
  │   ├─ query_analyzer.py            ← 查询分析（遗留，未被直接调用）
  │   ├─ agentic/                     ← Agentic RAG 核心
  │   │   ├─ engine.py                ← AgenticEngine（ReAct 循环, MAX_TURNS=10）
  │   │   ├─ context.py               ← AgenticContext（上下文窗口管理）
  │   │   ├─ seed_retriever.py        ← SeedRetriever（jieba 分词, 级联检索）
  │   │   ├─ tools.py                 ← ToolRegistry（Skill+MCP 统一注册表）
  │   │   ├─ types.py                 ← Observation, SeedResult, AgenticResult
  │   │   └─ prompts/prompt_agentic.md← system prompt 模板
  │   ├─ retrievers/                  ← 检索器
  │   │   ├─ base_retriever.py        ← 检索器抽象基类
  │   │   ├─ document_summary_retriever.py ← 文档摘要检索
  │   │   ├─ database_summary_retriever.py ← 数据库摘要检索
  │   │   └─ graph_retriever.py       ← Neo4j 图谱检索
  │   ├─ memory/                      ← 记忆系统
  │   │   ├─ memory_manager.py        ← 短期记忆（SQLite,7天TTL）+ 长期记忆（MEMORY.md）
  │   │   └─ memory_extractor.py      ← LLM 记忆提取（单 worker 线程）
  │   ├─ tool_manager/                ← 统一的工具管理层
  │   │   ├─ tool_reasoner.py         ← 遗留（已被 AgenticEngine 替代）
  │   │   ├─ skill/                   ← 本地 Skill 源（加载 + 注册 + 执行）
  │   │   │   ├─ skill_loader.py      ← Skill 定义 + 加载
  │   │   │   └─ skill_registry.py    ← Skill 注册中心
  │   │   ├─ mcp/                     ← 外部 MCP 工具源（连接 + 管理 + 路由）
  │   │   │   ├─ mcp_client.py        ← MCP Client（stdio + HTTP）
  │   │   │   ├─ mcp_manager.py       ← 多 Server 管理 + 工具合并
  │   │   │   └─ config.py            ← MCP 配置加载
  │   │   └─ prompts/                 ← 推理 Prompt 模板
  │   └─ skills/                      ← 3 个本地 Skill 实现
  │       ├─ analyze_path/            ← 路径分析
  │       ├─ analyze_centrality/      ← 中心性分析
  │       └─ analyze_community/       ← 社区检测
  ├─ document_processing/             ← 文档解析
  │   └─ document_processor.py        ← PDF/Word/Markdown/图片解析
  ├─ entity_extraction/               ← 实体提取
  │   └─ llm_entity_enhancer.py       ← LLM 驱动的实体+关系抽取
  ├─ pageindex/                       ← 文档摘要树
  │   ├─ page_index.py                ← PDF/TXT 分层摘要生成
  │   └─ page_index_md.py            ← Markdown 摘要生成
  ├─ database_management/             ← 外部数据库管理
  │   ├─ database_manager.py          ← 连接管理 + Schema提取 + 行级导入
  │   ├─ database_service.py          ← 数据库元数据 CRUD
  │   └─ schema_annotator.py          ← LLM Schema 语义标注
  ├─ model_management/                ← LLM 模型管理
  │   ├─ model_client.py              ← 统一 LLM 调用客户端
  │   └─ model_service.py             ← 模型配置 CRUD
  ├─ cdc/                             ← Debezium 增量同步 (CDC)
  │   ├─ cdc_manager.py               ← CDC 生命周期管理 (启停/断流检测)
  │   ├─ cdc_consumer.py              ← Redis Streams 消费者线程
  │   ├─ event_processor.py           ← Debezium 事件 → Neo4j 操作
  │   └─ schema_cache.py              ← 表结构缓存 (PK/FK/列名)
  ├─ task_management/                 ← 异步任务
  │   ├─ task_manager.py              ← 任务队列 + 执行器
  │   └─ task_service.py              ← 任务状态 CRUD
  ├─ file_sources/                    ← 文件源抽象
  │   ├─ base.py                      ← 抽象基类
  │   └─ local_source.py              ← 本地文件系统实现
  ├─ utils/                           ← 工具
  │   └─ data_store.py                ← EntityDataStore (写 Neo4j)
  └─ system/                          ← 系统
      ├─ logger.py                    ← 日志（文件输出到 logs/）
      └─ system_integration.py        ← CORS/监控/健康检查
```

### 2.2 各模块职责

| 模块 | 职责 | 关键技术 |
|------|------|---------|
| `config/` | 数据库连接管理 | SQLAlchemy engine/session、Neo4j driver |
| `models/` | ORM 模型定义 | SQLAlchemy ORM、Pydantic |
| `api/routes/` | REST API 端点 | FastAPI Router、Pydantic Schema |
| `knowledge_graph/` | 图谱 CRUD、搜索、分区、缓存 | Cypher、LRU Cache |
| `analysis_engine/` | 图算法分析 | NetworkX、Louvain、scikit-learn |
| `decision_engine/` | 智能决策 | 统一 Agentic RAG（ReAct 循环）、种子检索、双层记忆、Skill+MCP 工具管理 |
| `document_processing/` | 多格式文档解析 | PyPDF2、python-docx、Pillow、pytesseract |
| `entity_extraction/` | 实体识别+关系抽取 | LLM prompt 工程、JSON 修复 |
| `pageindex/` | 文档分层摘要 | LLM、层级聚类 |
| `database_management/` | 外部DB连接+Schema分析 | SQLAlchemy dialects、LLM 标注 |
| `model_management/` | LLM 统一调用 | Ollama API、OpenAI-compatible API |
| `task_management/` | 异步任务队列 | Celery、线程池、状态追踪 |
| `cdc/` | Debezium 增量同步 | Redis Streams、XREADGROUP、事件处理 |
| `file_sources/` | 文件源抽象 | 本地文件系统、预留S3接口 |

---

### 2.3 Agentic 决策引擎架构

决策引擎的核心是 `AgenticEngine`，采用统一的 ReAct（Reason + Act）循环处理所有查询场景。

#### 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| DecisionKernel | `decision_kernel.py` | 全局入口：会话→记忆→意图判断→Agentic 循环→证据构建 |
| AgenticEngine | `agentic/engine.py` | ReAct 循环：种子检索→构建 Prompt→多轮 LLM+工具→反思→综合 |
| AgenticContext | `agentic/context.py` | 上下文窗口管理：观察截断、滚动压缩、消息重建 |
| SeedRetriever | `agentic/seed_retriever.py` | 级联种子检索：jieba 分词→摘要检索→URI 过滤图检索 |
| ToolRegistry | `agentic/tools.py` | 统一工具注册表：Skill+MCP 合并为 OpenAI function-calling 格式 |
| ConversationManager | `conversation_manager.py` | 多轮对话管理（JSON 文件持久化） |
| MemoryManager | `memory/memory_manager.py` | 双层记忆：短期（SQLite, 7 天 TTL）+ 长期（MEMORY.md） |
| MemoryExtractor | `memory/memory_extractor.py` | LLM 记忆提取（单 worker 线程串行） |

#### 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| MAX_TURNS | 10 | ReAct 循环最大轮数 |
| CONFIDENCE_THRESHOLD | 0.7 | 低于此值标记 needs_human_review |
| MAX_OBSERVATIONS_IN_CONTEXT | 6 | 上下文中保留的最大观察数 |
| OBSERVATION_MAX_CHARS | 500 | 单条观察 summary 截断长度 |
| MAX_RESULT_CHARS | 3000 | 工具结果最大字符数 |

#### 快速意图判断

`quick_check_intent()` 通过规则匹配 5 种社交意图，命中时跳过 Agentic 循环直接响应：

| 意图 | 触发词示例 | 响应 |
|------|-----------|------|
| greeting | 你好、您好、hello | 问候 + 能力介绍 |
| identity | 你是谁、你叫什么 | 身份说明 |
| capability | 你能做什么、你会什么 | 功能列表 |
| farewell | 再见、拜拜 | 告别 |
| thanks | 谢谢、感谢 | 礼貌回应 |

---

## 3. 前端组件架构

### 3.1 组件树

```
App.tsx (标签导航)
  ├─ DocumentViewer.tsx           ← 文档源管理 + 摘要树 + 实体提取触发
  ├─ DatabaseManagement.tsx       ← 外部数据库连接管理 + Schema展示
  │   └─ ERDiagram.tsx            ← ER 图可视化
  ├─ EntityManagement.tsx         ← 实体搜索、查看、编辑
  ├─ GraphVisualization.tsx       ← D3 力导向图 + 3D 图谱
  ├─ AnalysisDashboard.tsx        ← 路径/社区/中心性/趋势分析报告
  ├─ DecisionAssistant.tsx        ← 智能决策对话界面
  ├─ TaskManagement.tsx           ← 任务管理主容器
  │   ├─ TaskCreation.tsx         ← 任务创建表单
  │   ├─ TaskList.tsx             ← 任务列表（筛选/搜索）
  │   └─ TaskDetails.tsx          ← 任务详情 + 日志
  └─ ModelManagement.tsx          ← LLM 模型配置
```

### 3.2 技术栈

| 类别 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript |
| 构建 | Vite 7 |
| UI 库 | Ant Design 5 + @ant-design/icons |
| 可视化 | D3.js v7、react-force-graph-3d |
| HTTP | Axios |
| 状态管理 | React Hooks (useState/useEffect) |

---

## 4. 存储架构

### 4.1 存储分层

```
┌─ 应用元数据 (SQLite) ────────────────────────────────┐
│  model_info       ← LLM 模型配置                        │
│  document_sources ← 文档源注册信息                       │
│  database_tables  ← 外部数据库连接 + Schema 分析结果      │
│  tasks            ← 异步任务状态                         │
│  cdc_sync_states  ← CDC 增量同步状态 (binlog/WAL位点)     │
│  short_term_memories ← 短期记忆（7天TTL，关键词检索）           │
└──────────────────────────────────────────────────────┘

┌─ 图数据 (Neo4j) ────────────────────────────────────┐
│  Entity 节点     ← 所有实体（人物/组织/地点/事件/概念/DB行）│
│  Relationship 边 ← 实体间关系                           │
│  全文索引        ← 实体名称 + 类型搜索                    │
└──────────────────────────────────────────────────────┘

┌─ 文件系统 (data/summaries/) ────────────────────────┐
│  DOC/{source_uuid}/  ← 文档摘要树 JSON                  │
│  DBS/{conn_uuid}/    ← 数据库概要 JSON                  │
│  MEMORY.md           ← 长期记忆（用户偏好 + 重要决策，≤10条）   │
└──────────────────────────────────────────────────────┘

┌─ 缓存层 (Redis) ────────────────────────────────────┐
│  图谱数据缓存       ← 热数据 LRU 缓存                     │
│  Celery 消息队列    ← 异步任务 broker + result backend    │
│  CDC 事件流         ← Debezium → Redis Streams           │
│                    (key: openpalantir.{db}.{table})     │
└──────────────────────────────────────────────────────┘
```

### 4.2 实体 ID 生成规则

| 类型 | 格式 | 示例 |
|------|------|------|
| 图节点 ID | UUID v4 | `a1b2c3d4-...` |
| 文档实体 | MD5(name + type) 32位hex | `6f5902ac237...` |
| 数据库行实体 | `{表名}:{PK值}` | `users:42` |
| 关系 ID | MD5(subject + predicate + object) 32位hex | `c50d67e2ac...` |
| 资源标识符 (URI) | `{TYPE}://{UUID}/{PATH}` | `DOC://a1b2-.../novel.txt` |
| 摘要树节点 ID | 8位零填充序号 | `00000001` |
| 会话 ID | `sess_` + uuid4.hex[:12] | `sess_a1b2c3d4e5f6` |
| DocumentSource.id / Connection.id / Task.id | UUID v4，36 字符（纯 UUID，无前缀） | `d3060fed-53a1-...` |
| AnalyzedTable.uri (ORM) | `DBS://{conn_uuid}/{db_name}/{table_name}` | `DBS://c0e2.../employees/users` |

**资源标识符（ResourceIdentifier）**：URI 统一由 `ResourceIdentifier` 类（`models/resource_identifier.py`）管理，支持 `parse()` / `generate()` / `uri` / `file_safe_name`。前缀类型：

- `DOC://` — 文档源，如 `DOC://a1b2c3d4-.../重生野性时代-100章.txt`
- `DBS://` — 数据库，如 `DBS://c0e2d4ca-.../employees/departments`

实体/关系字典中的 `datasource_id` 字段、数据库概要 JSON 中的 `resource_id` 均采用此 URI 格式。

---

## 5. 中间件与横切关注点

### 5.1 请求处理流水线

```
HTTP 请求
  → CORS 中间件           (允许跨域)
  → 请求日志中间件          (记录 method/url/time)
  → Prometheus 指标收集    (counter/histogram/gauge)
  → 路由处理器              (api/routes/*)
  → 错误处理中间件          (HTTPException →JSON, Exception →500)
  → HTTP 响应
```

### 5.2 日志系统

- **输出**：`logs/backend.log`（文件）+ 控制台
- **级别**：DEBUG / INFO / WARNING / ERROR
- **格式**：`时间 - 模块名 - 级别 - 消息`
- **轮转**：按日期自动切割（`TimedRotatingFileHandler`）

### 5.3 监控端点

| 端点 | 用途 |
|------|------|
| `GET /api/system/health` | 健康检查 |
| `GET /api/system/info` | 系统信息（版本、环境） |
| `GET /api/system/config` | 当前配置（脱敏） |
| `GET /api/system/metrics` | Prometheus 指标 |

---

## 6. 部署架构

```
┌──────────────────────────────────────────┐
│  Docker Compose                           │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐     │
│  │ frontend │ │ backend │ │  neo4j  │     │
│  │  :5175   │ │  :8000  │ │  :7687  │     │
│  └─────────┘ └─────────┘ └─────────┘     │
│                  ┌─────────┐             │
│                  │  redis   │             │
│                  │  :6379   │             │
│                  └─────────┘             │
│            ┌──────────────────┐          │
│            │ Debezium Server  │          │
│            │ (Quarkus 独立进程)│          │
│            └──────────────────┘          │
└──────────────────────────────────────────┘
```

开发模式下前后端独立运行（支持热重载），生产环境通过 Docker Compose 统一编排。Debezium Server 作为独立 Java 进程运行，从源数据库捕获 binlog/WAL 变更并写入 Redis Streams。
