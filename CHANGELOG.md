# 变更日志 | Changelog

本文档记录 OpenPalantir 的所有重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2025-06-01

### 新增

- 文档源管理：支持 PDF、Word、Markdown、图片（OCR）文档上传与解析
- 文档摘要树：基于 PageIndex 的分层文档摘要生成
- 实体提取：基于 LLM 的实体识别与关系抽取，支持自定义实体类型
- 知识图谱：Neo4j 图数据库存储，支持实体 CRUD、全文搜索、图谱可视化
- 数据库接入：MySQL、PostgreSQL、SQLite 的 Schema 分析与行级图谱导入
- 图谱分析引擎：路径分析、社区发现（Louvain）、中心性计算、趋势分析
- 智能决策助手：插件化架构，支持自然语言查询数据库与图谱
- LLM 模型管理：支持 Ollama 本地模型与 OpenAI/DeepSeek/SiliconFlow 云端模型
- 异步任务管理：全流程任务队列（Celery + Redis），实时状态追踪
- 交互式可视化：D3.js 力导向图，支持 2D/3D 节点交互
- 文件源抽象层：支持本地文件系统，预留 S3 扩展接口

### 技术栈

- 后端：FastAPI + SQLAlchemy + Neo4j Driver + Celery + Redis
- 前端：React 18 + TypeScript + Vite + Ant Design 5 + D3.js
- 分析：NetworkX + scikit-learn
- 数据库：SQLite（元数据）+ Neo4j（图数据）

[1.0.0]: https://github.com/your-org/OpenPalantir/releases/tag/v1.0.0
