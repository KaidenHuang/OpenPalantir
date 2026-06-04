# 部署指南 | Deployment Guide

## 1. Docker 部署（推荐）

### 1.1 前置条件

- Docker 20.10+
- Docker Compose 2.0+

### 1.2 部署步骤

```bash
# 1. 克隆代码
git clone https://github.com/your-org/OpenPalantir.git
cd OpenPalantir

# 2. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，修改以下配置：
#   - NEO4J_PASSWORD: Neo4j 密码 (必须设置，与 docker-compose.yml 中的一致)
#   - 根据需要配置 LLM API 密钥

# 3. 启动所有服务
NEO4J_PASSWORD=your_strong_password docker-compose up -d

# 4. 查看启动状态
docker-compose ps

# 5. 查看日志
docker-compose logs -f backend
```

### 1.3 服务端口

| 服务 | 端口 | 用途 |
|------|------|------|
| frontend | 5175 | Web 前端界面 |
| backend | 8001 | REST API |
| Neo4j Browser | 7474 | 图数据库管理界面 |
| Neo4j Bolt | 7687 | 图数据库连接协议 |
| Redis | 6379 | 缓存和消息队列 |

### 1.4 常用命令

```bash
# 停止服务
docker-compose down

# 停止并删除数据卷
docker-compose down -v

# 重新构建镜像
docker-compose build --no-cache

# 重启单个服务
docker-compose restart backend

# 进入容器调试
docker-compose exec backend bash
```

---

## 2. 手动部署

### 2.1 环境准备

#### 安装 Python 依赖

```bash
cd backend
python -m venv venv
source venv/bin/activate    # Linux/Mac
# venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

#### 安装 Neo4j

**Docker 方式（推荐）**：
```bash
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  -v neo4j_data:/data \
  neo4j:4.4
```

**手动安装**：
1. 下载 [Neo4j Community 4.4](https://neo4j.com/download-center/#community)
2. 解压并配置 `conf/neo4j.conf`
3. 启动：`bin/neo4j start`

#### 安装 Redis

**Docker 方式（推荐）**：
```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

### 2.2 配置后端

```bash
cd backend
cp .env.example .env
```

编辑 `.env`：
```ini
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Application
APP_ENV=production
APP_VERSION=1.0.0
CORS_ORIGINS=http://your-domain.com
```

### 2.3 启动后端

**开发模式**：
```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

**生产模式**（使用 Gunicorn + Uvicorn workers）：
```bash
cd backend
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8001
```

**Celery Worker**（单独启动，用于异步任务）：
```bash
cd backend
celery -A task_management.task_manager worker --loglevel=info
```

### 2.4 构建并部署前端

```bash
cd frontend

# 修改 API 地址（如后端不在同域）
# 编辑 src/config/apiConfig.ts 或设置环境变量

# 构建
npm install
npm run build

# dist/ 目录即为静态文件，部署到 Nginx/CDN 即可
```

**Nginx 配置示例**：
```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 前端静态文件
    root /var/www/openpalantir/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 反向代理
    location /api/ {
        proxy_pass http://localhost:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 3. 生产环境建议

### 3.1 安全

- [ ] 修改所有默认密码（Neo4j、Redis）
- [ ] 使用强密码生成器生成 API 密钥
- [ ] 配置 HTTPS（Let's Encrypt + Nginx）
- [ ] 设置防火墙规则，仅暴露必要端口（80/443）
- [ ] 不要将 `.env` 文件提交到版本控制
- [ ] 定期轮换 API 密钥

### 3.2 性能

- [ ] Neo4j 配置足够的堆内存（`dbms.memory.heap.max_size`）
- [ ] Redis 配置 `maxmemory` 限制和淘汰策略
- [ ] 后端使用多 Worker 进程（Gunicorn `-w 4`）
- [ ] 前端启用 CDN 加速静态资源
- [ ] 大文件使用 S3 等对象存储

### 3.3 监控

- [ ] 监控 Prometheus 指标（`/api/system/metrics`）
- [ ] 配置日志收集（Filebeat → ELK/Loki）
- [ ] 设置健康检查告警（`/api/system/health`）
- [ ] 配置 Neo4j 监控（`neo4j-admin report`）

### 3.4 备份

```bash
# Neo4j 备份
docker exec neo4j neo4j-admin dump --database=neo4j --to=/backup/neo4j.dump

# SQLite 备份
cp backend/data/sqlite/database.db backup/sqlite_$(date +%Y%m%d).db
```

### 3.5 高可用（进阶）

- Neo4j：使用 Enterprise 版本的 Causal Clustering
- Redis：配置 Sentinel 或 Cluster 模式
- 后端：多实例 + 负载均衡（Nginx upstream）
- 文件存储：使用共享存储（NFS）或对象存储（S3）

---

## 4. 环境变量参考

完整环境变量列表（`backend/.env`）：

| 变量 | 必填 | 默认值 | 说明 |
|------|:--:|--------|------|
| `NEO4J_URI` | 是 | `bolt://localhost:7687` | Neo4j Bolt 连接地址 |
| `NEO4J_USER` | 是 | `neo4j` | Neo4j 用户名 |
| `NEO4J_PASSWORD` | 是 | - | Neo4j 密码 |
| `REDIS_HOST` | 是 | `localhost` | Redis 地址 |
| `REDIS_PORT` | 否 | `6379` | Redis 端口 |
| `REDIS_DB` | 否 | `0` | Redis 数据库编号 |
| `CELERY_BROKER_URL` | 否 | `redis://localhost:6379/0` | Celery 消息队列 |
| `CELERY_RESULT_BACKEND` | 否 | 同上 | Celery 结果存储 |
| `APP_ENV` | 否 | `development` | 运行环境 |
| `APP_VERSION` | 否 | `1.0.0` | 应用版本 |
| `CORS_ORIGINS` | 否 | `*` | CORS 允许域名（逗号分隔） |
| `BATCH_SIZE` | 否 | `100` | 批处理大小 |
| `CACHE_TTL` | 否 | `3600` | 缓存有效期（秒） |
| `OPENAI_API_KEY` | 否 | - | OpenAI API 密钥 |
| `SILICONFLOW_API_KEY` | 否 | - | SiliconFlow API 密钥 |
| `DEEPSEEK_API_KEY` | 否 | - | DeepSeek API 密钥 |

---

## 5. 系统要求

| 资源 | 最低 | 推荐 |
|------|------|------|
| CPU | 2 核 | 4 核+ |
| 内存 | 4 GB | 8 GB+ |
| 磁盘 | 10 GB | 50 GB+ (取决于数据量) |
| 操作系统 | Linux / macOS / Windows | Linux (Ubuntu 20.04+) |
