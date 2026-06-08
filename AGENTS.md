# 仓库指南

始终使用简体中文回复。

## 项目结构 & 模块组织

本项目采用**前后端分离**架构：

- **`backend/`** -- Python FastAPI 服务端，按领域模块组织：
  - `api/routes/` -- REST API 端点定义
  - `config/` -- 数据库连接、Neo4j、Celery 和环境配置
  - `document_processing/` -- 文档解析（PDF、Word、MD、图片）
  - `entity_extraction/` -- 基于 LLM 的实体与关系抽取
  - `knowledge_graph/` -- Neo4j 图谱操作（CRUD、分区、性能优化）
  - `analysis_engine/` -- 图谱分析（路径、社区、中心性、趋势）
  - `decision_engine/` -- 对话式决策推理内核
  - `database_management/` -- 数据库 Schema 标注与管理
  - `model_management/` -- LLM 模型客户端集成
  - `task_management/` -- 异步任务队列与状态跟踪
  - `models/` -- SQLAlchemy ORM 模型与资源标识符
  - `utils/` -- 通用工具函数
- **`frontend/`** -- React + TypeScript + Vite 单页应用
- **`tests/`** -- 测试套件（pytest）
- **`scripts/`** -- 服务管理脚本（启动/停止 Neo4j、Redis）
- **`data/`** -- 运行时数据（SQLite 数据库、摘要、上传文件）
- **`docs/`** -- 项目文档

## 构建、测试和开发命令

```bash
# 后端
cd backend && pip install -r requirements.txt
uvicorn main:app --reload --port 8001

# 前端
cd frontend && npm install
npm run dev      # Vite 开发服务器（端口 5175）
npm run build    # TypeScript 检查 + Vite 生产构建
npm run lint     # 对 .ts/.tsx 文件运行 ESLint

# 服务（PowerShell）
scripts/service/start-services.ps1   # 启动 Neo4j + Redis
scripts/service/stop-services.ps1    # 停止 Neo4j + Redis

# 测试（后端必须在 localhost:8001 运行）
cd tests && pytest
python run-all-tests.py              # 集成测试 + 报告
```

## 编码风格 & 命名规范

- **Python**: 遵循 PEP 8，4 空格缩进。使用类型注解。倾向于编写清晰自文档化的代码，而非过多内联注释。
- **TypeScript/React**: 2 空格缩进。使用函数式组件与 Hooks。配置的 ESLint 规则必须通过（`max-warnings 0`）。
- **格式化工具**: Prettier，配置为 `{ semi: true, singleQuote: true, printWidth: 100, trailingComma: "all", tabWidth: 2 }`。
- **EditorConfig** 应用于整个项目（`.editorconfig`）；确保你的编辑器已加载它。
- **Naming patterns**:
  - Python modules/files: `snake_case.py`
  - TypeScript/React files: `PascalCase.tsx` for components, `camelCase.ts` for utilities
  - Resource IDs: `{TYPE}://{UUID}/{path}` (e.g., `DOC://a1b2.../document.md`)
  - Entity IDs: MD5(`{name}_{type}`) -- 32-char hex
  - Relationship IDs: MD5(`{subject}_{predicate}_{object}`) -- 32-char hex
  - Conversation session IDs: `sess_` + uuid4.hex[:12]

## 测试指南

- **测试框架**: 后端测试使用 pytest。
- **覆盖率**: 为新功能和 Bug 修复添加测试。提交前确保所有现有测试通过。
- **执行方式**: 在 `localhost:8001` 启动后端，然后运行 `cd tests && pytest` 或 `python run-all-tests.py` 执行完整的集成测试套件。
- **测试命令**: 不要在 bash 测试命令中包含 `#` 内联注释。避免在 `cd` 后使用输出重定向。

## 提交 & Pull Request 指南

使用 **Conventional Commits（约定式提交）** 格式：

| Prefix      | Purpose              |
|-------------|----------------------|
| `feat:`     | 新功能                |
| `fix:`      | Bug 修复             |
| `docs:`     | 文档                 |
| `style:`    | 代码格式调整           |
| `refactor:` | 代码重构              |
| `test:`     | 测试新增              |
| `chore:`    | 构建/工具变更          |

**分支命名**: `feature/your-feature`、`fix/your-bugfix`。

**PR 要求**：
- 清晰的描述，说明变更的*原因*（而不仅仅是*内容*）。
- 关联相关 Issue。
- 等待 CI 通过。
- 合并前需要至少一位维护者审查。

## 安全 & 配置提示

- **`.env` 文件**：后端配置位于 `backend/.env`。切勿提交密钥。使用 `.env.example` 作为模板。
- **API 配置**：前端 API 端点在 `frontend/src/config/apiConfig.ts` 中设置。
- **数据库重置**：删除 `backend/data/sqlite/database.db` 并重启；Schema 将自动重建。如果数据库被锁定，先运行 `taskkill /F /IM python.exe`。
- **日志**：后端日志写入 `./logs/backend.log` —— 调试后端问题时请首先检查该文件。
