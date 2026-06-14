***

description: OpenPalantir 项目指南 — 中文
alwaysApply: true
-----------------
始终使用简体中文回复。

# OpenPalantir 项目指南

## 项目概述

OpenPalantir 是基于 AI 的数据分析与知识图谱构建系统:支持文档(PDF/Word/MD/图片)与数据库(MySQL/PostgreSQL/SQLite)数据源,通过规则引擎和 LLM 构建摘要、提取实体与关系存入 Neo4j,提供图谱分析(路径/社区/中心性/趋势)与问答型智能决策。UI 为中文。

**早期开发阶段**——**不要实现数据迁移脚本或向后兼容处理**。Schema 变更直接删除 `backend/data/sqlite/database.db` 重启即可;进程锁 DB 时执行 `taskkill /F /IM python.exe` 后重启。后端报错先查 `./logs/backend.log`。

## 系统架构

```
┌─ 前端 (React + TS + Vite) ────────────────┐
│  App.tsx 标签导航 → Axios → 后端 REST API   │
└──────────────────────────────────────────┘
         ↕ HTTP
┌─ 后端 (FastAPI + Python) ─────────────────┐
│  api/routes/ · task_manager(异步)· cdc/(增量)│
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

## 开发命令

```bash
# 后端
cd backend && pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 前端
cd frontend && npm install
npm run dev       # :5175
npm run build

# 服务管理(PowerShell):启动/停止 Neo4j + Redis + Debezium
scripts/service/start-services.ps1
scripts/service/stop-services.ps1

# 测试(需后端运行在 localhost:8000)
cd tests && pytest

# 清理 DB(Schema 变更后删除重启自动重建)
del backend\data\sqlite\database.db
```

> 安装(install-all / install-debezium)、集成测试脚本、构建命令见 `docs/development-guide.md` 与 `docs/deployment.md`。

## 测试规范

- **Bash 命令禁含注释**:测试验证时生成的 Bash 命令不能含 `#` 注释(避免触发路径验证警告);如需注释说明,写在命令之外。
- **避免 `cd` + 输出重定向**:禁止 `cd dir && cmd > file` 这类写法,改用绝对路径或 `--output` 等参数替代。

## 核心设计约束

- **前后端分离**:后端独立处理全部业务逻辑,前端仅调用接口与展示;脱离 UI 后端仍可独立运行。
- **数据库连接**:后端经 SQLAlchemy 连 MySQL/PostgreSQL/SQLite,前端连 Neo4j。
- **实体命名**:数据库行级导入用 `{表名}:{主键值}`(如 `db.users:42`)。
- **资源 ID**:URI 统一为 `{TYPE}://{UUID}/{路径}`(`DOC://` 文档源、`DBS://` 数据库),由 `ResourceIdentifier` 类(`models/resource_identifier.py`)管理;`entity_id` = MD5(`{name}_{type}`),`relationship_id` = MD5(`{subject}_{predicate}_{object}`)。完整规范见 `docs/architecture.md` §4.2。
- **单一存储**:实体/关系写入 Neo4j,通过全文索引实现搜索。
- **LLM 集成**:经 `ModelClient` 统一调用 Ollama API,支持本地/云端模型。
- **配置来源**:`backend/.env`(后端)、`frontend/src/config/apiConfig.ts`(前端 API 端点)。
- **CDC 增量同步**:基于 Debezium Server + Redis Streams。`snapshot.mode=never`;实体 ID 与全量导入一致(确保更新命中同一节点);启动前断流检测(`check_stream_continuity()`);`auto_start_cdc` 全量导入后自动启动;`offset_store.py` 复刻 Java 序列化格式生成 `offsets.dat`,确保从全量位点而非 binlog 头开始。**配置与启动顺序见 `docs/cdc-setup.md`,数据流转见 `docs/data-flow.md`。**

## 详细文档

| 文档 | 内容 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 系统架构、后端模块结构、前端组件树、存储分层、ID 规范 |
| [docs/data-flow.md](docs/data-flow.md) | 文档分析/数据库导入/CDC/决策引擎的业务流程与数据流转 |
| [docs/cdc-setup.md](docs/cdc-setup.md) | CDC 增量同步:新环境配置、完整启动顺序、关键设计 |
| [docs/development-guide.md](docs/development-guide.md) | 开发环境搭建、添加功能、代码规范 |
| [docs/deployment.md](docs/deployment.md) | Docker/手动部署、环境变量参考、系统要求 |
