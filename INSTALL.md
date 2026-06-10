# OpenPalantir 安装指南

> 当前仅支持 **Windows** 平台。Linux/macOS 支持将在后续版本中添加。

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Windows | 10 / 11 (x64) | 或 Windows Server 2019+ |
| PowerShell | 5.1+ | 所有安装/卸载/服务管理脚本均为 PowerShell |
| Python | 3.10+ | 后端运行环境 |
| Node.js | 18+ | 前端构建与运行 |
| Git | 任意 | 克隆仓库 |

此外系统依赖 Neo4j 4.4.8 和 Redis 6+，由安装脚本自动处理。

## 快速安装

### 1. 克隆仓库

```powershell
git clone git@github.com:KaidenHuang/OpenPalantir.git
cd OpenPalantir
```

> 如果遇到 SSH 公钥问题（`Permission denied (publickey)`），请先在 GitHub 中配置 SSH Key，或改用 HTTPS：
> ```
> git clone https://github.com/KaidenHuang/OpenPalantir.git
> ```

### 2. 准备离线依赖包

安装脚本采用离线安装策略，需提前下载 Neo4j 和 Redis 的发行包放入对应目录：

```text
dependencies/
├── neo4j/
│   └── local/
│       └── neo4j-community-4.4.8-windows.zip     # 从 https://neo4j.com/download/ 下载
└── redis/
    └── local/
        └── Redis-x64-<version>.zip               # 从 https://github.com/tporadowski/redis/releases 下载
```

创建目录并放入 zip 文件后即可继续。

### 3. 一键安装

以**管理员身份**打开 PowerShell，进入项目根目录执行：

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\scripts\install\install-all.ps1
```

该脚本按顺序执行：
1. 创建 `dependencies/` 和 `logs/` 目录
2. 安装 Redis（解压 → 注册 Windows 服务 → 启动）
3. 安装 Neo4j（解压 → 配置 → 注册 Windows 服务 → 设置初始密码 → 启动）
4. 安装前端依赖（`npm install` → `npm run build`）
5. 安装后端依赖（`pip install -r requirements.txt` → 生成 `.env`）

安装完成后输出摘要，列出各组件的安装结果。

## 分步安装

如果只需要安装部分组件，可单独运行对应脚本：

| 脚本 | 功能 |
|------|------|
| `scripts/install/install-redis.ps1` | 安装并启动 Redis |
| `scripts/install/install-neo4j.ps1` | 安装、配置并启动 Neo4j |
| `scripts/install/install-frontend.ps1` | 安装前端 npm 依赖并构建 |
| `scripts/install/install-backend.ps1` | 安装后端 pip 依赖并生成 `.env` |

> 每个脚本均需在项目根目录下运行。安装顺序建议：Redis → Neo4j → Frontend → Backend。

## 服务启停

### 启动基础服务（Neo4j + Redis）

```powershell
.\scripts\service\start-services.ps1
```

### 停止基础服务（Neo4j + Redis）

```powershell
.\scripts\service\stop-services.ps1
```

### 手动启动后端与前端

基础服务启动后，需在两个终端中分别启动前后端：

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

## 卸载

### 一键卸载

以**管理员身份**运行：

```powershell
.\scripts\uninstall\uninstall-all.ps1
```

该脚本依次：停止 Redis 服务并移除 → 停止 Neo4j 服务并移除 → 停止前后端进程 → 清理 `logs/` 目录。

### 分步卸载

| 脚本 | 功能 |
|------|------|
| `scripts/uninstall/uninstall-redis.ps1` | 停止并卸载 Redis |
| `scripts/uninstall/uninstall-neo4j.ps1` | 停止并卸载 Neo4j |
| `scripts/uninstall/uninstall-frontend.ps1` | 停止前端相关进程 |
| `scripts/uninstall/uninstall-backend.ps1` | 停止后端 Python 进程，移除 `.env` |

## 默认端口与凭据

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端应用 | `http://localhost:5175` | React UI |
| 后端 API | `http://localhost:8000` | FastAPI 服务 |
| API 文档 | `http://localhost:8000/docs` | Swagger UI |
| Neo4j Browser | `http://localhost:7474` | 图数据库管理界面 |
| Neo4j Bolt | `bolt://localhost:7687` | 应用连接用 |
| Redis | `localhost:6379` | 任务队列 / 缓存 |

**Neo4j 默认凭据：**

| 字段 | 值 |
|------|-----|
| 用户名 | `neo4j` |
| 密码 | `1234qwer` |

安装脚本会自动设置初始密码。如需修改，可在 Neo4j Browser 中操作，或运行：

```powershell
cd dependencies\neo4j\extracted\neo4j-community-4.4.8\bin
.\neo4j-admin.bat set-initial-password <新密码>
```

## 配置文件

后端安装脚本会在 `backend/.env` 生成默认配置文件，内容如下：

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

安装后请将 `NEO4J_PASSWORD` 修改为安装时设置的密码。

## 常见问题

### 执行脚本提示 "running scripts is disabled"

PowerShell 默认禁止运行脚本，执行：

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Neo4j 服务安装失败

Neo4j 服务安装需要管理员权限。右键 PowerShell 选择「以管理员身份运行」。

### 数据库被锁

```powershell
taskkill /F /IM python.exe
del backend\data\sqlite\database.db
```

重新启动后端即可自动重建数据库。

### Redis 连接失败 (PONG 测试不通过)

检查 Redis 服务状态：

```powershell
Get-Service | Where-Object {$_.Name -like "*redis*"}
```

或手动启动：

```powershell
.\scripts\service\start-services.ps1
```

### 后端日志

后端运行日志位于 `logs/backend.log`，运行时报错可查看此文件。

### 依赖包目录不存在

`dependencies/neo4j/local/` 和 `dependencies/redis/local/` 需自行创建并放入对应的 zip 包。未放入时安装脚本会跳过对应组件。
