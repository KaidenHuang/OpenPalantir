#!/bin/bash
# ============================================================
# OpenPalantir Debezium 卸载脚本
# 功能: 停止所有 Debezium 实例，删除 extracted/ 和 instances/ 目录
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "uninstall-debezium"

print_info "停止所有 Debezium 实例..."

# 停止所有实例
INSTANCES_DIR="$(debezium_instances_dir)"
if [ -d "$INSTANCES_DIR" ]; then
    for instance_dir in "$INSTANCES_DIR"/*/; do
        [ -d "$instance_dir" ] || continue
        local instance_id
        instance_id=$(basename "$instance_dir")
        bash "$SCRIPT_DIR/../service/stop-debezium.sh" "$instance_id" 2>/dev/null || true
    done
fi

# 兜底：按进程名杀
kill_by_pattern "io.debezium.server"

# 删除目录
print_info "删除 Debezium 文件..."
EXTRACTED_DIR="$(debezium_extracted_dir)"
if [ -d "$EXTRACTED_DIR" ]; then
    rm -rf "$EXTRACTED_DIR"
    print_info "已删除: $EXTRACTED_DIR"
fi
if [ -d "$INSTANCES_DIR" ]; then
    rm -rf "$INSTANCES_DIR"
    print_info "已删除: $INSTANCES_DIR"
fi

print_success "Debezium 卸载完成"