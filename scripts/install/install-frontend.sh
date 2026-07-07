#!/bin/bash
# ============================================================
# OpenPalantir 前端安装脚本
# 功能: npm install + npm run build
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "install-frontend"

FRONTEND_DIR="$(frontend_dir)"

install_frontend() {
    print_info "开始安装前端依赖..."

    cd "$FRONTEND_DIR"

    # 1. 安装 npm 依赖
    run_cmd "安装 npm 依赖" -- npm install --legacy-peer-deps

    # 2. 构建生产版本
    run_cmd "构建前端" -- npm run build

    cd "$PROJECT_ROOT"
}

install_frontend

print_success "前端安装完成"
echo ""
print_info "开发模式启动命令:"
echo "  cd frontend && npm run dev"