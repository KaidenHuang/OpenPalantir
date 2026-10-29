# 仓库指南

始终使用简体中文回复。

## 项目概述

OpenPalantir 是基于 AI 的数据分析与知识图谱构建系统：支持文档（PDF/Word/PPT/MD/Excel/CSV）与数据库（MySQL/PostgreSQL/SQLite）数据源，通过规则引擎和 LLM 构建摘要、提取实体与关系存入 Neo4j，提供图谱分析（路径/社区/中心性/趋势）与问答型智能决策。UI 为中文。

**早期开发阶段**——**不要实现数据迁移脚本或向后兼容处理**。Schema 变更直接删除 `backend/data/sqlite/database.db` 重启即可；进程锁 DB 时执行 `taskkill /F /IM python.exe` 后重启。后端报错先查 `./logs/backend.log`。

**设计优先**——当前阶段**不考虑向后兼容**，优先考虑设计合理性。旧代码、旧接口、旧 prompt 如果设计不合理，直接改掉或删除，不要保留兼容 shim。测试用例同样如此——测试应验证新设计，不是给旧实现做防腐。

## 系统架构

```
┌─ 前端 (React + TS + Vite) ────────────────┐
│  App.tsx 标签导航 → Axios → 后端 REST API   │
└──────────────────────────────────────────┘
         ↕ HTTP
┌─ 后端 (FastAPI + Python) ─────────────────┐
│  api/routes/ · task_manager(异步)· cdc/(增量)│
│  decision_engine/                           │
│    agentic/(ReAct循环) · memory/(记忆)       │
│    tool_manager/(Skill+MCP) · retrievers/   │
│    skills/(3个内置)                          │
│  wiki/(页面生成) · ontology/(受控本体)        │
│  各 manager/service 层处理全部业务逻辑        │
└──────────────────────────────────────────┘
         ↕
┌─ 存储 ─────────────────────────────────────┐
│  SQLite(元数据) · Neo4j(图) · Redis(CDC 流) │
│  文件系统 data/summaries/                  │
└──────────────────────────────────────────┘
         ↕
┌─ 外部服务 ─────────────────────────────────┐
│  Debezium Server → 源DB binlog/WAL → Redis  │
└──────────────────────────────────────────┘
```

## 项目结构 & 模块组织

本项目采用**前后端分离**架构：

- **`backend/`** -- Python FastAPI 服务端，按领域模块组织（前五个为五阶段数据链路组件，各自再分 `document/` 与 `database/` 两侧）：
  - `api/routes/` -- REST API 端点定义（薄壳，业务归组件）
  - `config/` -- 数据库连接、Neo4j、引擎与环境配置
  - `source_registry/` -- ① 注册数据源（文档源/数据库连接的注册、生命周期、测连、源目录浏览）
  - `content_extraction/` -- ② 内容提取（纯解析，无 LLM）：文档 → 章节树 + 页码，表格文件 → 一个 sheet 一节 + 确定性表档案；数据库 → 表/字段/主外键/视图
  - `summary_generation/` -- ③ 摘要生成（唯一 LLM 环节）：文档摘要树 + 落盘/指纹，表格一次请求出「每表摘要 + 逐列标注」；库表业务标注 + 概要
  - `entity_extraction/` -- ④ 实体抽取：文档批次 LLM 抽实体/关系/属性，表格分支纯规则装配列实体（零 LLM，重读源文件）；数据库行实体/属性表/外键关系
  - `wiki_generation/` -- ⑤ Wiki 生成（文档页 / 跨文档主题页 / 图谱实体页 / 问答沉淀）
  - `pipeline/` -- 跨阶段调度薄层（内容失效传播 `refresh` + 指纹轮询监听 `watcher`）
  - `knowledge_graph/` -- Neo4j 图谱操作（CRUD、分区、性能优化、来源回收、语义行装配）
  - `analysis_engine/` -- 图谱分析（路径、社区、中心性、趋势）
  - `decision_engine/` -- 对话式决策推理内核
    - `agentic/` -- 统一 ReAct 循环（MAX_TURNS=15），种子检索提供初始上下文，上下文窗口自动压缩
    - `memory/` -- 对话记忆管理
    - `tool_manager/` -- Skill + MCP 工具管理
    - `retrievers/` -- 检索器
    - `skills/` -- 3 个内置技能
  - `ontology/` -- 受控本体注册表（YAML 本体包、谓词归一化、prompt 词表注入、治理报告、社区包导入导出）
  - `model_management/` -- LLM 模型客户端集成，经 `ModelClient` 统一调用 Ollama API，支持本地/云端模型
  - `cdc/` -- Debezium 增量同步（CDC 消费 + 事件处理 + Schema 缓存）
  - `task_management/` -- 异步任务队列与状态跟踪
  - `models/` -- SQLAlchemy ORM 模型与资源标识符
  - `utils/` -- 通用工具函数
- **`frontend/`** -- React + TypeScript + Vite 单页应用
- **`tests/`** -- 测试套件（pytest）
- **`scripts/`** -- 服务管理脚本（启动/停止 Neo4j、Redis、Debezium）
- **`data/`** -- 运行时数据（SQLite 数据库、摘要、上传文件）
- **`docs/`** -- 对外文档；方案、计划、评审这类过程产出不进仓库，口径由 docs 与模块注释承载

## 核心设计约束

- **前后端分离**：后端独立处理全部业务逻辑，前端仅调用接口与展示；脱离 UI 后端仍可独立运行。
- **数据库连接**：后端经 SQLAlchemy 连 MySQL/PostgreSQL/SQLite，前端连 Neo4j。
- **实体命名**：数据库行级导入用 `{表名}:{主键值}`（如 `db.users:42`）。
- **资源 ID**：URI 统一为 `{TYPE}://{UUID}/{路径}`（`DOC://` 文档源、`DBS://` 数据库），由 `ResourceIdentifier` 类（`models/resource_identifier.py`）管理；`entity_id` = MD5(`name`)，`relationship_id` = MD5(`{subject}_{predicate}_{object}`)，统一由 `models/ids.py` 生成。完整规范见 `docs/architecture.md` §4.2。
- **单一存储**：实体/关系写入 Neo4j，通过全文索引实现搜索。
- **受控本体**：Neo4j 边类型取自 `ontology/packs/*.yaml` 的 LinkType 词表（谓词归一化**先于** `relationship_id` 计算，公式不变）；未命中词表兜底为「其他」，原始谓词存 `r.raw_predicate`。实体/关系枚举由 `ontology/prompt.py` 动态注入 prompt，文档抽取与 DB Schema 标注共用同一词表。包与类型各有独立的 `display_name`（中文名）：存储与查询永远用 key，界面经 `GET /api/ontology/vocabulary`、Wiki 实体页经 `registry.object_type_label()` 只在**显示时**翻译，改显示名不影响 ID 与页指纹。
- **Wiki 页面**：`wiki_pages` 表存 Markdown 正文 + `source_refs` 引用锚点，kind 为 document/topic/entity/answer；实体页 datasource 为 `ENT://{entity_id}/{name}`；生成按 `source_hash` 幂等跳过，LLM 不可用降级为确定性拼装。
- **来源归属**：实体节点与关系边都带两级来源——`datasource`（主来源，展示与检索用）与 `datasources`（全部佐证来源）。按来源过滤/回收必须走 `knowledge_graph/source_scope.py` 的 Cypher 片段（以 `datasources` 判定），否则重跑一个来源会连带删掉其他来源的佐证。来源 URI 出口：文档 `DOC://{source_id}/{文件相对路径}`、实体页 `ENT://{entity_id}/{name}`、数据库 `DBS://{conn}/{db}[/{table}]`。
- **内容失效传播**：摘要 JSON 内的 `content_hash`（源文件 MD5）是文档指纹，`pipeline/refresh.py` 据此判定 changed/removed/未变更；刷新顺序是**先生成摘要 → 抽取（代际佐证 `URI@content_hash`）→ 旧代回收（`keep_hash` 保留新代，`recycle_datasource` 只摘本来源佐证，清空才删）→ Wiki**，抽取/落库失败时旧图谱数据完好。文档级监听 `pipeline/watcher.py` 轮询派发 `document_refresh` 任务，与只管数据库的 CDC 对称。**详见 `docs/data-flow.md`。**
- **表格文件分支**：Excel/CSV 按文档类型处理（不伪造数据库连接、不接 `DBS://`），一个 sheet = 摘要树一个叶子，界面只借数据库侧的「表卡 + 字段列表」形状。④ 的表格分支**显式重读源文件**（明细行不进摘要 JSON，否则摘要文件变成数据副本），因此有两条硬约束：取行只能走 `content_extraction.document.table_reader.iter_table_rows`（表头判定必须与 ② 同一份代码，否则 ③ 标注的列名错位），且落库前必须校验源文件 MD5 == 摘要 `content_hash`，不一致直接终止写库。**列角色、实体类型、列间关系全在 ③ 的标注里，④ 只做装配 + 上限守卫（`COLUMN_ENTITY_LIMIT`/`SHEET_ENTITY_LIMIT`/`MAX_ROWS_READ`）+ 本体校验，零 LLM。**不做：行实体、跨 sheet 关系、ER 图、表格 CDC。详见 `docs/data-flow.md` 的「表格文件分支」一节。
- **本体治理与社区包**：内置包在 `ontology/packs/`，社区/自定义包在 `backend/data/ontology_packs/`（域包同名以后者为准、**基底包 `general` 只认内置目录**，运行时数据、不入库）；导入即走与内置包相同的校验链（`validate_pack`），导出 YAML 可原样回读。注册表 `version` 每次包注册/reload 自增，`ontology/prompt.py` 以 `(version, domain)` 为缓存键——社区包导入后新词表立刻进 prompt，无需重启。治理查询只读聚合，统一入口 `ontology/governance.py`（兜底占比、词表外谓词、定义域值域违规、游离/占位实体、无来源产出、别名候选），经 `/api/ontology/report` 暴露。
- **配置来源**：`backend/.env`（后端）、`frontend/src/config/apiConfig.ts`（前端 API 端点）。
- **MCP 工具**：通过 `config/mcp_servers.json` 配置外部 MCP Server，工具自动纳入 AgenticEngine ReAct 循环。
- **CDC 增量同步**：基于 Debezium Server + Redis Streams。`snapshot.mode=no_data`（首次只做 schema 快照建 history + 记位点，不重放历史，避免 OOM），**位点由 Debezium 自管、Python 不写 `offsets.dat`**；全量导入捕获的位点只存 `CdcSyncState` 作参考；实体 ID 与全量导入一致（确保更新命中同一节点）；启动前断流检测（`check_stream_continuity()`）；`auto_start_cdc` 全量导入后自动启动。clear 旧位点必须夹在 stop/start 之间，否则运行中的 Debezium 会周期 flush 写回。**配置与启动顺序见 `docs/cdc-setup.md`，数据流转见 `docs/data-flow.md`，模块设计见 `backend/cdc/AGENTS.md`。**

## 构建、测试和开发命令

```bash
# 后端
cd backend && pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 前端
cd frontend && npm install
npm run dev       # Vite 开发服务器（端口 5175）
npm run build     # TypeScript 检查 + Vite 生产构建
npm run lint      # 对 .ts/.tsx 文件运行 ESLint

# 服务管理
# Linux: 启动/停止 Neo4j + Redis (Docker)
bash scripts/service/start-services.sh
bash scripts/service/stop-services.sh
# Windows: 启动/停止 Neo4j + Redis (PowerShell)
scripts/service/start-services.ps1
scripts/service/stop-services.ps1

# 单元测试（无需后端运行）
cd tests
python test_memory.py
python test_skill.py
python test_mcp_integration.py

# 集成测试（需后端运行在 localhost:8000）
cd tests && pytest

# 抽取质量基线（模型管理里没有可用模型时自动 skip）
cd backend && python -m pytest ../tests/test_extraction_quality.py -v -s

# 清理 DB（Schema 变更后删除重启自动重建）
# Linux:   rm backend/data/sqlite/database.db
# Windows: del backend\data\sqlite\database.db
```

> 安装（install-all / install-debezium）、集成测试脚本、构建命令见 `docs/development-guide.md` 与 `INSTALL.md`。

## 编码风格 & 命名规范

- **Python**：遵循 PEP 8，4 空格缩进。使用类型注解。倾向于编写清晰自文档化的代码，而非过多内联注释。
- **TypeScript/React**：2 空格缩进。使用函数式组件与 Hooks。配置的 ESLint 规则必须通过（`max-warnings 0`）。
- **格式化工具**：Prettier，配置为 `{ semi: true, singleQuote: true, printWidth: 100, trailingComma: "all", tabWidth: 2 }`。
- **EditorConfig** 应用于整个项目（`.editorconfig`）；确保你的编辑器已加载它。
- **Naming patterns**：
  - Python modules/files：`snake_case.py`
  - TypeScript/React files：`PascalCase.tsx` for components, `camelCase.ts` for utilities
  - Resource IDs：`{TYPE}://{UUID}/{path}`（e.g., `DOC://a1b2.../document.md`）
  - Entity IDs：MD5(`{name}`) -- 32-char hex
  - Relationship IDs：MD5(`{subject}_{predicate}_{object}`) -- 32-char hex
  - Conversation session IDs：`sess_` + uuid4.hex[:12]

## 测试规范

- **测试框架**：后端测试使用 pytest。
- **标记**：`pytest.ini` 启用了 `--strict-markers`，只允许 `unit` / `integration` / `slow` 三个标记；不依赖外部服务的测试打 `unit`，需要 LLM/Neo4j/Redis 的打 `integration`。
- **抽取质量基线**：`tests/golden/extraction_v1.json` 是 `examples/docs` 的人工标注金标，`tests/test_extraction_quality.py` 据此产出实体/关系召回与越界率报告（写入 `logs/extraction_quality.json`）。没有可用模型时评测用例整体 skip；改 prompt、改本体包时必须先看这一层有没有退化。新增示例文档要同步补金标。详见 `docs/development-guide.md`。
- **覆盖率**：为新功能和 Bug 修复添加测试。提交前确保所有现有测试通过。
- **执行方式**：在 `localhost:8000` 启动后端，然后运行 `cd tests && pytest` 执行完整的集成测试套件。
- **Bash 命令禁含注释**：测试验证时生成的 Bash 命令不能含 `#` 注释（避免触发路径验证警告）；如需注释说明，写在命令之外。
- **避免 `cd` + 输出重定向**：禁止 `cd dir && cmd > file` 这类写法，改用绝对路径或 `--output` 等参数替代。

## 提交 & Pull Request 指南

使用 **Conventional Commits（约定式提交）** 格式：

| Prefix      | Purpose              |
|-------------|----------------------|
| `feat:`     | 新功能                |
| `fix:`      | Bug 修复             |
| `docs:`     | 文档                 |
| `style:`    | 代码格式调整           |
| `refactor:` | 代码重构              |
| `test:`     | 测试新增              |
| `chore:`    | 构建/工具变更          |

**分支命名**：`feature/your-feature`、`fix/your-bugfix`。

**PR 要求**：
- 清晰的描述，说明变更的*原因*（而不仅仅是*内容*）。
- 关联相关 Issue。
- 等待 CI 通过。
- 合并前需要至少一位维护者审查。

## 安全 & 配置提示

- **`.env` 文件**：后端配置位于 `backend/.env`。切勿提交密钥。使用 `.env.example` 作为模板。
- **API 配置**：前端 API 端点在 `frontend/src/config/apiConfig.ts` 中设置。
- **数据库重置**：删除 `backend/data/sqlite/database.db` 并重启；Schema 将自动重建。如果数据库被锁定，先运行 `taskkill /F /IM python.exe`。
- **日志**：后端日志写入 `./logs/backend.log` —— 调试后端问题时请首先检查该文件。

## 详细文档

| 文档 | 内容 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 系统架构、后端模块结构、前端组件树、存储分层、ID 规范 |
| [docs/data-flow.md](docs/data-flow.md) | 文档分析/数据库导入/CDC/决策引擎的业务流程与数据流转，含表格文件（Excel/CSV）分支口径 |
| [docs/cdc-setup.md](docs/cdc-setup.md) | CDC 增量同步：新环境配置、完整启动顺序、关键设计 |
| [docs/development-guide.md](docs/development-guide.md) | 开发环境搭建、添加功能、代码规范 |
| [docs/ontology-guide.md](docs/ontology-guide.md) | 本体包写法、`extends` 扩展链、谓词归一化如何改变落库数据、治理报告怎么读 |
| [examples/README.md](examples/README.md) | 示例文档与示例社区本体包、一键 demo `scripts/demo/run_demo.py` |
| [INSTALL.md](INSTALL.md) | 安装部署、环境变量参考、系统要求、常见问题 |
| [backend/cdc/AGENTS.md](backend/cdc/AGENTS.md) | CDC 模块（`backend/cdc/`）设计、关键设计、多类型支持、修改注意 |