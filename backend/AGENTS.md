***
description: OpenPalantir 后端模块指南 — 中文
alwaysApply: true
-----------------
# OpenPalantir 后端模块指南

始终使用简体中文回复。

## 项目概述

OpenPalantir 后端是数据分析与知识图谱构建系统的服务端，基于 FastAPI 框架。核心职责包括：

- **文档处理**：解析 PDF/Word/PPT/MD，提取文本与结构化内容
- **实体关系抽取**：基于 LLM 从文档中提取实体与关系
- **知识图谱管理**：Neo4j CRUD、分区、索引与性能优化
- **图谱分析**：路径分析、社区发现、中心性计算、趋势分析
- **决策引擎**：基于 ReAct 循环的智能问答与决策推理，支持多 Agent 协作
- **数据库导入**：从 MySQL/PostgreSQL/SQLite 导入 Schema 与数据到图谱
- **CDC 增量同步**：基于 Debezium Server + Redis Streams 的数据库增量变更同步
- **MCP 工具集成**：通过 MCP Server 扩展 Agentic 引擎能力

## 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI + uvicorn |
| ORM | SQLAlchemy 2.0 |
| 图数据库 | Neo4j 4.4（`neo4j` Python driver） |
| 缓存 / 消息 | Redis（RESP2 协议，`protocol=2`） |
| 任务队列 | 内置线程调度（`task_manager`，早期不需要独立 broker） |
| 文档处理 | PyPDF2、python-docx、python-pptx、Pillow、markdown、pymupdf4llm（PDF→Markdown 结构提取） |
| LLM 调用 | ModelClient（Ollama API 兼容，支持本地/云端模型） |
| 图计算 | NetworkX、scikit-learn、python-louvain |
| OCR | pytesseract |
| 监控 | Prometheus Client |
| 测试 | pytest、pytest-asyncio、pytest-cov |

## 后端架构与数据流

```
┌─ FastAPI 应用 ────────────────────────────────────┐
│  main.py                                           │
│    ├─ 创建 SQLite 表（Base.metadata.create_all）    │
│    ├─ 初始化 Neo4j Schema（约束 + 索引）            │
│    ├─ 初始化默认模型记录                           │
│    ├─ 系统集成（日志/错误/指标/中间件/路由）        │
│    └─ 注册路由（/api/ 下 11 个 router）           │
│                                                    │
│  WebSocket（/ws/tasks）                             │
│    ↕ 任务进度实时推送                               │
│                                                    │
│  各 service 层 ← REST API 端点 ← 前端（Axios）     │
└────────────────────────────────────────────────────┘
         ↕
┌─ 存储 ────────────────────────────────────────────┐
│  SQLite（backend/data/sqlite/database.db）         │
│    ├─ 任务状态 / 模型记录 / 数据源                 │
│    ├─ CDC 同步状态 / 数据库连接信息                │
│    └─ 对话记忆                                     │
│  Neo4j（图数据）                                    │
│    ├─ 实体（:Entity {id, name, type, ...}）        │
│    └─ 关系（MERGE 幂等写入）                       │
│  Redis（CDC Redis Streams + 图谱快照缓存）         │
└────────────────────────────────────────────────────┘
         ↕
┌─ 外部服务 ────────────────────────────────────────┐
│  Debezium Server → 源 DB binlog/WAL → Redis Stream │
│  Ollama API（本地 LLM 推理）                       │
│  MCP Servers（外部工具扩展）                       │
└────────────────────────────────────────────────────┘
```

### 启动流程（main.py）

1. 创建 SQLite 表（ORM 自动建表）
2. 初始化 Neo4j Schema（`CREATE CONSTRAINT IF NOT EXISTS`）
3. 初始化默认模型记录（`init_models()`）
4. 初始化系统集成（日志、错误处理器、中间件、指标、路由）
5. 后台线程：byname 回填（`backfill_byname()`）
6. 注册 11 个路由组（含 `/api/wiki`、`/api/ontology`）
7. `DOC_WATCH_ENABLED=1` 时启动文档轮询监听（`pipeline/watcher.py`），shutdown 时与 CDC Consumer 一同停止

## 五阶段组件

数据处理链路按「注册 → 提取 → 摘要 → 抽取 → Wiki」五个阶段组织，每个阶段一个顶层组件目录，
内部再分 `document/`（文档侧）与 `database/`（数据库侧）两个实现；阶段之间只经组件对外接口耦合。

| 阶段 | 组件 | 对外入口 |
|------|------|----------|
| ① 注册数据源 | `source_registry/` | `document_source_registry`（注册/软删/恢复/浏览）、`database_source_registry`（连接 CRUD/测连/库列表） |
| ② 内容提取 | `content_extraction/` | `document/`：`extract_content()` → `ExtractedDocument`（章节树 + 页码）；`database/`：`extract_schema_for_connection()` → 表/字段/主外键/**视图** |
| ③ 摘要生成 | `summary_generation/` | `document/`：`summarize_document()` + `store`（落盘/指纹/URI）；`database/`：`annotator`（LLM 标注）+ `build`/`store`（库表概要） |
| ④ 实体抽取 | `entity_extraction/` | `document/`：`DocumentExtractionService`（批次 LLM 抽实体/关系/属性）；`database/`：`importer`（行实体/属性表/外键关系）+ `row_reader`（keyset 分页） |
| ⑤ Wiki 生成 | `wiki_generation/` | `service.wiki_service`（页面 CRUD/编排/答案发布）、`document/`（文档页+主题页）、`entity/`（实体页） |

跨阶段的两件事不在某个组件里，放 `pipeline/` 薄层：
- `pipeline/refresh.py`：内容失效传播（摘要 → 抽取新代佐证 → 旧代回收 → Wiki 刷新）
- `pipeline/watcher.py`：轮询内容指纹派发 `document_refresh`（与只管数据库的 CDC 对称）

## 模块结构

```
backend/
├── main.py                        # 应用入口
│
├── api/                           # REST API 层
│   ├── routes/
│   │   ├── graph.py               # 图谱 CRUD / 搜索 / 属性
│   │   ├── analysis.py            # 图谱分析（路径/社区/中心性/趋势）
│   │   ├── decision.py            # 决策引擎对话（scope + 引用）
│   │   ├── database.py            # 数据库连接与导入
│   │   ├── cdc.py                 # CDC 配置与启停
│   │   ├── source.py              # 数据源管理 + summarize/refresh/stale
│   │   ├── wiki.py                # Wiki 页面 CRUD / 生成 / 答案发布
│   │   ├── ontology.py            # 本体包导入导出 + 治理报告 + 中文词表接口
│   │   ├── model.py               # LLM 模型配置
│   │   └── filesystem.py          # 文件系统操作
│   └── task.py                    # 异步任务状态查询
│
├── config/                        # 系统配置
│   ├── database.py                # SQLAlchemy 引擎与会话（WAL + busy_timeout）
│   ├── neo4j_config.py            # Neo4j 连接与 Schema 初始化
│   └── decision_engine.yaml       # 决策引擎参数配置
│
├── decision_engine/               # 决策推理引擎
│   ├── agentic/                   # ReAct 循环核心
│   │   ├── engine.py              # 主循环（max_turns=15）
│   │   ├── context.py             # 上下文管理与自动压缩
│   │   ├── seed_retriever.py      # 种子检索（混合召回入口）
│   │   ├── tools.py               # 内置工具（含摘要树导航：先看树、再按 node_id 取正文）
│   │   ├── types.py               # 类型定义
│   │   └── multi_agent.py         # 多 Agent 协作
│   ├── memory/                    # 对话记忆
│   │   ├── memory_manager.py
│   │   └── memory_extractor.py
│   ├── retrievers/                # 检索器
│   │   ├── summary_retriever.py   # 摘要检索（文档 + 数据库 JSON，共享打分 helper）
│   │   └── embedding_utils.py     # 向量召回 + hybrid_rank（embedding 缓存于 embedding_cache）
│   ├── skills/                    # 内置技能
│   │   ├── analyze_path/          # 路径分析
│   │   ├── analyze_community/     # 社区分析
│   │   └── analyze_centrality/    # 中心性分析
│   ├── tool_manager/              # 工具管理
│   │   ├── mcp/                   # MCP Server 集成
│   │   │   ├── mcp_client.py      # MCP 客户端
│   │   │   ├── mcp_manager.py     # MCP 管理器
│   │   │   ├── config.py          # MCP 配置
│   │   │   └── types.py
│   │   └── skill/                 # 技能加载与注册
│   │       ├── skill_loader.py
│   │       └── skill_registry.py
│   ├── conversation_manager.py    # 会话管理
│   ├── decision_kernel.py         # 决策内核
│   ├── contracts.py               # 数据契约
│   └── config.py                  # 引擎配置
│
├── knowledge_graph/               # 知识图谱操作
│   ├── entity_repository.py       # 实体存储（两级来源、回收、get_nodes、抽样配额公式）
│   ├── relationship_repository.py # 关系存储（受控边类型写入；「语义行→受控写入」唯一缝）
│   ├── viz_snapshot.py            # 可视化快照（/api/graph/graph-data 五步读路径）
│   ├── graph_topology.py          # 图级拓扑操作（分区/压缩/元图，共享构图 helper）
│   ├── recycle.py                 # 来源回收组合入口（先边佐证后实体佐证）
│   ├── source_scope.py            # 来源归属/回收的 Cypher 片段唯一出口
│   ├── graph_partition.py         # 图谱分区算法（Louvain 等，分析引擎共用）
│   ├── graph_performance.py       # 性能优化（索引/Redis 快照缓存）
│   ├── entity_data_store.py       # 语义行装配（原 utils/data_store.py）：实体/关系字段与端点 id
│   └── alias_cache.py             # 别名缓存
│
├── analysis_engine/               # 图谱分析引擎
│   ├── analyzer.py                # 分析主入口
│   └── report_generator.py        # 报告生成
│
├── source_registry/               # ① 注册数据源
│   ├── document/
│   │   ├── registry.py            # 文档源注册/软删/恢复/路径解析（产出判定以回调注入）
│   │   └── scanner.py             # 源目录浏览（前端文件选择）
│   └── database/
│       └── registry.py            # 连接 CRUD / 测连 / 库列表 / 产出判定合并
│
├── content_extraction/            # ② 内容提取（纯解析，无 LLM）
│   ├── document/
│   │   ├── models.py              # ExtractedDocument / Section 数据契约
│   │   ├── md_parser.py           # Markdown 章节解析（PDF/MD 共用建树核心）
│   │   └── converters/            # 格式注册表：pdf/docx/pptx/md/txt（新格式在此登记）
│   └── database/
│       ├── connector.py           # SQLAlchemy 引擎构建（含裸引擎，仅列举库/测连用）
│       ├── dialects.py            # 各方言 Schema/视图 SQL + SchemaExtractor 编排
│       ├── schema_reader.py       # extract_schema_for_connection（配置 → 引擎 → 提取）
│       └── store.py               # SchemaStore：表/字段/外键/推断关系 + 已分析库记录
│
├── summary_generation/            # ③ 摘要生成（唯一的 LLM 环节）
│   ├── document/
│   │   ├── summarizer.py          # ExtractedDocument → 摘要树（叶子 summary，父 prefix_summary）
│   │   ├── tree_utils.py          # node_id / 子树正文聚合 / 页码区间
│   │   ├── llm.py                 # ModelClient 调用 + token 估算
│   │   ├── store.py               # 摘要落盘/指纹/DOC:// 来源 URI/遍历（原 summary_generator）
│   │   └── prompts/               # 节点摘要 / 文档描述模板
│   └── database/
│       ├── annotator.py           # 库/表/字段业务标注（词表并入统一本体）
│       ├── build.py               # Schema → 概要结构（表/键/视图）
│       └── store.py               # 概要 JSON 落盘（data/summaries/DBS/{conn}/{db}.json）
│
├── entity_extraction/             # ④ 实体抽取
│   ├── document/
│   │   ├── service.py             # DocumentExtractionService：批次 LLM 抽取 + 去重 + 落库
│   │   ├── chunker.py             # 摘要树 → 正文批次 + 跨批次去重（含属性合并）
│   │   ├── extractor.py           # LLMEntityEnhancer（取实体/关系/实体属性）
│   │   └── prompts/               # 抽取 prompt（实体/关系/属性枚举由本体注册表注入）
│   └── database/
│       ├── importer.py            # 行实体/属性表/外键关系构建（原 import_helpers）
│       └── row_reader.py          # 表行读取：keyset / LIMIT-OFFSET 两套分页 + 标识符白名单
│
├── wiki_generation/               # ⑤ Wiki 生成
│   ├── document/
│   │   ├── generator.py           # 文档页 / 跨文档主题页
│   │   └── prompts/
│   ├── entity/
│   │   ├── generator.py           # 图谱实体页（实体档案 → 页面）
│   │   └── prompts/
│   └── service.py                 # 页面 CRUD + 生成编排 + 答案发布 + 孤儿页清理
│                                   # 预留 database/ 扩展位（本轮不含库表页面）
│
├── pipeline/                      # 跨阶段调度薄层
│   ├── refresh.py                 # 内容失效传播（摘要→抽取新代→旧代回收→Wiki）
│   └── watcher.py                 # 轮询内容指纹派发 document_refresh
│
├── ontology/                      # 受控本体层
│   ├── registry.py                # 包加载/校验/extends 链/视图合并、社区包导入导出、version 计数
│   ├── governance.py              # 治理报告：词表使用/非法类型/定义域值域/游离实体/别名候选
│   ├── predicates.py              # 谓词归一化 → relationship_id → Cypher 类型名
│   ├── prompt.py                  # 类型/属性枚举注入 prompt（按 (version, domain) 缓存）
│   ├── types.py                   # ObjectType / LinkType / PropertyType / OntologyPack
│   └── packs/                     # 内置包 general/finance/medical/workforce
│                                   # 社区包在 data/ontology_packs/（域包同名覆盖内置、基底包 general 除外；可 extends 内置域只写增量）
│
├── cdc/                           # CDC 增量同步
│   ├── cdc_manager.py             # CDC 管理器（生命周期）
│   ├── cdc_consumer.py            # Redis Stream 消费
│   ├── event_processor.py         # Debezium 事件 → Neo4j
│   ├── debezium_config.py         # Debezium 配置渲染
│   └── schema_cache.py            # Schema 缓存
│   —— 详细指南见 cdc/AGENTS.md
│
├── task_management/               # 异步任务管理
│   ├── task_manager.py            # 任务调度器（HANDLERS 契约注册表分发；唯一落库缝）
│   └── handlers/                  # 任务处理器（base.py = task_type/payload 显式契约）
│       ├── base.py                # 处理器基类
│       ├── document_summary.py    # 文档摘要
│       ├── document_refresh.py    # 文档失效重跑（摘要→回收→重抽取→Wiki）
│       ├── wiki_generate.py       # Wiki 页面批量生成
│       ├── schema_analyze.py      # Schema 分析
│       ├── schema_import.py       # Schema 导入
│       └── cdc_start.py           # CDC 启动
│
├── model_management/              # LLM 模型管理
│   ├── model_client.py            # Ollama API 客户端
│   ├── model_service.py           # 模型服务
│   └── __init__.py                # 模型类型定义
│
├── models/                        # ORM / 数据模型
│   ├── model.py                   # 模型记录
│   ├── task.py                    # 任务状态
│   ├── database.py                # 数据库连接 / 已分析库状态
│   ├── source.py                  # 数据源
│   ├── cdc.py                     # CDC 状态
│   ├── wiki.py                    # WikiPage（正文 + 引用锚点 + source_hash）
│   ├── embedding.py               # EmbeddingCache（实体名/别名向量，非全量文档向量）
│   ├── memory.py                  # 对话记忆
│   ├── ids.py                     # ID 生成（entity_id / relationship_id）
│   ├── graph_models.py            # 图数据 Pydantic 模型
│   └── resource_identifier.py     # 资源标识符（DOC:// / DBS:// / ENT://）
│
├── system/                        # 系统基础设施
│   ├── logger.py                  # 日志系统
│   ├── error_handlers.py          # 全局错误处理器
│   ├── middleware.py               # 中间件
│   ├── metrics.py                 # Prometheus 指标
│   ├── routes.py                  # 系统路由
│   └── system_integration.py      # 系统集成入口
│
├── websocket/                     # WebSocket 通信
│   └── task_ws.py                 # 任务进度 WebSocket（/ws/tasks）
│
└── utils/                         # 工具函数
    ├── json_utils.py              # JSON 序列化
    └── path_guard.py              # 路径安全（safe_join：源内相对路径越界拒绝）
```

> 图谱写入侧（`knowledge_graph/`，含 `entity_data_store.py` 语义行装配）见上面「知识图谱」段；
> 它不属于五阶段中的任何一环，而是所有抽取侧共用的落库缝。

## 开发命令

```bash
# 安装依赖
cd backend && pip install -r requirements.txt

# 启动开发服务器（热重载）
uvicorn main:app --reload --port 8000

# 单元测试（无需后端运行）
cd tests
python test_memory.py
python test_skill.py
python test_mcp_integration.py

# 集成测试（后端需运行在 localhost:8000）
cd tests && pytest

# 抽取质量基线（模型管理里没有可用模型时自动 skip）
cd backend && python -m pytest ../tests/test_extraction_quality.py -v -s

# 清理 DB（Schema 变更后删除重启自动重建）
del backend\data\sqlite\database.db
# 进程锁 DB 时先清理
taskkill /F /IM python.exe
```

> 完整安装与构建命令见 `docs/development-guide.md` 与 `INSTALL.md`。

## 配置说明

### `.env` 配置项（`backend/.env`）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j 连接地址 |
| `NEO4J_USER` | `neo4j` | Neo4j 用户名 |
| `NEO4J_PASSWORD` | — | Neo4j 密码 |
| `REDIS_HOST` | `localhost` | Redis 主机 |
| `REDIS_PORT` | `6379` | Redis 端口 |
| `REDIS_DB` | `0` | Redis 数据库编号 |
| `API_AUTH_KEY` | — | 设置后所有 `/api` 路由要求 `X-API-Key` 请求头；不设置则仅本机开发模式 |
| `APP_ENV` | `development` | 运行环境 |
| `CORS_ORIGINS` | `http://localhost:5175` | 前端地址 |
| `BATCH_SIZE` | `100` | 批处理大小 |
| `CACHE_TTL` | `3600` | 缓存 TTL |
| `DATABASE_URL` | `sqlite:///data/sqlite/database.db` | SQLite 路径 |
| `DOC_WATCH_ENABLED` | `0` | 文档轮询监听开关（`1` 时启动 `pipeline/watcher.py`，比对 `content_hash` 派发 `document_refresh`） |
| `DOC_WATCH_INTERVAL` | `60` | 轮询间隔秒数（下限 5） |

### 数据库说明

- **SQLite**：元数据存储，路径为 `backend/data/sqlite/database.db`（相对于 `backend/` 目录）
- **Neo4j**：图数据存储，`:Entity` 标签的 `id` 属性有唯一约束
- **Redis**：需使用 RESP2 协议（`redis.Redis(protocol=2)`），服务端版本 5.0.14

### Neo4j Schema 初始化

启动时自动执行：
```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE
```

## API 路由总览

| 前缀 | 文件 | 功能 |
|------|------|------|
| `/api/graph` | `api/routes/graph.py` | 图谱 CRUD、搜索、属性管理 |
| `/api/analysis` | `api/routes/analysis.py` | 路径/社区/中心性/趋势分析 |
| `/api/model` | `api/routes/model.py` | LLM 模型配置 |
| `/api/task` | `api/task.py` | 异步任务状态 |
| `/api/decision` | `api/routes/decision.py` | 决策引擎对话（可选 `scope` 限定作用域 + 返回引用） |
| `/api/filesystem` | `api/routes/filesystem.py` | 文件系统操作 |
| `/api/wiki` | `api/routes/wiki.py` | Wiki 页面 CRUD / 生成 / 答案发布 |
| `/api/ontology` | `api/routes/ontology.py` | 本体包查询与导入导出、中文词表（`/vocabulary`）、治理报告 |
| `/api` | `api/routes/source.py` | 数据源管理（含 `summarize` / `refresh` / `stale`） |
| — | `api/routes/database.py` | 数据库连接与导入 |
| — | `api/routes/cdc.py` | CDC 增量同步配置 |
| `/ws/tasks` | `websocket/task_ws.py` | 任务进度 WebSocket |

## 关键设计约束

- **前后端分离**：后端独立处理全部业务逻辑，前端仅调用接口与展示
- **资源 ID**：URI 统一为 `{TYPE}://{UUID}/{路径}`（`DOC://`、`DBS://`），由 `models/resource_identifier.py` 管理
- **实体/关系 ID**：`entity_id = MD5(name)`，`relationship_id = MD5({subject}_{predicate}_{object})`，由 `models/ids.py` 生成
- **单一存储**：实体与关系写入 Neo4j，通过全文索引实现搜索
- **受控本体**：边类型取自 `ontology/packs/` 的 LinkType 词表；谓词归一化**先于** `relationship_id` 计算，未命中兜底为「其他」并记 `raw_predicate`。域视图 = `general ⊕ extends 链 ⊕ 本包`，社区包可 `extends: workforce` 只写增量（校验相对父视图，故可引用父包类型）。社区包在 `backend/data/ontology_packs/`（域包同名覆盖内置，基底包 general 不可覆盖），导入即校验，`registry.version` 变更即令 prompt 缓存失效
- **本体显示名分层**：包与类型各有可选 `display_name`（中文名），存储与 Cypher 永远用 key；界面经 `GET /api/ontology/vocabulary`（`registry.vocabulary()`，同 key 以基底包显示名为准）、Wiki 实体页经 `registry.object_type_label()` 只在**显示时**翻译，未知 key 原样返回。`source_hash`/ID 仍按 key 计算，改中文名不触发重生成
- **两级来源**：节点/边同时带 `datasource`（主来源，展示与检索用，纯 URI）与 `datasources`（全部佐证条目，代际场景为 `URI@content_hash`）；按来源过滤与回收必须走 `knowledge_graph/source_scope.py` 的片段，`recycle_datasource` 只摘本来源佐证、清空才删；`keep_hash`（代际回收）保留本来源新代佐证
- **内容失效传播**：摘要 JSON 的 `content_hash`（源文件 MD5）是文档指纹；刷新顺序是先生成摘要 → **抽取（新代佐证 `URI@content_hash`）** → 旧代回收（`keep_hash` 保留新代）→ 再刷新 Wiki —— 抽取/落库失败时旧图谱数据完好，成功才摘除旧代
- **Wiki 页面**：`wiki_pages` 存 Markdown 正文 + `source_refs`（node_id 锚点），kind 为 document/topic/entity/answer；按 `source_hash` 幂等，LLM 不可用降级为确定性拼装
- **LLM 集成**：经 `model_management/model_client.py` 统一调用 Ollama API
- **MCP 工具**：通过 `config/mcp_servers.json` 配置外部 MCP Server，自动纳入 AgenticEngine ReAct 循环
- **Agentic 引擎**：统一 ReAct 循环（max_turns=15，可在 `decision_engine.yaml` 调整），种子检索提供初始上下文，上下文窗口自动压缩
- **CDC 增量同步**：基于 Debezium Server + Redis Streams，设计与操作详见 `cdc/AGENTS.md`
- **设计优先**：当前阶段不考虑向后兼容，设计不合理之处直接改掉或删除

## 测试指南

- **测试框架**：pytest + pytest-asyncio + pytest-cov
- **单元测试**（无需后端运行）：
  ```bash
  cd tests
  python test_memory.py
  python test_skill.py
  python test_mcp_integration.py
  ```
- **集成测试**（需 `localhost:8000` 运行后端）：
  ```bash
  cd tests && pytest
  ```
- **抽取质量基线**：`tests/golden/extraction_v1.json` 人工标注 `examples/docs` 三篇文档，
  `tests/test_extraction_quality.py` 产出实体/关系召回与越界率报告（写入 `logs/extraction_quality.json`）；
  模型管理里没有可用模型时评测用例整体 skip。改抽取 prompt 或本体包后先看这一层。
- **测试规范**：Bash 命令不含 `#` 内联注释；避免 `cd` + 输出重定向的写法

## 调试与运维

- **日志**：写入 `./logs/backend.log`（从项目根目录）—— 后端报错首先检查该文件
- **数据库重置**：删除 `backend/data/sqlite/database.db` 重启即可自动重建
- **进程清理**：`taskkill /F /IM python.exe`（Windows），或用 `Get-Process` 定位
- **CDC 调试**：
  - 日志关键词：`[CDCManager]`、`[CDCConsumer]`、`[EventProcessor]`
  - 重配步骤：`stop-debezium.ps1` → 删 offset → `start-debezium.ps1`
  - Debezium 是独立 Java 进程，不受 `uvicorn --reload` 影响
- **Schema 变更**：删除 `database.db` 重启（不做数据迁移）

## 参考文档

| 文档 | 内容 |
|------|------|
| [docs/architecture.md](../docs/architecture.md) | 系统架构、后端模块结构、ID 规范 |
| [docs/data-flow.md](../docs/data-flow.md) | 文档分析/数据库导入/CDC/决策引擎业务流程 |
| [docs/cdc-setup.md](../docs/cdc-setup.md) | CDC 增量同步：新环境配置与启动顺序 |
| [docs/development-guide.md](../docs/development-guide.md) | 开发环境搭建与代码规范 |
| [cdc/AGENTS.md](cdc/AGENTS.md) | CDC 模块详细设计指南 |
| [INSTALL.md](../INSTALL.md) | 安装部署与环境变量参考 |