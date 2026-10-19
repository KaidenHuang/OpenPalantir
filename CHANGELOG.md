# 变更日志 | Changelog

本文档记录 OpenPalantir 的所有重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

LLM Wiki + 受控本体演进路线的三个里程碑（M1 Wiki 与检索、M2 本体层、M3 增量与治理）。

### 新增

- **LLM Wiki**（`backend/wiki/`）：文档页 / 跨文档主题页 / 本体实体页三级生成，页面可编辑、带 draft/published 状态，正文保留 `node_id` 引用锚点与 wiki-link
- **Wiki API**（`/api/wiki/pages`、`/api/wiki/generate`、`/api/wiki/publish_answer`）：问答答案可发布为带引用的新页面
- **前端 Wiki 标签页**：目录树 + Markdown 渲染 + 编辑，页面内「就本页提问」把 scope 带入智能决策
- **引用溯源**：`POST /api/decision/ask` 支持 `scope`（页面/文档）并返回 `citations`，前端渲染为可点击锚点
- **混合检索**：摘要树推理式导航工具 + Neo4j 全文 + embedding 重排，统一收拢在 `agentic/seed_retriever`
- **长文生成**：`ModelClient` 支持流式与分节续写，解除单次 8192 token 限制；新增 embedding 接口（Ollama `bge-m3`）
- **本体层**（`backend/ontology/`）：`ObjectType` / `LinkType` / `PropertyType` / `OntologyPack` 与 YAML 本体包注册表，内置 general / workforce / finance / medical 四包
- **谓词归一化**：写入前任意谓词映射到受控 key（exact → 别名 → 兜底「其他」并保留 `raw_predicate`），归一化先于 `relationship_id` 计算；Neo4j 边从单一 `RELATED_TO` 改为按 LinkType 类型化
- **本体包 `extends`**：社区包可挂在内置域包之上只写增量，校验相对父视图进行
- **本体治理**（`/api/ontology/report`）：词表使用率、词表外谓词、非法实体类型、定义域/值域违规、游离/占位实体、无来源产出、别名候选与结论清单
- **本体 API**：域列表、包导入导出（YAML 回读等价）、reload，导入即让 prompt 缓存失效，无需重启
- **内容失效传播**：摘要 JSON 记录源文件 `content_hash`，变更即标记受影响摘要/实体/Wiki 页为 stale 并重跑「摘要 → 图谱回收 → 重抽取 → Wiki 刷新」；`pipeline/watcher.py` 可选轮询监听
- **示例与一键 demo**：`examples/docs`（三篇同主题文档）+ `examples/ontology/rd_efficiency.yaml` + `scripts/demo/run_demo.py`
- **PPT 内容提取**（`content_extraction/document/converters/pptx_converter.py`）：`.pptx` 经 python-pptx 提取，每页幻灯片一个章节、幻灯片序号作为页码锚点；标题占位符缺失时（企业模板把标题画成文本框）退化为页面第一行文本，表格、组合图形、图表（类别×系列）与 SmartArt 图示文字（读 `diagrams/dataN.xml` 的 `dgm:pt`）都进正文，演讲者备注并入同页章节，旧版 `.ppt` 二进制明确拒绝
- **`GET /api/sources/formats`**：对外暴露可解析的文档扩展名（取自转换器注册表），`scripts/demo/run_demo.py` 改用该接口取代脚本内硬编码清单

### 变更

- 实体/关系类型枚举改为从本体注册表动态注入，文档抽取与数据库 Schema 标注共用同一套词表；DB 行级导入原先的 6 选项硬编码关系词表并入统一 LinkType
- 问答的领域实体词表取自本体注册表，社区导入的域自动可用于问答
- 关系类型化边需要干净图谱：删除 `backend/data/sqlite/database.db` 与 Neo4j 数据后重新导入（早期阶段不写迁移脚本）

### 移除

- `backend/config/domain_config.yaml`（词表唯一来源改为本体包，消除重复定义）

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
