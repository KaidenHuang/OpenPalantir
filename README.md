# OpenPalantir

基于 AI 的数据分析与知识图谱构建系统 | AI-Powered Data Analysis & Knowledge Graph System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Node.js](https://img.shields.io/badge/node-18+-green.svg)](https://nodejs.org/)
[![React](https://img.shields.io/badge/react-18-61dafb.svg)](https://react.dev/)

<p align="center">
  <img src="frontend/public/openpalantir.svg" alt="OpenPalantir Logo" width="128" height="128"/>
</p>

> **Logo 释义**：中央的水晶球象征 Palantir——洞悉世间万物、洞察数据真相；环绕四周的五本书籍源源不断地为水晶球输送知识与数据，寓意系统从多源异构数据中汲取养分，汇入知识图谱，赋能智能决策。

OpenPalantir 是一个基于 AI 的数据分析与知识图谱构建系统。支持文档（PDF/Word/Markdown/图片）、数据库（MySQL/PostgreSQL/SQLite）等多种数据源，通过规则引擎和 LLM 为数据源构建摘要，并提取实体与关系，存入 Neo4j 图数据库，提供图谱分析（路径分析、社区发现、中心性计算、趋势分析）和问答型智能决策能力。

## 功能特性

- **多源数据接入** — 支持 PDF、Word、Markdown、图片（OCR）、MySQL、PostgreSQL、SQLite 等
- **智能实体提取** — 基于 LLM 的实体识别与关系抽取，支持自定义实体类型
- **知识图谱构建** — Neo4j 图数据库存储，支持大规模图谱的批量优化与分区管理
- **图谱分析引擎** — 路径分析、社区发现、中心性计算、趋势分析
- **智能决策助手** — 插件化架构，结合图谱与数据库的问答型决策支持
- **异步任务管理** — 全流程异步任务队列，实时状态追踪
- **交互式可视化** — D3.js 图谱可视化，支持节点/边交互与 3D 展示

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Vite + Ant Design 5 + D3.js |
| 后端 | FastAPI + Python 3.10+ |
| 图数据库 | Neo4j 4.4+ |
| 任务队列 | Celery + Redis |
| 元数据库 | SQLite |
| 图谱分析 | NetworkX + scikit-learn |
| LLM 集成 | Ollama / OpenAI / DeepSeek / SiliconFlow |

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

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- Neo4j 4.4+
- Redis 6+

### 安装与运行

```bash
# 克隆仓库
git clone https://github.com/your-org/OpenPalantir.git
cd OpenPalantir

# 后端
cd backend
cp .env.example .env   # 编辑 .env 填入你的配置
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev             # 端口 5175
```

访问 http://localhost:5175 打开应用，http://localhost:8000/docs 查看 API 文档。

### 使用 Docker（推荐）

```bash
docker-compose up -d
```

## 项目结构

```
OpenPalantir/
├── backend/                # FastAPI 后端
│   ├── api/routes/         # REST API 端点
│   ├── analysis_engine/    # 图谱分析引擎
│   ├── config/             # 数据库 & Neo4j 配置
│   ├── database_management/# 外部数据库连接管理
│   ├── decision_engine/    # 智能决策引擎
│   ├── document_processing/# 文档解析（PDF/Word/MD/图片）
│   ├── entity_extraction/  # 实体识别（LLM 增强）
│   ├── file_sources/       # 文件源抽象
│   ├── knowledge_graph/    # Neo4j 图操作
│   ├── model_management/   # LLM 模型管理
│   ├── models/             # SQLAlchemy ORM 模型
│   ├── pageindex/          # 文档摘要树
│   ├── system/             # 日志 & 系统集成
│   ├── task_management/    # 异步任务管理
│   └── utils/              # 工具函数
├── frontend/               # React 前端
│   └── src/
│       ├── components/     # UI 组件
│       └── config/         # API 配置
├── scripts/                # 安装 & 服务管理脚本
├── tests/                  # 测试
└── docs/                   # 设计文档
```

## 文档

- [效果展示](docs/screenshots.md)
- [安装指南](INSTALL.md)
- [用户指南](docs/user-guide.md)
- [架构设计](docs/architecture.md)
- [API 参考](docs/api-reference.md)
- [数据流说明](docs/data-flow.md)
- [开发指南](docs/development-guide.md)
- [部署指南](docs/deployment.md)
- [贡献指南](CONTRIBUTING.md)
- [行为准则](CODE_OF_CONDUCT.md)
- [安全政策](SECURITY.md)
- [变更日志](CHANGELOG.md)

## 贡献

欢迎贡献！请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 了解如何参与。

## 许可证

本项目基于 MIT 许可证开源。详见 [LICENSE](LICENSE) 文件。

OpenPalantir is open source software licensed under the [MIT License](LICENSE).
