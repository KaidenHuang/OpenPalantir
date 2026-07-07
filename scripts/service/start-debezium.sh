#!/bin/bash
# ============================================================
# OpenPalantir Debezium 实例启动脚本
# 用法: start-debezium.sh <instance_id>
# 由后端 cdc_manager.configure_connection() 按需调用
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

INSTANCE_ID="${1:-}"
if [ -z "$INSTANCE_ID" ]; then
    echo "用法: $0 <instance_id>" >&2
    exit 1
fi

INSTANCE_DIR="$PROJECT_ROOT/dependencies/debezium/instances/$INSTANCE_ID"
PID_FILE="$INSTANCE_DIR/debezium.pid"
LOG_DIR="$INSTANCE_DIR/data/debezium"

start_instance() {
    print_info "启动 Debezium 实例: $INSTANCE_ID"

    if [ ! -d "$INSTANCE_DIR" ]; then
        print_error "实例目录不存在: $INSTANCE_DIR"
        exit 1
    fi

    # 检查是否已在运行
    if [ -f "$PID_FILE" ]; then
        local existing_pid
        existing_pid=$(cat "$PID_FILE")
        if kill -0 "$existing_pid" 2>/dev/null; then
            print_warn "实例 $INSTANCE_ID 已在运行 (PID: $existing_pid)"
            exit 0
        fi
        rm -f "$PID_FILE"
    fi

    # 确保日志目录存在
    mkdir -p "$LOG_DIR"

    # 查找 runner.jar
    cd "$INSTANCE_DIR"
    local runner_jar
    runner_jar=$(ls debezium-server-*runner.jar 2>/dev/null | head -1)
    if [ -z "$runner_jar" ]; then
        print_error "未找到 debezium-server-*runner.jar"
        exit 1
    fi

    # 查找 JAVA_HOME
    local java_bin="java"
    if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/java" ]; then
        java_bin="$JAVA_HOME/bin/java"
    fi

    log_info "启动: $java_bin -jar $runner_jar"
    log_info "日志: $LOG_DIR/debezium.log"

    # 后台启动 Java 进程
    nohup "$java_bin" -jar "$runner_jar" \
        > "$LOG_DIR/debezium.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    # 短暂等待，确认进程未立即退出
    sleep 3
    if kill -0 "$pid" 2>/dev/null; then
        print_success "Debezium 实例 $INSTANCE_ID 已启动 (PID: $pid)"
        log_info "PID 已写入: $PID_FILE"
    else
        print_error "Debezium 实例 $INSTANCE_ID 启动失败，查看日志:"
        tail -20 "$LOG_DIR/debezium.log" 2>/dev/null || true
        rm -f "$PID_FILE"
        exit 1
    fi
}

start_instance