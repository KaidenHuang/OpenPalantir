# ontology 能力规格

## Purpose

本体是图谱可分析的前提：实体类型、关系谓词、定义域/值域由可插拔的 YAML 包统一定义，文档与数据库两条导入路径共用同一套词表，并有治理报告持续检验词表是否真的被用起来。

## Requirements

### Requirement: 包加载即校验，任一非法整体拒绝

系统 SHALL 在加载与运行期导入时执行同一条校验链，社区包与内置包标准一致。

#### Scenario: 悬空引用

- **WHEN** 包内 `ObjectType.parent`、`LinkType.domain`/`range` 或 `inverse` 引用了父视图与本包并集之外的 key
- **THEN** 抛出 `OntologyError`，该包不注册，注册表 `version` 不前进

#### Scenario: 缺少基底包

- **WHEN** 包目录里没有 `general`
- **THEN** 加载失败，服务不带着半套词表启动

### Requirement: 域视图与 extends 扩展链

域视图 SHALL 为 `general ⊕ extends 链 ⊕ 本包`，同 key 覆盖、新 key 追加；`extends` 的包相对**父视图**校验，因此可引用父包定义的类型。

#### Scenario: 扩展包只写增量

- **WHEN** 导入 `examples/ontology/rd_efficiency.yaml`（`extends: workforce`）
- **THEN** `object_types("rd_efficiency")` 同时含 workforce 的 `employee` 与自己的 `system_component`
- **AND** `link_types("rd_efficiency")` 同时含 `任职于` 与 `维护`

#### Scenario: 扩展链非法

- **WHEN** `extends` 指向不存在的包，或形成环（含自指）
- **THEN** 抛 `OntologyError` 并指明缺失包名或成环包名

#### Scenario: 未知域

- **WHEN** 以未注册的 `domain` 请求词表
- **THEN** 回落到 `general` 视图（不报错，保证抽取链路可用）

### Requirement: 谓词归一化先于 ID 计算

任意来源的关系谓词 SHALL 先映射到受控 key（exact → 别名，大小写与空白不敏感 → 兜底「其他」），再参与 `relationship_id` 计算。

#### Scenario: 同义词落同一条边

- **WHEN** 「负责平台」与「管理平台」两条抽取结果主语宾语相同
- **THEN** 归一化后 key 相同，`relationship_id = MD5(subject_受控key_object)` 一致，图谱只有一条边

#### Scenario: 兜底不丢信息

- **WHEN** 谓词无法归一
- **THEN** key 为「其他」且原始值保存在 `raw_predicate`，供治理报告的别名候选使用

### Requirement: 类型化边与 Cypher 注入防护

Neo4j 边类型 SHALL 为受控 LinkType key，插值前经白名单校验。

#### Scenario: 非法类型名被拒

- **WHEN** `cypher_rel_type` 收到不在词表内的值、空值，或含反引号的值
- **THEN** 抛 `OntologyError`，不拼进 Cypher

### Requirement: 词表变更即时生效

本体注册表 SHALL 维护 `version`，导入/reload 成功即自增；抽取与标注 prompt 以 `(version, domain)` 为缓存键。

#### Scenario: 社区包无需重启

- **WHEN** 运行期 `POST /api/ontology/packs` 导入含新谓词的包
- **THEN** 下一次抽取的 prompt 已包含该谓词，无需重启进程

#### Scenario: 词表未变

- **WHEN** 注册表 `version` 未变时重复渲染同一 domain 的 prompt 段
- **THEN** 命中缓存，返回同一对象

### Requirement: 包导入导出等价

导出 SHALL 产出与人手写的 YAML 同构的文本，且可原样回读。

#### Scenario: 回读

- **WHEN** `export_pack(domain)` 的文本再次 `import_pack`
- **THEN** 解析出的包与原包相等（含 `extends` 字段）

#### Scenario: 落盘与基底保护

- **WHEN** `import_pack(text, persist=True)`
- **THEN** 写入 `backend/data/ontology_packs/<name>.yaml`，重启后仍在；对 `general` 的 persist 导入被拒绝

### Requirement: 两条导入路径共用一套词表

文档抽取与数据库 Schema 标注 SHALL 从同一注册表生成枚举，产出可互相比较的 predicate。

#### Scenario: prompt 对齐

- **WHEN** 分别构造文档抽取与 DB 标注的 prompt（同一 domain）
- **THEN** 该 domain 视图的每个 LinkType key 都出现在两边

### Requirement: 只读治理报告

系统 SHALL 提供聚合只读的治理报告，不修改图谱。

#### Scenario: 报告字段

- **WHEN** `GET /api/ontology/report`
- **THEN** 返回 `domains` / `vocabulary` / `object_types` / `domain_range_violations` / `structure_issues` / `alias_candidates` / `findings`
- **AND** 带 `domain` 与 `with_pack` 时附 `pack`（该域包 YAML）

#### Scenario: 约束口径

- **WHEN** 同一谓词在多个域包声明了不同 `domain`/`range`
- **THEN** 校验取并集，任一包声明不限则整体不限，避免误报存量数据
