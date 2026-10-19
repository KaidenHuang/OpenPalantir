# 贡献指南 | Contributing Guide

感谢你对 OpenPalantir 的关注！我们欢迎任何形式的贡献。

## 行为准则

本项目遵循 [贡献者公约](CODE_OF_CONDUCT.md)。参与即表示你同意遵守其条款。

## 如何贡献

### 报告 Bug

1. 在 [Issues](../../issues) 中搜索，确认 Bug 未被报告
2. 使用 Bug Report 模板创建新 Issue
3. 清晰描述：复现步骤、预期行为、实际行为、环境信息

### 提出功能建议

1. 在 [Issues](../../issues) 中搜索，确认建议未被提出
2. 使用 Feature Request 模板创建新 Issue
3. 说明：使用场景、期望行为、备选方案

### 提交代码

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 编写代码并添加测试
4. 确保测试通过：`cd tests && pytest`
5. 提交变更：`git commit -m "feat: add your feature"`
6. 推送到分支：`git push origin feature/your-feature`
7. 创建 Pull Request

### 提交信息规范

使用约定式提交格式：

- `feat:` — 新功能
- `fix:` — Bug 修复
- `docs:` — 文档更新
- `style:` — 代码格式（不影响功能）
- `refactor:` — 代码重构
- `test:` — 测试相关
- `chore:` — 构建/工具变更

### 代码风格

- **Python**: 遵循 PEP 8，使用类型注解
- **TypeScript/React**: 遵循 ESLint 配置，使用函数组件 + Hooks
- 保持代码简洁，避免过度抽象
- 不要添加不必要的注释（代码应自解释）

### 开发环境设置

```bash
# 后端
cd backend
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 配置数据库连接

# 前端
cd frontend
npm install
npm run dev
```

### 测试

```bash
# 确保后端运行在 localhost:8000
cd tests
pytest

# 或运行抽取质量基线（模型管理里没有可用模型时自动 skip）
pytest test_extraction_quality.py -v -s
```

## 贡献领域本体包（最欢迎的贡献）

本体包是纯 YAML，不需要改代码就能扩展系统能力。最有价值的包是**挂在内置域之上的增量**：

```yaml
name: rd_efficiency
description: 研发效能领域本体
extends: workforce          # 复用内置域的 employee/任职于/管理，只写自己的部分

object_types:
  - key: system_component
    display_name: 系统组件
    parent: concept

link_types:
  - key: 维护
    domain: [person, organization]
    range: [system_component]
    inverse: 维护者
    aliases: [负责维护, 运维]   # 同一语义的不同说法进别名，别开新 key
```

自查方式（本地起后端即可）：

```bash
jq -Rs '{yaml: ., persist: true}' 你的包.yaml | \
  curl -X POST http://localhost:8000/api/ontology/packs \
       -H 'Content-Type: application/json' -d @-
python scripts/demo/run_demo.py --domain 你的包名 --docs examples/docs
curl http://localhost:8000/api/ontology/report
```

报告里 `fallback_ratio` 高 → 补 aliases；`unused_link_types` 多 → 词表写宽了。规则细节与校验口径见 [docs/ontology-guide.md](docs/ontology-guide.md)。

## 变更讨论

涉及**能力边界**的改动（新增接口族、改数据模型、调整某条链路的职责）请先在 Issue 里说明动机、影响面与取舍，达成一致后再动手；纯 bug 修复和文档不需要。

项目的硬约束决定了改动被接受的程度：**不做向后兼容与数据迁移**（Schema 变更直接删库重建）、**词表只有一个来源**（本体注册表，不要再建一份配置）、**治理只读**（报告不改图谱）。与这些冲突的方案请先在 Issue 里讨论。

## Pull Request 流程

1. 确保 PR 描述清晰，说明变更的"为什么"而非"是什么"
2. 关联相关 Issue
3. 等待 CI 通过
4. 至少需要一位维护者审核通过
5. 维护者合并 PR

## 问题反馈

如有问题，请通过 [Issues](../../issues) 反馈。
