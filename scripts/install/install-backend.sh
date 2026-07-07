#!/bin/bash
# ============================================================
# OpenPalantir 后端安装脚本
# 功能: Python 虚拟环境创建 + pip 依赖安装 + .env 生成
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "install-backend"

BACKEND_DIR="$(backend_dir)"

install_backend() {
    print_info "开始安装后端依赖..."

    cd "$BACKEND_DIR"

    # 1. 创建 Python 虚拟环境
    if [ ! -d "venv" ]; then
        run_cmd "创建 Python 虚拟环境" -- python3 -m venv venv
    else
        log_info "虚拟环境已存在，跳过创建"
    fi

    # 2. 激活虚拟环境
    source venv/bin/activate
    log_info "已激活虚拟环境: $VIRTUAL_ENV"

    # 3. 升级 pip
    run_cmd "升级 pip" -- pip install --upgrade pip

    # 4. 安装依赖（优先使用清华镜像源加速）
    if run_cmd "安装 Python 依赖" -- pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt; then
        print_success "Python 依赖安装完成"
    else
        log_warn "清华源安装失败，尝试默认源..."
        run_cmd "安装 Python 依赖（默认源）" -- pip install -r requirements.txt
    fi

    # 5. 生成 .env 文件（如不存在）
    if [ ! -f ".env" ]; then
        log_info "生成 .env 配置文件..."
        cat > .env <<'ENVEOF'
# Neo4j configuration
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=1234qwer

# Redis configuration
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0

# Celery configuration
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0

# Other configuration
APP_ENV=development
APP_VERSION=1.0.0
CORS_ORIGINS=*
BATCH_SIZE=100
CACHE_TTL=3600
ENVEOF
        print_success ".env 配置文件已生成"
        print_warn "请修改 .env 中的 NEO4J_PASSWORD 为实际密码（默认 1234qwer）"
    else
        log_info ".env 已存在，跳过生成"
    fi

    deactivate 2>/dev/null || true
    cd "$PROJECT_ROOT"
}

install_backend

print_success "后端安装完成"
echo ""
print_info "启动命令:"
echo "  cd backend && source venv/bin/activate"
echo "  uvicorn main:app --host 0.0.0.0 --port 8000"