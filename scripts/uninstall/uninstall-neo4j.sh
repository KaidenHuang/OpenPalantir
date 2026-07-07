#!/bin/bash
# ============================================================
# OpenPalantir Neo4j 卸载脚本 (Linux)
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "uninstall-neo4j"

print_info "卸载 Neo4j..."

# 查找 Neo4j 安装目录
NEO4J_EXTRACTED_DIR="$PROJECT_ROOT/dependencies/neo4j/extracted"
NEO4J_HOME_DIR=$(find "$NEO4J_EXTRACTED_DIR" -maxdepth 1 -type d -name "neo4j-community-*" 2>/dev/null | head -1)

if [ -n "$NEO4J_HOME_DIR" ] && [ -f "$NEO4J_HOME_DIR/bin/neo4j" ]; then
    print_info "停止 Neo4j..."
    "$NEO4J_HOME_DIR/bin/neo4j" stop 2>/dev/null || true
fi

# 停止所有 Neo4j Java 进程
kill_by_pattern "neo4j"

# 删除解压目录
if [ -d "$NEO4J_EXTRACTED_DIR" ]; then
    print_info "删除 Neo4j 目录..."
    rm -rf "$NEO4J_EXTRACTED_DIR"
    print_success "已删除: $NEO4J_EXTRACTED_DIR"
fi

# 清理数据目录
if [ -d "$PROJECT_ROOT/backend/data/neo4j" ]; then
    print_info "清理 Neo4j 数据目录..."
    rm -rf "$PROJECT_ROOT/backend/data/neo4j"
    print_success "已清理数据目录"
fi

print_success "Neo4j 卸载完成"