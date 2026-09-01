#!/bin/bash
# ============================================================
# OpenPalantir 前端卸载脚本
# 功能: 停止前端进程
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "uninstall-frontend"

# 忽略 SIGTERM，防止 kill_by_pattern 发送的信号在 WSL 中传播到自身
trap '' SIGTERM

print_info "停止前端进程..."
kill_by_pattern "vite"

print_success "前端卸载完成"
print_info "node_modules 目录已保留，如需清理请手动删除: rm -rf frontend/node_modules"