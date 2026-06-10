# 开发指南 | Development Guide

## 1. 开发环境搭建

### 前置依赖

```bash
# Python 3.10+
python --version

# Node.js 18+
node --version

# Neo4j 4.4+ (Docker 方式)
docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/test1234 neo4j:4.4

# Redis 7+ (Docker 方式)
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

### 启动开发服务

```bash
# 后端 (热重载)
cd backend
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 中的数据库连接信息
uvicorn main:app --reload --port 8000

# 前端 (热重载)
cd frontend
npm install
npm run dev     # 监听 :5175
```

### 运行测试

```bash
# 确保后端运行在 localhost:8000

# 方式一：pytest
cd tests
pytest -v

# 方式二：集成测试脚本
python run-all-tests.py
```

---

## 2. 项目结构速览

```
OpenPalantir/
├── backend/
│   ├── main.py                  ← FastAPI 应用入口
│   ├── api/
│   │   ├── routes/              ← 8个路由模块 (graph/analysis/database/...)
│   │   └── task.py              ← 任务管理路由
│   ├── config/
│   │   ├── database.py          ← SQLite (SQLAlchemy Session)
│   │   └── neo4j_config.py      ← Neo4j 连接
│   ├── models/                  ← ORM 模型 (model/task/database/source)
│   ├── knowledge_graph/         ← 图谱 CRUD + 缓存 + 分区
│   ├── analysis_engine/         ← NetworkX 分析
│   ├── decision_engine/         ← 决策引擎 (插件化)
│   ├── document_processing/     ← 文档解析
│   ├── entity_extraction/       ← LLM 实体提取
│   ├── pageindex/               ← 文档摘要树
│   ├── database_management/     ← 外部 DB 连接管理
│   ├── model_management/        ← LLM 调用客户端
│   ├── task_management/         ← 异步任务管理
│   ├── file_sources/            ← 文件源抽象
│   ├── utils/                   ← 数据存储工具
│   └── system/                  ← 日志 + 系统集成
├── frontend/
│   └── src/
│       ├── App.tsx              ← 主入口 + 标签路由
│       ├── components/          ← 12个功能组件
│       ├── config/apiConfig.ts  ← API 配置
│       └── services/logger.ts   ← 前端日志
├── scripts/                     ← 安装/服务管理脚本
├── tests/                       ← 测试
└── docs/                        ← 文档
```

---

## 3. 如何添加新功能

### 3.1 添加新的 API 端点

1. 在 `backend/api/routes/` 创建或编辑路由文件：

```python
# backend/api/routes/new_feature.py
from fastapi import APIRouter, HTTPException
from system.logger import logger

router = APIRouter()

@router.get("/items")
async def list_items():
    logger.info("获取项目列表")
    return {"status": "success", "items": []}
```

2. 在 `backend/main.py` 注册路由：

```python
from api.routes import new_feature
app.include_router(new_feature.router, prefix="/api/new-feature", tags=["new-feature"])
```

### 3.2 添加新的决策领域插件

```python
# backend/decision_engine/plugins/my_domain_plugin.py
from decision_engine.plugins.base_decision_plugin import BaseDecisionPlugin
from decision_engine.contracts import DecisionRequest

class MyDomainPlugin(BaseDecisionPlugin):
    def run(self, request: DecisionRequest) -> dict:
        # 1. 查询图谱
        # 2. 查询数据库
        # 3. LLM 推理
        # 4. 返回结构化结果
        return { ... }

# 注册插件 (在 plugin_registry.py 或插件文件末尾)
from decision_engine.plugin_registry import plugin_registry
plugin_registry.register("my_domain", MyDomainPlugin)
```

### 3.3 添加新的前端组件

1. 在 `frontend/src/components/` 创建 `NewFeature.tsx`：

```tsx
import { useState } from 'react';
import { logger } from '../services/logger';

export default function NewFeature() {
  const [data, setData] = useState([]);
  // 组件逻辑...
  return <div>...</div>;
}
```

2. 在 `App.tsx` 导入并添加标签页。

---

## 4. 代码规范

### 4.1 Python

- 遵循 PEP 8，4 空格缩进
- 使用类型注解（函数参数和返回值）
- 使用 `logger.info/debug/error` 而非 `print()`
- 每个模块有简要的模块级 docstring
- 避免过度抽象，遵循 YAGNI 原则

```python
# 推荐
def get_entity(entity_id: str) -> dict | None:
    """获取实体，不存在返回 None"""
    return graph_manager.get_entity(entity_id)

# 不推荐
def get_entity(entity_id):
    # 这个函数用于获取实体
    result = graph_manager.get_entity(entity_id)
    return result
```

### 4.2 TypeScript/React

- 2 空格缩进
- 使用函数组件 + Hooks，避免 class 组件
- 组件文件名使用 PascalCase
- 使用 `logger.info(component, message)` 记录关键操作
- Props 使用 interface 定义类型

```tsx
// 推荐
interface Props {
  entityId: string;
  onUpdate?: (id: string) => void;
}

export default function EntityCard({ entityId, onUpdate }: Props) {
  // ...
}
```

### 4.3 提交信息格式

使用约定式提交：

```
feat: 添加用户认证功能
fix: 修复图谱节点重复创建的Bug
docs: 更新API文档
refactor: 重构实体提取模块
test: 添加决策引擎单元测试
chore: 升级依赖版本
```

---

## 5. 数据库操作

### 5.1 SQLite (应用元数据)

```python
from config.database import SessionLocal

db = SessionLocal()
try:
    # CRUD 操作
    db.add(item)
    db.commit()
finally:
    db.close()
```

### 5.2 Neo4j (图数据)

```python
from config.neo4j_config import neo4j_conn

# 执行 Cypher 查询
results = neo4j_conn.execute_query(
    "MATCH (n:Entity {type: $type}) RETURN n LIMIT $limit",
    {"type": "人物", "limit": 10}
)

# 使用 GraphManager (推荐)
from knowledge_graph.graph_manager import graph_manager
entity = graph_manager.get_entity(entity_id)
entities, total = graph_manager.list_entities_with_pagination(...)
```

---

## 6. 调试技巧

### 后端日志

```bash
# 实时查看日志
tail -f logs/backend.log

# 或在代码中
from system.logger import logger
logger.info(f"变量值: {some_var}")
```

### API 调试

- 访问 `http://localhost:8000/docs` 使用 Swagger UI 交互式测试 API
- 访问 `http://localhost:8000/redoc` 查看更详细的 API 文档

### 前端调试

- 浏览器 DevTools → Console（查看前端日志）
- Vite 会显示组件热重载状态

### 清理数据库

```powershell
# 删除 SQLite 应用数据库
del backend\data\sqlite\database.db

# 关闭 Neo4j 进程后删除图数据库
taskkill /F /IM python.exe
# 重启后端自动重建表结构
```

---

## 7. 常见问题

**Q: 启动报错 `No module named 'xxx'`**
A: 检查 `pip install -r requirements.txt` 是否完整执行，确保 Python 版本 ≥ 3.10。

**Q: Neo4j 连接失败**
A: 确认 Neo4j 服务已启动（`docker ps | grep neo4j`），检查 `backend/.env` 中的连接信息。

**Q: 前端热重载不生效**
A: Vite 默认监听 `:5175`，确认浏览器访问的是此端口。清除浏览器缓存试试。

**Q: LLM 调用超时**
A: 修改模型配置中的超时时间（默认 600s），或检查 API 端点是否可达。
