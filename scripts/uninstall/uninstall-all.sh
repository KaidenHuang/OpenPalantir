#!/bin/bash
# ============================================================
# OpenPalantir 一键卸载脚本
# 功能: 依次卸载所有组件
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "uninstall-all"

print_info "开始卸载 OpenPalantir..."

# 1. 停止所有服务
print_info "1/4 停止所有服务..."
bash "$SCRIPT_DIR/../service/stop-services.sh" || true

# 2. 卸载 Debezium
print_info "2/4 卸载 Debezium..."
bash "$SCRIPT_DIR/uninstall-debezium.sh" || true

# 3. 卸载前端
print_info "3/4 卸载前端..."
bash "$SCRIPT_DIR/uninstall-frontend.sh" || true

# 4. 卸载后端
print_info "4/4 卸载后端..."
bash "$SCRIPT_DIR/uninstall-backend.sh" || true

print_success "OpenPalantir 卸载完成"
echo ""
print_info "以下内容未自动清理，如需清理请手动执行:"
echo "  - Docker 容器:    docker compose -f deploy/docker-compose.yml down -v"
echo "  - Python 虚拟环境: rm -rf backend/venv"
echo "  - node_modules:    rm -rf frontend/node_modules"
echo "  - 下载的安装包:    rm -rf dependencies/debezium/local"