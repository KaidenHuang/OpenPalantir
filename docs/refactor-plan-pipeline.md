# 后端五阶段组件化重构计划

> 目标：按「注册数据源 → 内容提取 → 摘要生成 → 实体提取 → Wiki 生成」五阶段重组后端，
> 每阶段一个组件目录，组件内部再分 `document/` 与 `database/` 子包，模块独立、解耦。
> 本计划基于 2026-10-19 的代码现状盘点，供审核后逐阶段实施。

---

## 1. 现状盘点与差距

### 1.1 现有模块 → 五阶段映射

| 阶段 | 文档侧现状 | 数据库侧现状 | 主要问题 |
|------|-----------|-------------|---------|
| ① 注册数据源 | `api/routes/source.py`（路由直接操作 ORM）+ `file_sources/`（base/local/watcher 混放） | `database_management/database_manager.py`（673 行：连接 CRUD + schema 提取 + 测连混在一起） | 数据访问逻辑散在路由里；`file_sources` 的「文件源抽象」与「失效监听」语义混杂；`database_manager` 单文件职责过重 |
| ② 内容提取 | `content_extraction/`（章节树 + 页码，纯解析，已达标） | `database_manager.extract_schema`（表/字段/主外键，**无视图提取**） | 与连接管理耦合在同一文件；不提取视图 |
| ③ 摘要生成 | `content_summarization/`（LLM 摘要树）+ `document_processing/summary_generator.py`（落盘/指纹/URI） | `schema_annotator.py`（库表标注+摘要）；**概要落盘逻辑散落在 task handler**（`handlers/schema_analyze.py` 步骤4） | 组件间边界尚可，但「落盘」职责一半在组件、一半在 handler，违反组件自治 |
| ④ 实体提取 | `source_management/source_service.py`（分段/合并/并发编排）+ `entity_extraction/llm_entity_enhancer.py` | `import_helpers.py` + `handlers/schema_import.py`（行级导入核心散在 handler） | `source_management` 名不副实（实际是文档侧提取编排）；handler 里塞了 343 行业务核心；文档侧实体属性提取尚未启用本体 PropertyType |
| ⑤ Wiki 生成 | `wiki/`（文档页/主题页/实体页 CRUD+编排） | 无（库表页面未涉及） | 目录名未与其他组件统一为 `wiki_generation` |

### 1.2 独立于五阶段、需在迁移中同步处理的模块

| 模块 | 处置 |
|------|------|
| `document_processing/document_processor.py` | **删除**。旧解析器（PyPDF2 纯文本、无章节/页码结构），能力已被 `content_extraction/` 完全覆盖，仅 `file_sources/local_source.py` 引用 |
| `document_processing/summary_generator.py` | 移入 `summary_generation/document/store.py`，目录解散 |
| `source_management/refresh_service.py` | 是**跨阶段**的失效传播编排（先摘要→抽取→旧代回收→Wiki），不属于任何单一组件 → 移入独立薄层 `pipeline/refresh.py` |
| `file_sources/watcher.py` | 轮询指纹派发 `document_refresh`，同样是跨阶段调度 → `pipeline/watcher.py` |
| `utils/data_store.py`（EntityDataStore） | 实体/关系的图谱写入属** Neo4j 存储层**而非五阶段业务 → 移入 `knowledge_graph/` |
| `cdc/` | 保持独立（Debezium 增量同步是基础设施），仅同步修改其 import（`cdc_manager` / `debezium_config` / `schema_cache` 引用了 `DatabaseService` / `database_manager`） |
| `task_management/` | 保持独立；handler 继续**瘦壳**，剥离业务核心后只调组件服务 |

---

## 2. 目标目录结构

```
backend/
├── source_registry/                  # ① 注册数据源
│   ├── __init__.py                   # 导出统一注册入口
│   ├── document/
│   │   ├── registry.py               # 文档源注册/列表/删除/恢复/软删判定（数据访问自 route 收编）
│   │   ├── file_source.py            # ← file_sources/base.py + local_source.py
│   │   │                             #   （local_source 重写为调 content_extraction.document，替代旧 processor）
│   │   └── scanner.py                # 源内支持文件遍历 + safe_join 路径守卫收编
│   └── database/
│       └── registry.py               # 数据库连接 CRUD/恢复/软删/测连（自 database_manager + DatabaseService 收编）
│
├── content_extraction/               # ② 内容提取（纯解析，无 LLM）
│   ├── __init__.py                   # extract(spec)：按源类型分发
│   ├── document/                     # 现 content_extraction/ 整体下移
│   │   ├── models.py                 # ExtractedDocument / Section（章节树 + 页码）
│   │   ├── extract.py                # extract_content 入口
│   │   ├── md_parser.py              # MD/PDF 共用建树核心
│   │   └── converters/               # pdf / docx / md / txt(+图片) 格式注册表
│   └── database/
│       ├── models.py                 # DatabaseSchema 契约：tables/columns/foreign_keys/views
│       ├── connector.py              # 连接执行器：engine 构建/试连/方言（自 database_manager 抽出）
│       ├── schema_reader.py          # extract_schema：表/字段/主外键/视图提取
│       └── store.py                  # ← DatabaseService.save_schema/get_schema（Schema 结果持久化 SQLite）
│
├── summary_generation/               # ③ 摘要生成（唯一 LLM 环节）
│   ├── __init__.py
│   ├── document/
│   │   ├── summarizer.py             # ← content_summarization/summarizer.py：节点摘要 + 文档整体摘要
│   │   ├── tree_utils.py             # node_id / 子树正文 / 页码区间
│   │   ├── llm.py                    # ModelClient 异步薄封装
│   │   ├── prompts/                  # prompt_summary_node.md / prompt_doc_description.md
│   │   └── store.py                  # ← document_processing/summary_generator.py
│   │                                 #   （落盘/指纹/URI/删除/遍历；文件路径布局不变）
│   └── database/
│       ├── annotator.py              # ← database_management/schema_annotator.py（库/表摘要标注）
│       ├── prompts/                  # prompt_schema_annotate.md
│       └── store.py                  # 库/表概要 JSON 落盘（自 handlers/schema_analyze.py 步骤4收编）
│
├── entity_extraction/                # ④ 实体提取
│   ├── __init__.py
│   ├── document/
│   │   ├── chunker.py                # ← source_management/source_service.py 的分段/切分/合并
│   │   ├── extractor.py              # ← entity_extraction/llm_entity_enhancer.py
│   │   ├── prompts/                  # prompt_combined_template.md 等
│   │   └── service.py                # 逐篇编排：并发提取 → 去重 → 图写入（evidence_hash 代际）
│   └── database/
│       ├── row_reader.py             # 行级批量读取（自 handlers/schema_import.py 抽出）
│       └── importer.py               # ← database_management/import_helpers.py + 导入编排核心
│
├── wiki_generation/                  # ⑤ Wiki 生成
│   ├── __init__.py
│   ├── service.py                    # ← wiki/wiki_service.py：CRUD/生成编排/答案发布/孤儿清理
│   ├── document/
│   │   ├── document_page_generator.py# ← wiki/page_generator.py 文档页
│   │   ├── topic_page_generator.py   # ← wiki/page_generator.py 跨文档主题页
│   │   └── prompts/
│   └── entity/
│       └── entity_page_generator.py  # ← wiki/entity_generator.py（图谱实体页，混合来源）
│
├── pipeline/                         # 跨阶段调度薄层（不承载业务逻辑）
│   ├── __init__.py
│   ├── refresh.py                    # ← source_management/refresh_service.py（先摘要→抽取→旧代回收→Wiki）
│   └── watcher.py                    # ← file_sources/watcher.py（轮询指纹，派发 document_refresh）
│
└── （其余模块不动）
    ├── knowledge_graph/              # + 收编 utils/data_store.py（EntityDataStore → 图写入）
    ├── cdc/                          # 增量同步，独立维持；仅改 import 指向
    ├── decision_engine/ · ontology/ · analysis_engine/ · model_management/
    ├── task_management/              # handler 瘦壳，业务核心全部归位组件
    ├── api/routes/                   # 路由瘦壳，数据访问归位 source_registry
    └── models/ · system/ · websocket/ · utils/
```

解体删除的目录：`document_processing/`、`content_summarization/`、`source_management/`、
`file_sources/`、`database_management/`（全部拆散归位，不留兼容 shim）。

---

## 3. 阶段数据契约（组件对外只依赖契约）

| 契约 | 位置 | 内容 | 消费方 |
|------|------|------|--------|
| SourceSpec | `source_registry` | kind=doc/db、id、根路径、来源 URI 根 | 所有阶段 |
| ExtractedDocument | `content_extraction/document/models.py` | 章节树 Section（title/level/text/page_start/page_end/children） | 摘要、（未来）提取 |
| DatabaseSchema | `content_extraction/database/models.py` | tables/columns/foreign_keys/views（dataclass，取代 handler 间裸 dict） | 摘要、导入 |
| 摘要 JSON | 文档 `data/summaries/DOC/{source_id}/{path}.json`<br>数据库 `data/summaries/DB/...` | `structure` 摘要树 / `content_hash` 指纹 / `doc_description`；库表概要 | 提取、检索、Wiki、决策引擎 |
| 图产出 | Neo4j 节点/边 | 两级来源（datasource/datasources）、代际佐证 `URI@content_hash` | Wiki、检索、回收 |
| wiki_pages | `models/wiki.py` | Markdown 正文 + source_refs + source_hash 幂等 | 前端 |

**约定：摘要文件与图谱数据的既有布局不变**——本轮是代码组织重构，不改变数据格式，
已有 `data/summaries` 与 Neo4j 产出继续有效（免重跑）。

---

## 4. 实施步骤（六个阶段，每阶段独立可验证）

> 原则：每阶段结束跑一遍集成测试 + 抽取质量基线；搬迁用文件移动 + 全局替换 import，
> 不改业务逻辑（除非明确标注「重构点」）。SQLite 可随时删库重建，无迁移负担。

### 阶段 1：`source_registry`（注册数据源）
1. 新建 `source_registry/document/`、`/database/` 骨架。
2. `api/routes/source.py` 的文档源 CRUD/软删/校验逻辑 → `document/registry.py`；路由只留薄壳。
3. `file_sources/base.py + local_source.py` → `document/file_source.py`；**重构点：**
   `local_source` 重写为调 `content_extraction.document`，删除 `document_processor.py`。
4. `database_manager.py` 的连接 CRUD/测连部分 → `database/registry.py`（DatabaseService 的 CRUD 并入）。
5. 新建 `pipeline/`，`refresh_service.py` → `pipeline/refresh.py`，`file_sources/watcher.py` → `pipeline/watcher.py`。
6. 验证：创建/列表/删除文档源与数据库连接接口回归；pytest。

### 阶段 2：`content_extraction` 拆分
1. 现 `content_extraction/*` → `content_extraction/document/*`（models/extract/md_parser/converters）。
2. `database_manager.extract_schema` → `content_extraction/database/schema_reader.py`；
   引擎构建/方言 → `connector.py`；**重构点：** DatabaseSchema 用 dataclass 契约替代 handler 裸 dict。
3. **功能补齐（待确认）：** `schema_reader` 增加视图提取（views/view_columns）。
4. 验证：三篇示例文档提取回归 + SQL Server/MySQL/SQLite schema 提取回归。

### 阶段 3：`summary_generation` 拆分
1. `content_summarization/*` → `summary_generation/document/*`。
2. `document_processing/summary_generator.py` → `summary_generation/document/store.py`；目录解散。
3. `schema_annotator.py` → `summary_generation/database/annotator.py`（prompts 随迁）。
4. **重构点：** `handlers/schema_analyze.py` 步骤4的概要落盘 → `summary_generation/database/store.py`，handler 瘦壳。
5. 验证：文档摘要任务、库表分析任务回归；`decision_engine/retrievers/summary_retriever.py`
   依赖的是 `data/summaries` 路径约定（布局不变，无 import 改动）。

### 阶段 4：`entity_extraction` 拆分
1. `source_management/source_service.py` 拆为 `document/chunker.py`（分段/切分/合并）+
   `document/service.py`（并发编排/去重）；`llm_entity_enhancer.py` → `document/extractor.py`，prompts 随迁。
2. `import_helpers.py` → `entity_extraction/database/importer.py`；
   `handlers/schema_import.py` 的行读取/导入核心 → `database/row_reader.py` + `importer.py`，handler 瘦壳。
3. `utils/data_store.py`（EntityDataStore）→ `knowledge_graph/entity_store.py`。
4. `source_management/` 目录解散。
5. **功能补齐（待确认）：** 文档侧实体属性提取并入 prompt/输出契约（依赖本体包 PropertyType），
   先跑 `tests/test_extraction_quality.py` 基线确认无退化。
6. 验证：文档抽取基线无退化；数据库导入任务回归；CDC 消费链路（event_processor 写图谱路径不变）。

### 阶段 5：`wiki_generation`
1. `wiki/` → `wiki_generation/`：service 保留顶层；`page_generator.py` 按「文档页/主题页」拆入
   `document/`，`entity_generator.py` → `entity/`；prompts 随迁。
2. 验证：文档页/主题页/实体页生成 + 孤儿清理回归。

### 阶段 6：收尾
1. 全局清点残留旧 import（`document_processing|content_summarization|source_management|file_sources|database_management|wiki\.`）→ 0 匹配为通过标准。
2. 更新文档：`docs/architecture.md`、`docs/data-flow.md`、`backend/AGENTS.md`、根 `AGENTS.md` 模块树。
3. 补组件级单测：chunker 合并逻辑、DatabaseSchema 契约、store 路径安全。
4. 删除残留 `__pycache__`，全量 pytest。

---

## 5. 受影响的消费方清单（import 面改动）

| 消费方 | 改动 |
|--------|------|
| `api/routes/source.py` / `database.py` / `wiki.py` | 数据访问收编后改调组件服务 |
| `task_management/handlers/*`（6 个） | 瘦壳化，业务核心归位组件 |
| `decision_engine/retrievers/summary_retriever.py` | 无 import 改动（仓位到 `data/summaries` 路径约定） |
| `cdc/cdc_manager.py`、`cdc/debezium_config.py`、`cdc/schema_cache.py` | import 指向 `source_registry` / `content_extraction.database.store` |
| `decision_engine/agentic/tools.py`（摘要树导航读 `data/summaries`） | 同上，路径约定不变 |
| `main.py` | watcher import 改为 `pipeline.watcher` |
| `tests/*` | import 同步；金标 `tests/golden/extraction_v1.json` 不受影响 |

---

## 6. 决策点（已于 2026-10-19 审核）

| # | 决策 | 结论 |
|---|------|------|
| D1 | 五组件归属 | **backend 顶层**（与现有模块布局一致，import 更短） |
| D2 | 旧解析器 `document_processor.py` | **删除**；`local_source` 重写为调 `content_extraction.document` |
| D3 | 失效传播 refresh/watcher 归属 | **独立 `pipeline/` 薄层**（跨阶段编排，不塞进任何单一组件） |
| D4 | 数据库视图提取 | **本轮补齐**：`schema_reader` 增加视图字段/依赖提取，DatabaseSchema 契约同步含 views |
| D5 | 文档侧实体属性提取是否本轮启用 | 倾向**启用**，但以抽取质量基线不退化为前提（实施阶段 4 时再定） |
| D6 | `utils/data_store.py` 移入 `knowledge_graph/` | **赞成**（图谱写入属存储层） |
| D7 | Wiki 暂不含数据库侧（库表页面） | 本轮不做；目录结构已预留扩展位 |

## 7. 风险与注意

- **import 面大**：约 15+ 消费文件跨 5 个阶段改动，逐阶段推进、每阶段全局 grep 清点。
- **uvicorn --reload 残留**：目录更名后旧 pycache 可能引出假报错，重启进程即可。
- **数据零迁移**：代码搬家不碰 `data/summaries` 结构与 Neo4j；只有新功能（视图、实体属性）才需要源端重跑。
- **CDC 与 schema_cache 的隐式依赖**：阶段 2、3 改 DatabaseService/manager 时必须同步改 cdc 三处 import，
  否则 CDC 配置链路静默断掉——列入每阶段 grep 清单。

---

## 8. 执行记录（已完成）

按阶段顺序落地，每阶段一个提交、独立可回退：

| 阶段 | 提交 | 内容 |
|------|------|------|
| 回退锚点 | `dc23961` | 移除 pageindex/mineru 旧实现，`content_extraction` 落地 |
| ① 注册数据源 | `22e1414` | `source_registry/{document,database}`、`pipeline/{refresh,watcher}`、`content_extraction/database`、`summary_generation/database` 落地；`file_sources/` 与 `source_management/refresh_service.py` 删除；各方言补 `extract_views`（D4） |
| ② 内容提取 | `3e0f8ee` | `content_extraction/*` → `content_extraction/document/*`（models/md_parser/converters） |
| ③ 摘要生成 | `a11a222` | `content_summarization/*` → `summary_generation/document/*`；`document_processing/` 与 `content_summarization/` 目录解散；`schema_annotator` → `summary_generation/database/annotator` |
| ④ 实体抽取 | `4dc6d4d` | `source_management/source_service` → `entity_extraction/document/{chunker,service}`；`llm_entity_enhancer` → `entity_extraction/document/extractor`；`database_management/` 解散（dialects → `content_extraction/database/dialects`、SchemaStore → `content_extraction/database/store`、import_helpers → `entity_extraction/database/importer`、行读取 → `entity_extraction/database/row_reader`）；**D5 启用**：跨批次属性合并 + 本体属性词表注入 prompt + 实体属性非空覆盖 |
| ⑤ Wiki 生成 | `78802e2` | `wiki/` → `wiki_generation/`（service 顶层；文档页/主题页 → `document/`，实体页 → `entity/`）；预留 `database/` 扩展位（D7） |
| ⑥ 收尾 | 本提交 | 清理残留引用与文档结构描述（`README.md`、`AGENTS.md`、`backend/AGENTS.md`、`docs/*`），全局 grep 旧目录名归零，全量测试 |

复核标准：全局 grep `document_processing|content_summarization|source_management|file_sources|database_management|wiki\.` 在代码中 0 匹配（本计划文档内的「改造前」引用除外）。
