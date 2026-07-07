# OpenPalantir 安装与部署指南

支持 **Windows** 和 **Linux** 平台。

## 1. 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| 操作系统 | Windows 10/11 (x64) 或 Linux (Ubuntu 20.04+) | |
| Python | 3.10+ | 后端运行环境 |
| Node.js | 18+ | 前端构建与运行 |
| Git | 任意 | 克隆仓库 |
| Java | 17+ | Debezium Server 运行环境（CDC 增量同步） |
| Docker | 20.10+ | Linux 下运行 Neo4j + Redis（Windows 可用原生安装） |

| 资源 | 最低 | 推荐 |
|------|------|------|
| CPU | 2 核 | 4 核+ |
| 内存 | 4 GB | 8 GB+ |
| 磁盘 | 10 GB | 50 GB+（取决于数据量） |

---

## 2. Linux 安装

### 2.1 安装系统依赖

```bash
sudo apt update && sudo apt install -y \
    python3 python3-pip python3-venv \
    curl wget tar unzip \
    openjdk-17-jdk \
    docker.io docker-compose-v2

# 安装 Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 启动 Docker
sudo systemctl enable --now docker
```

### 2.2 克隆仓库

```bash
git clone https://github.com/KaidenHuang/OpenPalantir.git
cd OpenPalantir
```

### 2.3 一键安装

```bash
bash scripts/install/install-all.sh
```

该脚本按顺序执行：
1. 前置检查（Python、Node.js、Java、Docker）
2. 安装 Debezium Server（下载 + 解压 + 配置）
3. 安装前端依赖（`npm install` → `npm run build`）
4. 安装后端依赖（`pip install -r requirements.txt` → 生成 `.env`）
5. 拉取 Neo4j + Redis Docker 镜像

### 2.4 分步安装

| 脚本 | 功能 |
|------|------|
| `bash scripts/install/install-debezium.sh` | 下载并解压 Debezium Server + 连接器插件 |
| `bash scripts/install/install-frontend.sh` | 安装前端 npm 依赖并构建 |
| `bash scripts/install/install-backend.sh` | 安装后端 pip 依赖并生成 `.env` |

### 2.5 启动系统

```bash
# 启动基础设施 (Neo4j + Redis)
bash scripts/service/start-services.sh

# 启动后端（终端 1）
cd backend && source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000

# 启动前端（终端 2）
cd frontend && npm run dev
```

访问地址：
- 前端: `http://localhost:5175`
- API 文档: `http://localhost:8000/docs`
- Neo4j Browser: `http://localhost:7474`

---

## 3. Windows 安装

### 3.1 准备离线依赖包

安装脚本采用离线安装策略，需提前下载 Neo4j 和 Redis 的发行包放入对应目录：

```text
dependencies/
├── neo4j/
│   └── local/
│       └── neo4j-community-5.26.27-windows.zip     # 从 https://neo4j.com/download/ 下载
├── redis/
│   └── local/
│       └── Redis-x64-<version>.zip                 # 从 https://github.com/tporadowski/redis/releases 下载
└── debezium/
    └── local/                                      # 首次安装自动从 Maven 中央仓库下载，无需手动放置
```

### 3.2 一键安装

以**管理员身份**打开 PowerShell，进入项目根目录执行：

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\scripts\install\install-all.ps1
```

该脚本按顺序执行：创建目录 → 安装 Redis → 安装 Neo4j → 安装 Debezium → 安装前端 → 安装后端。

### 3.3 分步安装

| 脚本 | 功能 |
|------|------|
| `scripts/install/install-redis.ps1` | 安装并启动 Redis |
| `scripts/install/install-neo4j.ps1` | 安装、配置并启动 Neo4j |
| `scripts/install/install-debezium.ps1` | 解压 Debezium Server + 连接器插件，生成配置并启动 |
| `scripts/install/install-frontend.ps1` | 安装前端 npm 依赖并构建 |
| `scripts/install/install-backend.ps1` | 安装后端 pip 依赖并生成 `.env` |

> 每个脚本均需在项目根目录下运行。安装顺序建议：Redis → Neo4j → Debezium → Frontend → Backend。

### 3.4 启动系统

基础服务启动后，在两个终端中分别启动前后端：

**后端**（终端 1）：
```powershell
cd backend
python -m uvicorn main:app --reload --port 8000
```

**前端**（终端 2）：
```powershell
cd frontend
npm run dev
```

---

## 4. 配置说明

### 4.1 配置文件

后端安装脚本会在 `backend/.env` 生成默认配置文件：

```ini
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password_here    # 修改为实际密码（默认 1234qwer）

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# 其他
APP_ENV=development
APP_VERSION=1.0.0
CORS_ORIGINS=*
BATCH_SIZE=100
CACHE_TTL=3600
```

安装后请将 `NEO4J_PASSWORD` 修改为实际密码。

### 4.2 环境变量参考

| 变量 | 必填 | 默认值 | 说明 |
|------|:--:|--------|------|
| `NEO4J_URI` | 是 | `bolt://localhost:7687` | Neo4j Bolt 连接地址 |
| `NEO4J_USER` | 是 | `neo4j` | Neo4j 用户名 |
| `NEO4J_PASSWORD` | 是 | - | Neo4j 密码 |
| `REDIS_HOST` | 是 | `localhost` | Redis 地址（缓存 + Celery + CDC 事件流） |
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

## 5. 服务管理

### 5.1 基础命令

| 操作 | Linux | Windows |
|------|-------|---------|
| 启动 Neo4j + Redis | `bash scripts/service/start-services.sh` | `.\scripts\service\start-services.ps1` |
| 停止所有服务 | `bash scripts/service/stop-services.sh` | `.\scripts\service\stop-services.ps1` |
| 启动 Debezium 实例 | `bash scripts/service/start-debezium.sh <id>` | `.\scripts\service\start-debezium.ps1 -InstanceId <id>` |
| 停止 Debezium 实例 | `bash scripts/service/stop-debezium.sh <id>` | `.\scripts\service\stop-debezium.ps1 -InstanceId <id>` |

### 5.2 systemd 服务（Linux 生产环境）

```bash
# 安装 systemd 单元文件
sudo cp deploy/openpalantir-backend.service /etc/systemd/system/
sudo cp deploy/openpalantir-celery.service /etc/systemd/system/
sudo systemctl daemon-reload

# 启用开机自启
sudo systemctl enable openpalantir-backend openpalantir-celery

# 启动
sudo systemctl start openpalantir-backend openpalantir-celery
```

### 5.3 卸载

| 平台 | 命令 |
|------|------|
| Linux | `bash scripts/uninstall/uninstall-all.sh` |
| Windows | `.\scripts\uninstall\uninstall-all.ps1`（以管理员身份运行） |

---

## 6. 生产环境部署

### 6.1 Docker 全容器部署

项目根目录 `docker-compose.yml` 包含全部 4 个服务（Neo4j + Redis + Backend + Frontend），适合快速体验，但不支持 Debezium 多实例动态管理。

```bash
# 配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，设置 NEO4J_PASSWORD

# 启动全部服务
NEO4J_PASSWORD=your_strong_password docker-compose up -d

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f backend

# 停止
docker-compose down
```

### 6.2 生产模式启动

**后端**（Gunicorn + Uvicorn workers）：
```bash
cd backend
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

**Celery Worker**（异步任务）：
```bash
cd backend
celery -A task_management.task_manager worker --loglevel=info
```

### 6.3 Nginx 反向代理

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
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 6.4 安全建议

- [ ] 修改所有默认密码（Neo4j、Redis）
- [ ] 配置 HTTPS（Let's Encrypt + Nginx）
- [ ] 设置防火墙规则，仅暴露必要端口（80/443）
- [ ] 不要将 `.env` 文件提交到版本控制
- [ ] 定期轮换 API 密钥

### 6.5 性能优化

- [ ] Neo4j 配置足够的堆内存（`dbms.memory.heap.max_size`）
- [ ] Redis 配置 `maxmemory` 限制和淘汰策略
- [ ] 后端使用多 Worker 进程（Gunicorn `-w 4`）
- [ ] 前端启用 CDN 加速静态资源

### 6.6 监控

- [ ] 监控 Prometheus 指标（`/api/system/metrics`）
- [ ] 配置日志收集（Filebeat → ELK/Loki）
- [ ] 设置健康检查告警（`/api/system/health`）

### 6.7 备份

```bash
# Neo4j 备份
docker exec openpalantir-neo4j neo4j-admin dump --database=neo4j --to=/backup/neo4j.dump

# SQLite 备份
cp backend/data/sqlite/database.db backup/sqlite_$(date +%Y%m%d).db
```

---

## 7. 默认端口与凭据

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端应用 | `http://localhost:5175` | React UI |
| 后端 API | `http://localhost:8000` | FastAPI 服务 |
| API 文档 | `http://localhost:8000/docs` | Swagger UI |
| Neo4j Browser | `http://localhost:7474` | 图数据库管理界面 |
| Neo4j Bolt | `bolt://localhost:7687` | 应用连接用 |
| Redis | `localhost:6379` | 任务队列 / 缓存 / CDC 事件流 |
| Debezium Server | — | CDC 变更数据捕获（独立 Java 进程，通过 Redis 通信） |

**Neo4j 默认凭据：**

| 字段 | 值 |
|------|-----|
| 用户名 | `neo4j` |
| 密码 | `1234qwer` |

如需修改密码，在 Neo4j Browser 中操作，或执行：

```bash
# Linux (Docker)
docker exec openpalantir-neo4j neo4j-admin dbms set-initial-password <新密码>

# Windows
cd dependencies\neo4j\extracted\neo4j-community-5.26.27\bin
.\neo4j-admin.bat dbms set-initial-password <新密码>
```

---

## 8. 常见问题

### 执行脚本提示 "running scripts is disabled"（Windows）

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Neo4j 服务安装失败（Windows）

Neo4j 服务安装需要管理员权限。右键 PowerShell 选择「以管理员身份运行」。

### 数据库被锁

```powershell
# Windows
taskkill /F /IM python.exe

# Linux
pkill -f uvicorn
```

然后删除 `backend/data/sqlite/database.db`，重新启动后端即可自动重建。

### Redis 连接失败

**Linux**：检查 Docker 容器状态
```bash
docker compose -f deploy/docker-compose.yml ps
```

**Windows**：检查 Redis 服务状态
```powershell
Get-Service | Where-Object {$_.Name -like "*redis*"}
```

或手动启动：
```bash
# Linux
bash scripts/service/start-services.sh

# Windows
.\scripts\service\start-services.ps1
```

### 后端日志

后端运行日志位于 `logs/backend.log`，运行时报错可查看此文件。

### 依赖包目录不存在（Windows）

`dependencies/neo4j/local/`、`dependencies/redis/local/` 需自行创建并放入对应的发行包。`dependencies/debezium/local/` 由安装脚本首次运行时自动从 Maven 中央仓库下载，无需预置。