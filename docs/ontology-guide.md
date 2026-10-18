# 本体指南 | Ontology Guide

OpenPalantir 的图谱不是「自由文本关系」的堆砌，而是由**受控本体（Ontology）**约束的：实体类型、关系谓词、定义域/值域都来自可插拔的 YAML 本体包。本文档说明本体如何影响数据落地、如何写自己的领域包、以及如何用治理报告持续改进词表。

---

## 1. 为什么要受控本体

自由谓词的图谱不可分析：`任职于` / `就职在` / `works at` 会被当成三种关系，路径查询与社区发现直接失真。受控本体做三件事：

| 能力 | 效果 |
|------|------|
| 统一词表 | 抽取与标注的 prompt 从同一个注册表生成枚举，文档与数据库两条导入路径对齐同一本体 |
| 谓词归一化 | 任意 LLM 输出先映射到受控 key，再参与 ID 计算，同一语义只有一条边 |
| 定义域/值域 | 关系的主语/宾语类型有约束，治理报告能查出违规数据 |

---

## 2. 概念与数据模型

| 概念 | 类 | 说明 |
|------|-----|------|
| ObjectType | `ontology/types.py:ObjectType` | 实体类型，支持单继承（`parent` 指向另一个 key），带 `color` / `sort_order` 供前端着色 |
| LinkType | `ontology/types.py:LinkType` | 受控谓词。`domain`/`range` 是合法主语/宾语类型列表（**空列表 = 不限**），`symmetric` 表示无向，`inverse` 指向反向谓词，`aliases` 是归一化同义词 |
| PropertyType | `ontology/types.py:PropertyType` | 类型级属性声明（`key` / `data_type` / `description`） |
| OntologyPack | `ontology/types.py:OntologyPack` | 一个领域的包：`name` + `description` + 两类类型集合 + 可选 `extends` |

`name` 即 `domain` 参数取值。`general` 是**基底包**，其余域包在它之上扩展（同 key 覆盖、新 key 追加）。

包还可以声明 `extends: <另一个包名>` 挂在某个域包之上，形成扩展链：

```
general ⊕ workforce ⊕ rd_efficiency        # extends: workforce 的社区包
```

域视图按链条自基底往下逐层合并，因此**扩展包只写增量**——`examples/ontology/rd_efficiency.yaml` 只声明了 `system_component` / `review` 两个类型和三个谓词，`employee`、`任职于`、`管理` 这些 workforce 的词表照旧可用。这是「在别人的域上补自己的领域」的贡献方式，比整包 fork 更不易漂移。

---

## 3. 包文件与加载顺序

```
backend/ontology/packs/*.yaml       ← 内置包：general / workforce / finance / medical
backend/data/ontology_packs/*.yaml  ← 社区与自定义包（运行时目录，同名覆盖内置）
```

- 加载由 `OntologyRegistry.load()` 完成，**内置与用户包走同一条 `validate_pack()` 校验链**，社区包的验收标准与内置包完全一致。
- 缺少 `general` 或任一包非法 → 直接抛 `OntologyError`，服务不会带着半套词表启动。
- `backend/data/` 已被 `.gitignore` 忽略：本体包是本地运行数据。要把包贡献回社区，请提交到 `backend/ontology/packs/`。

校验规则（任一不满足即拒绝整个包）：

1. `object_types` / `link_types` 内部不得重复 key；
2. `ObjectType.parent` 必须存在（父视图 + 本包的并集内）；
3. `LinkType.domain` / `range` 里的每个类型必须存在；
4. `LinkType.inverse` 必须已在词表中定义；
5. `extends` 指向的包必须存在，且扩展链不得成环（自指或 A↔B 都会在加载时抛 `OntologyError`）。

有 `extends` 时，校验的「基底」是**父包的视图**而非 general——所以扩展包可以直接引用父包定义的类型（如 `warehouse_ops` 的 `装载于` 用 `range: [shipment, warehouse]`，这两个类型来自它 extends 的 `logistics`）。

---

## 4. 本体如何改变落库的数据

```
LLM 产出 (subject, predicate, object)
        │
        ▼  ontology/predicates.normalize_predicate(raw)
   exact key → aliases（大小写、空白不敏感）→ 未命中则兜底「其他」
        │  返回 (受控 key, 是否命中词表)
        ▼
relationship_id = MD5(subject + 受控key + object)     ← 归一化**先于**算 ID
        │
        ▼  ontology/predicates.cypher_rel_type(key)
Neo4j 边类型 = `受控key`                              ← 白名单校验，非词表值拒绝（防注入）
        └─ 兜底时原始谓词保存在 r.raw_predicate，供治理报告统计
```

要点：

- **ID 稳定**：因为 predicate 已归一，同一语义关系不管 LLM 用哪个同义词，都落在同一条边上。
- **边类型即谓词**：`MATCH ()-[r:任职于]->()` 是合法查询，图谱可直接按关系类型做路径与模式分析。
- **不丢信息**：兜底为「其他」的边保留 `raw_predicate`，治理报告据此提示该补哪些 alias。
- **三条写入路径共用**：文档抽取（`utils/data_store.py`）、数据库行级导入（`task_management/handlers/schema_import.py`）、CDC 增量（`cdc/event_processor.py`）都经同一个 `canonical_rel_id`。

---

## 5. API 用法

```bash
# 有哪些域包
curl http://localhost:8000/api/ontology/domains

# 导出某包（导出的 YAML 可原样再导入）
curl http://localhost:8000/api/ontology/packs/medical

# 导入社区包（persist=true 落盘到 backend/data/ontology_packs/，重启仍在）
curl -X POST http://localhost:8000/api/ontology/packs \
     -H 'Content-Type: application/json' \
     -d '{"yaml": "name: logistics\ndescription: 物流\nlink_types:\n  - key: 存放于\n", "persist": true}'

# 直接把 YAML 文件提交上去（jq 把文件内容包成 JSON 字符串字段）
jq -Rs '{yaml: ., persist: true}' examples/ontology/rd_efficiency.yaml | \
  curl -X POST http://localhost:8000/api/ontology/packs \
       -H 'Content-Type: application/json' -d @-

# 手工改过 packs 目录后热加载
curl -X POST http://localhost:8000/api/ontology/reload

# 治理报告
curl 'http://localhost:8000/api/ontology/report?domain=workforce&limit=50'
```

导入成功即令 `registry.version` 自增，而抽取/标注 prompt 的缓存键是 `(version, domain)`——**新词表下一条文档就生效，不需要重启进程**。校验失败则 400 且不注册，运行中的词表不受影响。

抽取时通过 `domain` 参数选包：

| 接口 | domain 位置 |
|------|------------|
| `POST /api/sources/{id}/extract` | body `{"domain": "workforce"}` |
| `POST /api/sources/{id}/refresh` | body `{"file": "...", "domain": "workforce"}` |
| `POST /api/database/{connection_id}/analyze` | body `{"domain": "finance"}` |
| `POST /api/decision/ask` | body `{"domain": "medical"}`（问答的实体类型词表同样取自注册表） |

---

## 6. 写一个领域包

最小可用包（只有 `name` 必填，其余可省）：

```yaml
name: logistics
description: 物流领域实体与受控关系

object_types:
  - key: shipment
    display_name: 运单
    description: 一次运输任务
    color: "#F5B041"
    sort_order: 10
  - key: warehouse
    display_name: 仓库
    parent: location            # 继承基底包的地点类型，前端复用其色系层级
    sort_order: 20

link_types:
  - key: 存放于
    display_name: 存放于
    description: 运单当前存放的仓库
    domain: [shipment]           # 主语只能是运单（含其子类型需自行列全）
    range: [warehouse]           # 空列表 = 不限
    aliases: [入库到, 存放在]     # 归一化同义词
  - key: 关联运单
    display_name: 关联运单
    symmetric: true              # 无向关系
```

写包的建议：

1. **优先复用基底词表**。`general` 已含 `包含/属于/引用/关联/亲属/依赖/其他` 及逆词，能用就别新造。
2. **能 extends 就别 fork**。已有内置域（workforce/finance/medical）接近你要的，就 `extends: workforce` 只补增量；整份 copy 出来的包在内置包更新后就漂移了。
3. **别名比新谓词便宜**。同一语义的多种说法应写进 `aliases`，而不是开新 key——否则词表膨胀、边被拆散。
4. **定义域别写太死**。`domain`/`range` 只列实际会出现的类型，或干脆留空表示不限；写窄了会让合法数据在治理报告里全是违规。
5. **成对谓词要互指 `inverse`**（如 `包含 ↔ 属于`），否则查询时得手写两遍方向。

挂在工作力域上的扩展包示例（与仓库里的 `examples/ontology/rd_efficiency.yaml` 同构）：

```yaml
name: rd_efficiency
description: 研发效能领域本体
extends: workforce            # 继承 employee/department + 任职于/管理 等词表

object_types:
  - key: system_component
    display_name: 系统组件
    parent: concept           # 基底包的类型同样可用
  - key: review
    display_name: 评审
    parent: event

link_types:
  - key: 维护
    domain: [person, organization]
    range: [system_component]
    inverse: 维护者
    aliases: [负责维护, 运维]
```

---

## 7. 治理报告怎么读

`GET /api/ontology/report` 的分组与对应的整改动作：

| 字段 | 含义 | 该做什么 |
|------|------|---------|
| `vocabulary.fallback_ratio` | 兜底为「其他」的边占比 | 偏高说明词表覆盖不足，看 `alias_candidates` 补别名或补 key |
| `vocabulary.unused_link_types` | 定义了却从未使用的谓词 | 确认场景不需要就删掉，别留死词表 |
| `vocabulary.undeclared_predicates` | 词表外的谓词仍在图里 | 早期数据或词表变更后残留，重新抽取即可归一 |
| `object_types.illegal_types` | 不在本体里的实体类型 | 老数据或手工写入；改包或重抽取 |
| `object_types.unused_types` | 从未落到任何实体上的类型 | 词表虚设，考虑精简 |
| `domain_range_violations` | 谓词的（主语类型, 宾语类型）不合法 | 判断是抽取错还是词表写窄了 |
| `structure_issues.isolated_entities` | 无任何边的实体 | 抽取噪声，考虑回收 |
| `structure_issues.placeholder_entities` | CDC 外键建的占位节点 | 源数据补齐后会 MERGE 命中 |
| `structure_issues.entities_without_source` / `edges_without_source` | 没有来源佐证的节点/边 | 归属链路有洞，无法按来源回收 |
| `alias_candidates` | 同一受控谓词下的原始说法排行 | 高频 raw 值补进 `aliases` |

`findings` 是上述问题拼成的人话结论，前端与脚本都可直接展示。

**治理是只读的**：报告只跑聚合查询，不修改图谱。整改靠「改包 → reload → 重新抽取/刷新文档」这条链路完成。

---

## 8. 与 Wiki 的关系

Wiki 实体页按本体类型组织实体档案，关系段落的谓词就是 LinkType key，兜底关系会附上原始谓词（`（原文：…）`）。因此本体越准，实体页越像「百科条目」；词表散乱时页面会退化成同义关系罗列——治理报告正是为了把它拉回来。

---

## 9. 常见问题

**改了 packs 里的 YAML 但没生效？** 内置包改动需 `POST /api/ontology/reload`；`backend/data/ontology_packs/` 下的同名包会覆盖内置包，先确认没有-shadow。

**能不能覆盖 `general`？** 可以——把改过的 `general.yaml` 放进 `data/ontology_packs/`（文件级覆盖）。但 API 的 `persist` 导入**禁止**覆盖基底包，避免运行期把词表改坏。

**谓词为什么全是中文？** 词表 key 就是 Neo4j 边类型，团队约定用中文谓词贴合中文文档；key 也可用英文，只要同一个包内一致。

**LLM 完全没用受控词表怎么办？** 全部落到「其他」，`fallback_ratio` 会接近 1。检查抽取 prompt 是否注入了目标 domain 的枚举（`ontology/prompt.py`），以及 `domain` 参数是否传对。

**`extends` 的包还没导入会怎样？** 校验直接失败（`本体包 extends 的包不存在: xxx`），不会静默退化到基底。所以发布扩展包时要说明它依赖哪个包；示例包 `rd_efficiency` 依赖内置 `workforce`，后者始终随仓库提供。
