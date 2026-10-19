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
  │   ├─ wiki.py                      ← WikiPage（页面正文 + source_refs 锚点 + source_hash）
  │   ├─ embedding.py                 ← 实体名/别名向量（语义对齐用，非全量文档向量）
  │   ├─ memory.py                    ← 对话记忆
  │   ├─ ids.py                       ← entity_id / relationship_id 生成
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
  │   ├─ wiki.py                      ← Wiki 页面 CRUD / 生成 / 答案发布
  │   ├─ ontology.py                  ← 本体包查询/导入导出 + 治理报告
  │   └─ api/task.py                  ← 异步任务管理
  ├─ knowledge_graph/                 ← 图谱管理层
  │   ├─ entity_repository.py         ← 实体节点读写（含回收、治理聚合、get_nodes、抽样配额）
  │   ├─ relationship_repository.py   ← 关系边读写（「语义行→受控写入」唯一归一化缝）
  │   ├─ viz_snapshot.py              ← 可视化快照（图数据五步读路径）
  │   ├─ graph_topology.py            ← 图级拓扑（分区/压缩/元图）
  │   ├─ recycle.py                   ← 来源回收组合入口（先边后实体）
  │   ├─ source_scope.py              ← 两级来源的 Cypher 片段（归属/回收唯一出口）
  │   ├─ alias_cache.py               ← 实体别名缓存
  │   ├─ graph_partition.py           ← 图谱分区
  │   └─ graph_performance.py         ← 性能优化（缓存、索引）
  ├─ analysis_engine/                 ← 图分析引擎
  │   ├─ analyzer.py                  ← NetworkX 分析（路径/社区/中心性/趋势）
  │   └─ report_generator.py          ← HTML/PDF 报告生成
  ├─ ontology/                        ← 受控本体层
  │   ├─ registry.py                  ← 本体包加载/校验/合并、社区包导入导出、版本计数
  │   ├─ governance.py                ← 治理报告：词表使用/非法类型/定义域值域/游离实体/别名候选
  │   ├─ predicates.py                ← 归一化 → relationship_id → Cypher 类型名
  │   ├─ prompt.py                    ← 实体/关系枚举注入 prompt（抽取与标注共用，按注册表版本缓存）
  │   ├─ types.py                     ← ObjectType/LinkType/OntologyPack 数据类
  │   └─ packs/                       ← 内置 YAML 本体包（general/finance/medical/workforce）
  │                                     社区/自定义包在 data/ontology_packs/（同名覆盖内置）
  ├─ wiki/                            ← LLM Wiki 内容层
  │   ├─ wiki_service.py              ← 页面 CRUD + 生成编排 + 答案发布（SQLite）
  │   ├─ page_generator.py            ← 文档页 / 跨文档主题页生成
  │   ├─ entity_generator.py          ← 图谱实体页生成（实体档案 → 页面）
  │   └─ prompts/                     ← 页面生成 prompt 模板
  ├─ decision_engine/                 ← 决策引擎
  │   ├─ decision_kernel.py           ← 决策内核（路由到 AgenticEngine）
  │   ├─ contracts.py                 ← 数据模型（Pydantic）
  │   ├─ conversation_manager.py      ← 多轮对话管理（JSON 文件持久化）
  │   ├─ agentic/                     ← Agentic RAG 核心
  │   │   ├─ engine.py                ← AgenticEngine（ReAct 循环, MAX_TURNS=15）
  │   │   ├─ context.py               ← AgenticContext（上下文窗口管理）
  │   │   ├─ seed_retriever.py        ← SeedRetriever（jieba 分词, 级联检索）
  │   │   ├─ tools.py                 ← ToolRegistry（Skill+MCP 统一注册表）
  │   │   ├─ types.py                 ← Observation, SeedResult, AgenticResult
  │   │   └─ prompts/prompt_agentic.md← system prompt 模板
  │   ├─ retrievers/                  ← 检索器
  │   │   ├─ summary_retriever.py     ← 摘要检索（文档 + 数据库 JSON，共享打分 helper）
  │   │   └─ embedding_utils.py       ← 向量召回 + hybrid_rank
  │   ├─ memory/                      ← 记忆系统
  │   │   ├─ memory_manager.py        ← 短期记忆（SQLite,7天TTL）+ 长期记忆（SQLite）
  │   │   └─ memory_extractor.py      ← LLM 记忆提取（单 worker 线程）
  │   ├─ tool_manager/                ← 统一的工具管理层
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
  │   ├─ document_processor.py        ← PDF/Word/Markdown/图片解析
  │   └─ summary_generator.py         ← 摘要编排 + 落盘 + 源文件内容指纹 + DOC:// 来源 URI
  ├─ source_management/               ← 文档源处理与刷新
  │   ├─ source_service.py            ← 摘要分块抽取（实体/关系入库）
  │   └─ refresh_service.py           ← 内容失效传播：判定→先生成→后回收→Wiki 刷新
  ├─ entity_extraction/               ← 实体提取
  │   └─ llm_entity_enhancer.py       ← LLM 驱动的实体+关系抽取
  ├─ content_extraction/              ← 内容提取（纯解析，无 LLM）
  │   ├─ models.py                    ← ExtractedDocument / Section 数据契约
  │   └─ converters/                  ← pdf(pymupdf4llm)/docx/md/txt 转换器注册表
  ├─ content_summarization/           ← 摘要生成（唯一的 LLM 环节）
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
  │   ├─ task_manager.py              ← 任务队列 + 执行器（按 task_type 分发 handler；唯一落库缝）
  │   └─ handlers/                    ← schema_analyze / schema_import / cdc_start /
  │                                     document_summary / document_refresh / wiki_generate
  ├─ file_sources/                    ← 文件源抽象
  │   ├─ base.py                      ← 抽象基类
  │   ├─ local_source.py              ← 本地文件系统实现
  │   └─ watcher.py                   ← 文档监听：轮询指纹，派发 document_refresh 任务
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
| `knowledge_graph/` | 图谱 CRUD、搜索、分区、缓存 | Cypher（按 LinkType 类型化边）、LRU Cache |
| `analysis_engine/` | 图算法分析 | NetworkX、Louvain、scikit-learn |
| `ontology/` | 受控本体注册表、谓词归一化与治理 | YAML 本体包、词表校验、prompt 注入、只读聚合治理报告、包导入导出 |
| `wiki/` | LLM Wiki 页面生成与编辑 | 摘要树聚合、跨文档主题聚类、实体档案拼装 |
| `decision_engine/` | 智能决策 | 统一 Agentic RAG（ReAct 循环）、种子检索、双层记忆、Skill+MCP 工具管理 |
| `document_processing/` | 多格式文档解析 + 摘要落盘与内容指纹 | PyPDF2、python-docx、Pillow、pytesseract |
| `content_extraction/` | 按格式提取结构/正文/页码 → 统一中间格式 | pymupdf4llm、python-docx、Markdown 章节解析（无 LLM） |
| `source_management/` | 摘要→图谱抽取、文档内容失效传播 | 指纹比对、按佐证回收、Wiki 下游刷新 |
| `entity_extraction/` | 实体识别+关系抽取 | LLM prompt 工程、JSON 修复 |
| `content_summarization/` | 摘要树生成（叶子 summary / 父 prefix_summary + 页码区间） | LLM 节点摘要 |
| `database_management/` | 外部DB连接+Schema分析 | SQLAlchemy dialects、LLM 标注 |
| `model_management/` | LLM 统一调用 | Ollama API、OpenAI-compatible API |
| `task_management/` | 异步任务队列 | Celery、线程池、状态追踪 |
| `cdc/` | Debezium 增量同步 | Redis Streams、XREADGROUP、事件处理 |
| `file_sources/` | 文件源抽象 + 文档变更监听 | 本地文件系统、预留S3接口、指纹轮询派发刷新任务 |

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
| MemoryManager | `memory/memory_manager.py` | 双层记忆：短期（SQLite, 7 天 TTL）+ 长期（SQLite, 去重合并/提炼覆写） |
| MemoryExtractor | `memory/memory_extractor.py` | LLM 记忆提取（单 worker 线程串行） |

#### 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| MAX_TURNS | 15 | ReAct 循环最大轮数 |
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
│  wiki_pages       ← Wiki 页面正文 + 引用锚点 + source_hash │
│  embedding_cache  ← 实体名/别名向量（语义对齐，非全量文档向量）│
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
│  （长期记忆已迁入 SQLite long_term_memories 表）        │
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
| 文档实体 | MD5(name) 32位hex | `6f5902ac237...` |
| 数据库行实体 | `{表名}:{PK值}` | `users:42` |
| 关系 ID | MD5(subject + predicate + object) 32位hex，predicate 为**受控 LinkType key**（归一化先于算 ID）；词表外兜底「其他」时 ID 改用**原始谓词**参与计算（防同对实体不同语义的兜底边互覆，见 docs/ontology-guide.md） | `c50d67e2ac...` |
| 资源标识符 (URI) | `{TYPE}://{UUID}/{PATH}` | `DOC://a1b2-.../novel.txt` |
| 摘要树节点 ID | 8位零填充序号 | `00000001` |
| 会话 ID | `sess_` + uuid4.hex[:12] | `sess_a1b2c3d4e5f6` |
| DocumentSource.id / Connection.id / Task.id | UUID v4，36 字符（纯 UUID，无前缀） | `d3060fed-53a1-...` |
| AnalyzedTable.uri (ORM) | `DBS://{conn_uuid}/{db_name}/{table_name}` | `DBS://c0e2.../employees/users` |

**资源标识符（ResourceIdentifier）**：URI 统一由 `ResourceIdentifier` 类（`models/resource_identifier.py`）管理，支持 `parse()` / `generate()` / `uri` / `file_safe_name`。前缀类型：

- `DOC://` — 文档源，如 `DOC://a1b2c3d4-.../重生野性时代-100章.txt`
- `DBS://` — 数据库，如 `DBS://c0e2d4ca-.../employees/departments`
- `ENT://` — 图谱实体（Wiki 实体页的 datasource），如 `ENT://6f5902ac.../张三`

实体/关系字典中的 `datasource_id` 字段、数据库概要 JSON 中的 `resource_id` 均采用此 URI 格式。

### 4.3 来源归属与内容失效

图谱节点与边都携带**两级来源**属性：

| 属性 | 含义 | 用途 |
|------|------|------|
| `datasource` | 主来源（首次写入的来源 URI） | 展示、全文检索过滤 |
| `datasources` | 全部佐证来源列表 | **归属判定与回收的唯一依据** |

同一实体/关系可由多个来源佐证（`entity_id`=MD5(name)、`relationship_id`=MD5(s_p_o) 都与来源无关），因此按来源过滤或回收必须走 `knowledge_graph/source_scope.py` 的 Cypher 片段（`match_prefix` / `match_any_prefix` / `union_sources` / `strip_prefix`），否则重跑一个来源会连带删掉其他来源的佐证。回收入口是 `knowledge_graph/recycle.py 的 recycle_datasource(prefix)`：先摘边佐证、再摘实体佐证，**佐证列表清空才删除**。

文档侧的失效判定不建状态表：摘要 JSON 内的 `content_hash` 就是生成当时源文件的 MD5，`source_management/refresh_service.py` 比对它即可得出 `changed` / `removed` / 未变更；下游 Wiki 页各自的 `source_hash` 幂等，上游一变下游自动重算。

```
文档变更 ──▶ file_sources/watcher.py（DOC_WATCH_ENABLED=1 轮询）
             或 POST /api/sources/{id}/refresh
                 │
                 ▼  task_type = document_refresh
   ① 重新生成摘要并落盘（LLM 风险步骤放最前，失败则旧数据完好）
   ② recycle_datasource(DOC://{source_id}/{文件})  ← 只摘本来源佐证
   ③ 重新抽取实体关系入库
   ④ Wiki 传播：文档页重生成 → 主题页/实体页按指纹重算 → prune_orphans
```

数据库侧的增量仍由 CDC 负责（`DBS://` 前缀回收 + Debezium 事件），两者对称覆盖「文档 + 数据库」两类来源的自动刷新。

### 4.4 本体包分层与治理报告

```
backend/ontology/packs/*.yaml     ← 内置包（general 为基底，其余域包在其上扩展）
backend/data/ontology_packs/*.yaml ← 社区/自定义包（运行时数据，同名覆盖内置）
        │
        ▼  OntologyRegistry._pack_files()：同名以用户包为准，加载即 build_views()
   域视图 = general ⊕ extends 链 ⊕ 本包（同 key 覆盖，新 key 追加）
        │
        ▼
   /api/ontology/packs  POST 导入（persist=true 落用户包目录）、GET 导出 YAML
```

- **导入即校验**：社区包与内置包走同一条 `validate_pack` 链（重复 key、`parent` 不存在、`domain`/`range` 类型不存在、`inverse` 未定义 → 直接 400 拒绝，不入库）。
- **extends 扩展链**：包可声明 `extends: <包名>` 挂在某个域包之上、只写增量（例：`examples/ontology/rd_efficiency.yaml` 挂 `workforce`）。校验的基底是**父包视图**，故扩展包能直接引用父包定义的类型；`extends` 目标缺失或成环 → 整体拒绝，注册表状态与 `version` 均不变。
- **版本驱动缓存失效**：`OntologyRegistry.version` 在每次 `register_pack` / `reload` 成功后自增；`ontology/prompt.py` 的缓存键是 `(version, domain)`，因此新导入的谓词立刻进入抽取与标注 prompt，无需重启进程。被拒绝的包不改版本号，避免无谓重算。
- **只读治理**：`ontology/governance.py` 聚合图谱现状与词表定义，输出兜底占比、词表外谓词、未使用词表项、非法实体类型、定义域/值域违规、游离/占位实体、无来源佐证产出、别名候选排行；`GET /api/ontology/report` 一份 JSON 看全貌，`findings` 是可读的治理结论。治理查询全部是只读聚合，不写图谱。

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
