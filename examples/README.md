# 示例数据集 | Examples

这里是「一键 demo」的素材：三篇互相引用的虚构文档 + 一个示例社区本体包。全部内容虚构，可自由复制修改。

```
examples/
├── docs/                    # 示例文档（Markdown，同主题跨文档）
│   ├── 组织架构说明.md        # 人员 / 小组 / 职级 / 汇报关系
│   ├── 季度评审记录.md        # 评审事件、结论、待办
│   └── 发布与CI手册.md        # 系统组件、负责人、依赖与稳定性指标
└── ontology/
    └── rd_efficiency.yaml   # 示例社区本体包（extends: workforce）
```

三篇文档故意共享同一批实体（张明、李芳、周雨、平台工程部、数据平台组、指标服务、CI 流水线……），这样才能看出 Wiki 的两级生成：**文档页**按 PageIndex 摘要树改写，**跨文档主题页 / 实体页**把散落在多篇文档里的同一实体聚合成一页。

## 一键跑通

后端与 Neo4j 已启动、且「模型管理」里有一个**已启用且可连接**的模型时：

```bash
python scripts/demo/run_demo.py              # Linux / macOS
powershell scripts/demo/run-demo.ps1         # Windows
```

脚本依次做七件事，任何一步失败都会打印可执行的修复提示：

| 步骤 | 接口 | 说明 |
|------|------|------|
| 1 | `GET /` · `GET /api/model/models` | 确认后端在线、有可用模型（否则抽取直接 503） |
| 2 | `POST /api/ontology/packs` | 导入 `rd_efficiency.yaml`，词表即刻进 prompt（默认落盘，重启仍在） |
| 3 | `GET/POST /api/sources` | 以 `examples/docs` 为路径建文档源，已存在则复用 |
| 4 | `POST /api/sources/{id}/summarize` | 逐篇生成层级摘要树，轮询 `GET /api/task/{task_id}` |
| 5 | `POST /api/sources/{id}/extract` | 按域 `rd_efficiency` 抽取实体与关系，predicate 走本体归一化后写 Neo4j 类型化边 |
| 6 | `POST /api/wiki/generate` | 生成文档页 + 主题页 + 实体页 |
| 7 | `GET /api/ontology/report` | 打印图谱规模、兜底谓词占比与治理结论 |

常用参数：

```bash
python scripts/demo/run_demo.py --domain workforce --no-pack   # 只用内置域
python scripts/demo/run_demo.py --no-persist                    # 本体包不留盘
python scripts/demo/run_demo.py --docs /path/to/你的文档 --timeout 1800
python scripts/demo/run_demo.py --help
```

跑完在 http://localhost:5175 看结果：「知识Wiki」标签页浏览与编辑页面，「图谱可视化」看类型化边，「智能决策」提问并带引用（「就本页提问」会把页面 scope 带过去）。

## 换成自己的文档

把 `--docs` 指向任何本地目录即可（支持 `.md/.txt/.pdf/.docx`，PDF/Word 需要 MinerU 或对应解析依赖，见 [INSTALL.md](../INSTALL.md)）。文档主题与本体域越贴近，`fallback_ratio` 越低——这正是 `GET /api/ontology/report` 里 `alias_candidates` 要回答的问题：哪些原始谓词高频掉进兜底，该补进哪个 LinkType 的 `aliases`。

写自己的领域包见 [docs/ontology-guide.md](../docs/ontology-guide.md) 第 6 节。
