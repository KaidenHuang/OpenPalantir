#!/bin/bash
# ============================================================
# OpenPalantir Redis 卸载脚本 (Linux)
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "uninstall-redis"

print_info "卸载 Redis..."

# 停止 Redis 服务
if systemctl is-active --quiet redis-server 2>/dev/null; then
    print_info "停止 redis-server 服务..."
    sudo systemctl stop redis-server 2>/dev/null || true
    sudo systemctl disable redis-server 2>/dev/null || true
elif systemctl is-active --quiet redis 2>/dev/null; then
    print_info "停止 redis 服务..."
    sudo systemctl stop redis 2>/dev/null || true
    sudo systemctl disable redis 2>/dev/null || true
fi

# 停止所有 Redis 进程
kill_by_pattern "redis-server"

# 如果通过 apt 安装，询问是否卸载
if dpkg -l redis-server &>/dev/null 2>&1; then
    print_warn "Redis 通过 apt 安装，如需完全卸载请执行:"
    print_info "  sudo apt remove --purge redis-server"
fi

print_success "Redis 已停止"