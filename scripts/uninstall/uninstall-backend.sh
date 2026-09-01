#!/bin/bash
# ============================================================
# OpenPalantir 后端卸载脚本
# 功能: 停止后端进程，删除 .env 文件
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "uninstall-backend"

# 忽略 SIGTERM，防止 kill_by_pattern 发送的信号在 WSL 中传播到自身
trap '' SIGTERM

print_info "停止后端进程..."
kill_by_pattern "uvicorn.*main:app"
kill_by_pattern "main:app"

print_info "删除 .env 配置文件..."
if [ -f "$PROJECT_ROOT/backend/.env" ]; then
    rm -f "$PROJECT_ROOT/backend/.env"
    print_info ".env 已删除"
fi

print_success "后端卸载完成"