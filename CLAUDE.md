***

description: OpenPalantir 项目指南 — 中文
alwaysApply: true
-----------------

# OpenPalantir 项目指南

## 项目概述

OpenPalantir 是一个基于 AI 的数据分析与知识图谱构建系统。支持文档（PDF/Word/MD/图片）、数据库（MySQL/PostgreSQL/SQLite）等数据源，通过规则引擎和 LLM 为数据源构建摘要，并提取实体与关系，存入 Neo4j（图数据库），提供图谱分析（路径分析、社区发现、中心性计算、趋势分析）和问答型智能决策能力。UI 为中文。

当前处于早期开发阶段。**不要实现数据迁移脚本或向后兼容处理**。数据库 Schema 变更直接删除 `backend/data/sqlite/database.db` 后重启应用即可。若进程锁住 DB，执行 `taskkill /F /IM python.exe` 后重启。

后端日志存放在 `./logs/backend.log` 中，后端报错可参考此日志解决。

## 系统架构

```
┌─ 前端 (React + TypeScript + Vite) ─────────────────────┐
│  App.tsx → 标签导航：文档/DB/实体/图谱/任务/模型/分析/决策 │
│  组件 → API Config → Axios → 后端 REST API               │
└────────────────────────────────────────────────────────┘
         ↕ HTTP
┌─ 后端 (FastAPI + Python) ───────────────────────────────┐
│  api/routes/ → 各模块 router                             │
│  task_manager → 异步任务队列（状态追踪）                    │
│  各 manager/service 层处理业务逻辑                         │
└────────────────────────────────────────────────────────┘
         ↕
┌─ 存储层 ────────────────────────────────────────────────┐
│  SQLite (应用元数据) | Neo4j (图关系)                      │
│  文件系统 (data/summaries/)                │
└────────────────────────────────────────────────────────┘
```

## 后端模块结构

| 模块                     | 职责                             | 核心文件                                                                                            |
| ---------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------- |
| `config/`              | 数据库连接、Neo4j 配置                 | `database.py`, `neo4j_config.py`                                                                 |
| `api/routes/`          | REST API 端点                    | `graph.py`, `analysis.py`, `database.py`, `model.py`, `decision.py`, `source.py`, `filesystem.py` |
| `document_processing/` | 文档解析（PDF/Word/MD/图片→文本）        | `document_processor.py`                                                                          |
| `entity_extraction/`   | 实体识别（LLM 增强）                   | `llm_entity_enhancer.py`                                                                        |
| `knowledge_graph/`     | Neo4j 图操作（增删查、社区检测、批量优化 + 实体 CRUD/搜索） | `graph_manager.py`, `graph_partition.py`, `graph_performance.py`                                |
| `analysis_engine/`     | 图谱分析（NetworkX 路径/中心性/社区/趋势）    | `analyzer.py`, `report_generator.py`                                                            |
| `database_management/` | 外部数据库连接管理 + Schema 提取 + LLM 标注 | `database_manager.py`, `database_service.py`, `schema_annotator.py`                             |
| `decision_engine/`     | 智能决策（插件化架构，查询数据库 + 图谱）         | `decision_kernel.py`, `plugin_registry.py`, `plugins/`, `adapters/`                             |
| `task_management/`     | 异步任务执行 + 状态追踪                  | `task_manager.py`, `task_service.py`                                                            |
| `system/`              | 日志（文件输出到 `logs/`）、管道编排         | `logger.py`, `system_integration.py`                                                            |
| `models/`              | SQLAlchemy ORM 模型              | `database.py`, `model.py`, `source.py`, `task.py`                                               |
| `file_sources/`        | 文件源抽象（本地、S3 等）                 | `local_source.py`, `base.py`                                                                    |
| `pageindex/`           | 文档摘要树生成（PDF/MD/TXT 分层结构）       | `page_index.py`, `page_index_md.py`, `utils.py`                                                 |
| `utils/`               | 数据存储工具                         | `data_store.py`                                                                                 |
| `model_management/`    | LLM 模型管理（Ollama API 调用）        | `model_client.py`, `model_service.py`                                                           |

## 前端组件

| 组件                                                 | 功能                           |
| -------------------------------------------------- | ---------------------------- |
| `DocumentViewer`                                   | 文档浏览 + 摘要树展示 + 实体提取触发        |
| `EntityManagement`                                 | 实体搜索、查看、编辑                   |
| `GraphVisualization`                               | D3.js 图谱可视化（节点/边交互）          |
| `AnalysisDashboard`                                | 路径/社区/中心性/趋势分析报告             |
| `DatabaseManagement`                               | 外部数据库连接 → Schema 分析 → 行级图谱导入 |
| `DecisionAssistant`                                | 智能决策对话界面                     |
| `TaskManagement/TaskList/TaskDetails/TaskCreation` | 异步任务管理                       |
| `ModelManagement`                                  | LLM 模型配置（本地/云端）              |
| `ERDiagram`                                        | 数据库 ER 图可视化                  |

## 核心业务流程

### 文档分析流程

```
添加文档源 → DocumentProcessor 解析文本 → PageIndex 生成摘要树
         → LLMEntityEnhancer 提取实体+关系 → EntityDataStore 写入 Neo4j
         → AnalysisEngine 图谱分析
```

### 数据库导入流程（两阶段）

```
阶段1（Schema 分析）：
添加数据源 → 获取数据库列表 → DatabaseDialect 提取 Schema → SchemaAnnotator(LLM) 标注业务描述
→ 保存到本地 SQLite + 生成数据库概要文件 data/summaries/DBS/{conn_id}/{db_name}.json

阶段2（图谱导入）：
读取本地 Schema → 连接源DB逐表查询行数据（上限1000行/表）
→ 每行构建为一个实体（命名：{表名}:{主键值}）
→ 外键值匹配构建行间关系 → EntityDataStore.save_all() 写入 Neo4j
```

## 开发命令

```bash
# 后端
cd backend && pip install -r requirements.txt
uvicorn main:app --reload --port 8001

# 前端
cd frontend && npm install
npm run dev       # 端口 5175
npm run build

# 服务管理（PowerShell）
scripts/service/start-services.ps1   # 启动 Neo4j + Redis
scripts/service/stop-services.ps1    # 停止 Neo4j + Redis

# 测试
cd tests && pytest                   # 需运行后端 localhost:8001
python run-all-tests.py              # 集成测试 + 报告

# 清理 DB
del backend\data\sqlite\database.db  # 删除后重启自动重建
```

## 测试规范

- **Bash 命令禁含注释**：测试验证时生成的 Bash 命令不能包含 `#` 注释（避免触发路径验证警告）。如需注释说明，写在命令之外。
- **避免 `cd` + 输出重定向**：禁止在测试命令中使用 `cd` 后跟输出重定向（如 `cd dir && cmd > file`），改用绝对路径或 `--output` 等参数替代。

## 关键设计决策

- **前后端分离架构**：后端负责业务逻辑的实现，前端负责调用后端接口以及展示返回结果，不参与业务的逻辑处理，即脱离界面，后端依旧能够独立处理业务逻辑。
- **数据库连接**：后端通过 SQLAlchemy 连接 MySQL/PostgreSQL/SQLite 数据库，前端通过 Neo4j 连接。
- **实体命名规则**：数据库行级导入使用 `{表名}:{主键值}`（如 `db.users:42`）
- **资源 ID 格式规范**：
  - **统一资源标识符（ResourceIdentifier）**：`{TYPE}://{UUID}/{路径}`，通过 `ResourceIdentifier` 类（`models/resource_identifier.py`）管理，支持 `parse()` / `generate()` / `uri` / `file_safe_name`
    - `DOC://` — 文档源，如 `DOC://a1b2c3d4-.../重生野性时代-100章.txt`
    - `DBS://` — 数据库，如 `DBS://c0e2d4ca-.../employees/departments`
  - `DocumentSource.id` / `Connection.id` — UUID v4，36 字符（`d3060fed-53a1-4e9f-895b-8cfa31e5c189`）。`DocumentSource.id` 为纯 UUID（不再使用 `src_` 前缀）
  - `Task.id` — UUID v4，36 字符
  - `entity_id` — MD5(`{name}_{type}`)，32 字符 hex
  - `relationship_id` — MD5(`{subject}_{predicate}_{object}`)，32 字符 hex
  - 图节点 `id`（Neo4j）— UUID v4
  - `node_id`（PageIndex 摘要树）— 8 位零填充序号（`00000001` 起），文档和数据库概要统一格式
  - 会话 ID — `sess_` + uuid4.hex\[:12]（`sess_a1b2c3d4e5f6`）
  - 实体/关系字典的 `datasource_id` — URI 格式 `{TYPE}://{UUID}/{路径}`，关系字典新增 `datasource_id` 字段
  - `AnalyzedTable.uri`（新增 ORM 模型）— `DBS://{conn_uuid}/{db_name}/{table_name}`
  - 概要 JSON 中的 `resource_id` — URI 格式 `{TYPE}://{UUID}/{路径}`
- **概要文件存储**：`data/summaries/DOC/{source_uuid}/`（文档）和 `data/summaries/DBS/{conn_uuid}/`（数据库），按资源类型分目录
- **LLM 集成**：通过 `ModelClient` 统一调用 Ollama API，支持本地和云端模型
- **单一存储**：实体和关系写入 Neo4j（图遍历），通过全文索引实现搜索
- **配置来源**：`backend/.env` 配置数据库连接，`frontend/src/config/apiConfig.ts` 配置 API 端点


