# 项目上下文 | Project Context

供 OpenSpec 流程读取的项目背景。写提案/规格前先读这份，避免与既有约定冲突。

## 这是什么

OpenPalantir：把企业文档与数据库变成 **LLM Wiki + 受控本体知识图谱** 的开源系统。链路是「解析 → 层级摘要 → 本体约束抽取 → 图谱 → Wiki 生成 → 带引用的问答 → 增量刷新」。

定位是**开源项目 + 社区**：领域本体包（`extends` 内置域、只写增量）是最主要的贡献形态。

## 技术栈

- 后端：FastAPI + Python 3.10+ + SQLAlchemy（SQLite 元数据）+ Neo4j 驱动 + Celery/Redis
- 前端：React 18 + TypeScript + Vite + Ant Design 5 + D3.js
- 解析：MinerU（PDF）、OCR（图片）；摘要：PageIndex 式层级摘要树（`backend/pageindex/`）
- LLM：经 `ModelClient` 统一调用，支持 Ollama / OpenAI / DeepSeek / SiliconFlow，含 embedding 与流式
- CDC：Debezium Server + Redis Streams

## 模块地图

| 目录 | 职责 |
|------|------|
| `backend/api/routes/` | REST 端点，只做参数校验与转发，业务在各模块 service |
| `backend/ontology/` | 本体注册表、谓词归一化、治理报告、prompt 注入；包 YAML 在 `packs/` |
| `backend/wiki/` | 页面生成与服务（文档页/主题页/实体页） |
| `backend/decision_engine/` | ReAct 循环、检索、记忆、Skill+MCP |
| `backend/knowledge_graph/` | Neo4j 读写、来源回收、分区 |
| `backend/source_management/` `document_processing/` `pageindex/` | 文档解析、摘要与失效重生成 |
| `frontend/src/components/` | 标签页组件，UI 文案为中文 |

## 硬约束（提案不得违反）

1. **早期开发阶段不做向后兼容**：Schema 变更直接删 `backend/data/sqlite/database.db` 与 Neo4j 数据重建，**不写迁移脚本**；旧接口/旧 prompt 设计不合理就直接改或删，不留兼容 shim。
2. **设计优先**：不为「以后可能用」预留开关或抽象；边界内信任内部代码，只在系统边界（用户输入、外部 API）做校验。
3. **单一词表来源**：实体/关系类型只能来自本体注册表。任何新枚举都要问「这是不是一条 LinkType/ObjectType」，而不是再建一份配置。
4. **写入路径共用归一化**：所有关系写入必须经 `ontology/predicates.canonical_rel_id`，保证 `relationship_id = MD5(subject_受控predicate_object)` 全链一致。
5. **治理是只读的**：报告只跑聚合查询，整改动作由人或脚本据结论执行。
6. **前后端分离**：后端脱离 UI 可独立运行完整链路，前端只调接口与展示。
7. **UI 中文**：面向用户的文案、错误提示、文档默认简体中文。

## 验证约定

- 单元测试：`cd tests && python test_*.py`（无需后端）
- 集成测试：后端跑在 `localhost:8000`，`cd tests && pytest`
- 抽取质量基线：`cd tests && pytest test_extraction_quality.py -v -s`（无可用模型时 skip，报告写入 `logs/extraction_quality.json`）
- 端到端：`python scripts/demo/run_demo.py` 走一遍真实链路（素材在 `examples/`）
- 提交前：`cd frontend && npm run lint`（`max-warnings 0` 必须通过）+ `npm run build`
- 后端报错先查 `./logs/backend.log`

## 提交约定

Conventional Commits（`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:` / `style:`），分支 `feature/xxx`、`fix/xxx`。PR 说明要写清*原因*。
