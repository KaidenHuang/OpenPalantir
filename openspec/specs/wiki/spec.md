# wiki 能力规格

## Purpose

Wiki 是系统的**内容出口**：把散落在多篇文档里的知识由 LLM 聚合改写成可编辑、可引用、可发布的一等页面，而不是只读的摘要树。

## Requirements

### Requirement: 三级页面生成

系统 SHALL 以摘要树为素材生成三类页面：文档页（单文档内按摘要节点聚合改写）、主题页（跨文档同主题合并）、实体页（按本体实体聚合该实体在所有来源中的出现）。

#### Scenario: 全量生成

- **WHEN** `POST /api/wiki/generate` 提交 `{"scope": "all"}`
- **THEN** 返回 `task_id`，任务完成后每篇已摘要文档至少一个文档页，跨文档共享实体的主题产出主题页与实体页
- **AND** `GET /api/wiki/pages` 返回的每项含 `page_id` / `kind` / `title` / `status` / `updated_at`

#### Scenario: 只生成某实体的页面

- **WHEN** 提交 `{"entity_id": "<实体ID>"}`
- **THEN** 任务只重建该实体页，不动其他页面

### Requirement: 页面引用锚点

每个页面的段落 SHALL 携带指向摘要节点（`node_id`）的引用，使结论可回跳到原文位置。

#### Scenario: 兜底谓词的引用可读

- **WHEN** 实体页渲染一条归一化为「其他」的关系
- **THEN** 该行附带原始谓词标注（`（原文：…）`），不伪装成受控关系

### Requirement: 页面可编辑与状态流转

页面 SHALL 是一等内容资产，支持人工改写而不被下次自动生成静默覆盖。

#### Scenario: 编辑保存

- **WHEN** `PUT /api/wiki/pages/{page_id}` 提交 `{"title": ..., "content": ...}`
- **THEN** 返回更新后的页面，`updated_at` 前进

#### Scenario: 发布

- **WHEN** `POST /api/wiki/pages/{page_id}/status` 提交 `{"status": "published"}`
- **THEN** 页面状态变为 published；提交其他值返回 400

### Requirement: 问答答案沉淀为页面

系统 SHALL 允许把带引用的问答回答发布为新页面，形成「问一次 → 沉淀下来」的闭环。

#### Scenario: 发布回答

- **WHEN** `POST /api/wiki/publish_answer` 提交 `{"question", "answer", "citations"}`
- **THEN** 创建新页面并保留 citations；`answer` 为空白返回 400

### Requirement: 内容失效传播

源文档内容变更 SHALL 传播到摘要、图谱与 Wiki，不需要人工介入。

#### Scenario: 文档被改写

- **WHEN** 源文件内容 hash 与摘要 JSON 记录的不一致，`GET /api/sources/{id}/stale` 列出该文件
- **AND** `POST /api/sources/{id}/refresh` 依次重跑摘要 → 回收该来源的旧实体关系 → 重新抽取 → 刷新相关页面并清理孤儿页

### Requirement: 生成任务异步化

Wiki 生成 SHALL 走统一异步任务队列，长文生成不受单次响应限制。

#### Scenario: 轮询进度

- **WHEN** `GET /api/task/{task_id}` 查询运行中的生成任务
- **THEN** 返回 `status` 为 pending/running/completed/failed 之一，失败时带 `error`
