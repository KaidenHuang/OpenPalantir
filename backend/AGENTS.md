***
description: OpenPalantir 后端模块指南 — 中文
alwaysApply: true
-----------------
# OpenPalantir 后端模块指南

始终使用简体中文回复。

## 项目概述

OpenPalantir 后端是数据分析与知识图谱构建系统的服务端，基于 FastAPI 框架。核心职责包括：

- **文档处理**：解析 PDF/Word/MD/图片，提取文本与结构化内容
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
| 任务队列 | Celery + Redis broker |
| 文档处理 | PyPDF2、python-docx、Pillow、markdown、magic-pdf（MinerU） |
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
│    ├─ 初始化默认模型记录 & 实体类型                  │
│    ├─ 系统集成（日志/错误/指标/中间件/路由）        │
│    └─ 注册路由（/api/ 下 10 个 router）           │
│                                                    │
│  WebSocket（/ws/task/{task_id}）                    │
│    ↕ 任务进度实时推送                               │
│                                                    │
│  各 service 层 ← REST API 端点 ← 前端（Axios）     │
└────────────────────────────────────────────────────┘
         ↕
┌─ 存储 ────────────────────────────────────────────┐
│  SQLite（backend/data/sqlite/database.db）         │
│    ├─ 任务状态 / 模型记录 / 数据源 / 实体类型      │
│    ├─ CDC 同步状态 / 数据库连接信息                │
│    └─ 对话记忆                                     │
│  Neo4j（图数据）                                    │
│    ├─ 实体（:Entity {id, name, type, ...}）        │
│    └─ 关系（MERGE 幂等写入）                       │
│  Redis（CDC Redis Streams + Celery broker）        │
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
4. 初始化默认实体类型（`init_entity_types()`）
5. 初始化系统集成（日志、错误处理器、中间件、指标、路由）
6. 后台线程：byname 回填（`backfill_byname()`）
7. 注册 10 个路由组

## 模块结构

```
backend/
├── main.py                        # 应用入口
│
├── api/                           # REST API 层
│   ├── routes/
│   │   ├── graph.py               # 图谱 CRUD / 搜索 / 属性
│   │   ├── analysis.py            # 图谱分析（路径/社区/中心性/趋势）
│   │   ├── decision.py            # 决策引擎对话
│   │   ├── database.py            # 数据库连接与导入
│   │   ├── cdc.py                 # CDC 配置与启停
│   │   ├── source.py              # 数据源管理
│   │   ├── model.py               # LLM 模型配置
│   │   ├── entity_types.py        # 实体类型
│   │   └── filesystem.py          # 文件系统操作
│   └── task.py                    # 异步任务状态查询
│
├── config/                        # 系统配置
│   ├── database.py                # SQLAlchemy 引擎与会话
│   ├── neo4j_config.py            # Neo4j 连接与 Schema 初始化
│   ├── celery_config.py           # Celery 任务队列
│   └── backup.py                  # 备份配置
│
├── decision_engine/               # 决策推理引擎
│   ├── agentic/                   # ReAct 循环核心
│   │   ├── engine.py              # 主循环（MAX_TURNS=10）
│   │   ├── context.py             # 上下文管理与自动压缩
│   │   ├── seed_retriever.py      # 种子检索
│   │   ├── tools.py               # 内置工具
│   │   ├── types.py               # 类型定义
│   │   └── multi_agent.py         # 多 Agent 协作
│   ├── memory/                    # 对话记忆
│   │   ├── memory_manager.py
│   │   └── memory_extractor.py
│   ├── retrievers/                # 检索器
│   │   ├── base_retriever.py
│   │   ├── graph_retriever.py
│   │   ├── document_summary_retriever.py
│   │   └── database_summary_retriever.py
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
│   ├── pipeline.py                # 对话管线
│   ├── conversation_manager.py    # 会话管理
│   ├── decision_kernel.py         # 决策内核
│   ├── contracts.py               # 数据契约
│   └── config.py                  # 引擎配置
│
├── knowledge_graph/               # 知识图谱操作
│   ├── graph_manager.py           # 图谱 CRUD 主入口
│   ├── entity_repository.py       # 实体存储
│   ├── relationship_repository.py # 关系存储
│   ├── graph_partition.py         # 图谱分区
│   ├── graph_performance.py       # 性能优化
│   └── alias_cache.py             # 别名缓存
│
├── analysis_engine/               # 图谱分析引擎
│   ├── analyzer.py                # 分析主入口
│   └── report_generator.py        # 报告生成
│
├── document_processing/           # 文档处理
│   ├── document_processor.py      # 统一文档解析入口
│   └── mineru_adapter.py          # MinerU PDF 解析适配
│
├── entity_extraction/             # 实体关系抽取
│   └── llm_entity_enhancer.py     # LLM 实体增强
│
├── database_management/           # 数据库 Schema 管理
│   ├── database_manager.py        # 数据库连接管理
│   ├── database_service.py        # 数据库导入服务
│   ├── schema_annotator.py        # Schema 标注
│   └── import_helpers.py          # 导入辅助
│
├── cdc/                           # CDC 增量同步
│   ├── cdc_manager.py             # CDC 管理器（生命周期）
│   ├── cdc_consumer.py            # Redis Stream 消费
│   ├── event_processor.py         # Debezium 事件 → Neo4j
│   ├── debezium_config.py         # Debezium 配置渲染
│   ├── schema_cache.py            # Schema 缓存
│   └── offset_store.py            # offset 序列化（预留）
│   —— 详细指南见 cdc/CLAUDE.md
│
├── task_management/               # 异步任务管理
│   ├── task_manager.py            # 任务调度器
│   ├── task_service.py            # 任务服务
│   └── handlers/                  # 任务处理器
│       ├── base.py                # 处理器基类
│       ├── document_summary.py    # 文档摘要
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
│   ├── database.py                # 数据库连接 / 实体类型
│   ├── source.py                  # 数据源
│   ├── cdc.py                     # CDC 状态
│   ├── memory.py                  # 对话记忆
│   ├── ids.py                     # ID 生成（entity_id / relationship_id）
│   ├── graph_models.py            # 图数据 Pydantic 模型
│   └── resource_identifier.py     # 资源标识符（DOC:// / DBS://）
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
│   └── task_ws.py                 # 任务进度 WebSocket
│
├── source_management/             # 数据源管理
│   └── source_service.py          # 源服务
│
├── file_sources/                  # 文件源抽象
│   ├── base.py                    # 文件源基类
│   ├── local_source.py            # 本地文件源
│   └── __init__.py
│
├── pageindex/                     # 页面索引
│   ├── page_index_txt.py          # 文本页面索引
│   └── utils.py
│
└── utils/                         # 工具函数
    ├── json_utils.py              # JSON 序列化
    └── data_store.py              # 数据存储工具
```

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
python run-all-tests.py    # 集成测试 + 报告

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
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery Broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` | Celery 结果后端 |
| `APP_ENV` | `development` | 运行环境 |
| `CORS_ORIGINS` | `http://localhost:5175` | 前端地址 |
| `BATCH_SIZE` | `100` | 批处理大小 |
| `CACHE_TTL` | `3600` | 缓存 TTL |
| `DATABASE_URL` | `sqlite:///data/sqlite/database.db` | SQLite 路径 |

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
| `/api/decision` | `api/routes/decision.py` | 决策引擎对话 |
| `/api/filesystem` | `api/routes/filesystem.py` | 文件系统操作 |
| `/api/entity-types` | `api/routes/entity_types.py` | 实体类型管理 |
| `/api` | `api/routes/source.py` | 数据源管理 |
| — | `api/routes/database.py` | 数据库连接与导入 |
| — | `api/routes/cdc.py` | CDC 增量同步配置 |
| `/ws/task/{task_id}` | `websocket/task_ws.py` | 任务进度 WebSocket |

## 关键设计约束

- **前后端分离**：后端独立处理全部业务逻辑，前端仅调用接口与展示
- **资源 ID**：URI 统一为 `{TYPE}://{UUID}/{路径}`（`DOC://`、`DBS://`），由 `models/resource_identifier.py` 管理
- **实体/关系 ID**：`entity_id = MD5(name)`，`relationship_id = MD5({subject}_{predicate}_{object})`，由 `models/ids.py` 生成
- **单一存储**：实体与关系写入 Neo4j，通过全文索引实现搜索
- **LLM 集成**：经 `model_management/model_client.py` 统一调用 Ollama API
- **MCP 工具**：通过 `config/mcp_servers.json` 配置外部 MCP Server，自动纳入 AgenticEngine ReAct 循环
- **Agentic 引擎**：统一 ReAct 循环（MAX_TURNS=10），种子检索提供初始上下文，上下文窗口自动压缩
- **CDC 增量同步**：基于 Debezium Server + Redis Streams，设计与操作详见 `cdc/CLAUDE.md`
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
  python run-all-tests.py
  ```
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
| [cdc/CLAUDE.md](cdc/CLAUDE.md) | CDC 模块详细设计指南 |
| [INSTALL.md](../INSTALL.md) | 安装部署与环境变量参考 |