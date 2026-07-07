#!/bin/bash
# ============================================================
# OpenPalantir 一键安装脚本
# 功能: 按序安装所有组件（Debezium → 基础设施 → 前端 → 后端）
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "install-all"

TOTAL_STEPS=5
CURRENT_STEP=0

step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo ""
    echo "============================================================"
    echo "  [$CURRENT_STEP/$TOTAL_STEPS] $1"
    echo "============================================================"
    log_info "=== 步骤 $CURRENT_STEP/$TOTAL_STEPS: $1 ==="
}

finish() {
    echo ""
    echo "============================================================"
    echo "  OpenPalantir 安装完成"
    echo "============================================================"
    echo ""
    print_info "安装摘要:"
    echo "  Debezium Server: $EXTRACTED_DIR"
    echo "  Neo4j + Redis:   Docker Compose (deploy/docker-compose.yml)"
    echo "  后端:            $PROJECT_ROOT/backend"
    echo "  前端:            $PROJECT_ROOT/frontend"
    echo ""
    echo "============================================================"
    echo "  启动步骤"
    echo "============================================================"
    echo ""
    echo "  1. 启动基础设施 (Neo4j + Redis):"
    echo "     bash scripts/service/start-services.sh"
    echo ""
    echo "  2. 启动后端:"
    echo "     cd backend && source venv/bin/activate"
    echo "     uvicorn main:app --host 0.0.0.0 --port 8000"
    echo ""
    echo "  3. 启动前端:"
    echo "     cd frontend && npm run dev"
    echo ""
    echo "  4. 访问:"
    echo "     前端:      http://localhost:5175"
    echo "     API 文档:  http://localhost:8000/docs"
    echo "     Neo4j:     http://localhost:7474"
    echo ""
}

# ── 前置检查 ────────────────────────────────────────────────

preflight() {
    step "前置检查"

    # 检查基础命令
    local missing=()
    for cmd in python3 node npm java curl tar; do
        if ! command -v "$cmd" &> /dev/null; then
            missing+=("$cmd")
        fi
    done

    if [ ${#missing[@]} -gt 0 ]; then
        print_error "缺少以下命令: ${missing[*]}"
        echo ""
        print_info "请先安装系统依赖:"
        echo "  sudo apt update && sudo apt install -y \\"
        echo "    python3 python3-pip python3-venv \\"
        echo "    curl wget tar unzip \\"
        echo "    openjdk-17-jdk \\"
        echo "    docker.io docker-compose-v2"
        echo ""
        print_info "然后安装 Node.js:"
        echo "  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -"
        echo "  sudo apt install -y nodejs"
        exit 1
    fi

    # 检查 Docker
    if ! docker info &> /dev/null; then
        print_warn "Docker 未运行，Neo4j/Redis 将无法通过 Docker Compose 启动"
        print_info "启动 Docker: sudo systemctl enable --now docker"
    fi

    # 创建目录
    mkdir -p "$PROJECT_ROOT/dependencies/debezium/local"
    mkdir -p "$PROJECT_ROOT/dependencies/debezium/extracted"
    mkdir -p "$PROJECT_ROOT/dependencies/debezium/instances"
    mkdir -p "$PROJECT_ROOT/logs"

    print_success "前置检查通过"
}

# ── 主流程 ──────────────────────────────────────────────────

main() {
    echo ""
    echo "============================================================"
    echo "  OpenPalantir 一键安装"
    echo "  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"

    preflight

    step "安装 Debezium Server"
    bash "$SCRIPT_DIR/install-debezium.sh" || {
        print_error "Debezium 安装失败"
        exit 1
    }

    step "安装前端依赖"
    bash "$SCRIPT_DIR/install-frontend.sh" || {
        print_error "前端安装失败"
        exit 1
    }

    step "安装后端依赖"
    bash "$SCRIPT_DIR/install-backend.sh" || {
        print_error "后端安装失败"
        exit 1
    }

    step "拉取 Docker 镜像"
    print_info "拉取 Neo4j 和 Redis 镜像..."
    docker pull neo4j:5.26 2>/dev/null || print_warn "Neo4j 镜像拉取失败（可稍后重试）"
    docker pull redis:7-alpine 2>/dev/null || print_warn "Redis 镜像拉取失败（可稍后重试）"

    finish
}

main