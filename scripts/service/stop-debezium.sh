#!/bin/bash
# ============================================================
# OpenPalantir Debezium 实例停止脚本
# 用法: stop-debezium.sh <instance_id>
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

stop_instance() {
    print_info "停止 Debezium 实例: $INSTANCE_ID"

    if [ ! -f "$PID_FILE" ]; then
        # 无 PID 文件，尝试按进程名查找
        log_info "无 PID 文件，尝试按进程名查找..."
        local pids
        pids=$(pgrep -f "io.debezium.server.*$INSTANCE_ID" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            log_info "找到进程: $pids"
            echo "$pids" | xargs kill 2>/dev/null || true
            sleep 2
            pids=$(pgrep -f "io.debezium.server.*$INSTANCE_ID" 2>/dev/null || true)
            [ -n "$pids" ] && echo "$pids" | xargs kill -9 2>/dev/null || true
        fi
        print_info "实例 $INSTANCE_ID 未在运行（无 PID 文件）"
        return 0
    fi

    local pid
    pid=$(cat "$PID_FILE")

    if ! kill -0 "$pid" 2>/dev/null; then
        log_info "进程 $pid 已不存在，清理 PID 文件"
        rm -f "$PID_FILE"
        print_info "实例 $INSTANCE_ID 已停止"
        return 0
    fi

    # 优雅终止
    log_info "发送 SIGTERM 到 PID: $pid"
    kill "$pid" 2>/dev/null || true

    # 等待进程退出（最多 30 秒）
    local waited=0
    while [ $waited -lt 30 ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PID_FILE"
            print_success "实例 $INSTANCE_ID 已停止"
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done

    # 超时强制终止
    log_warn "优雅终止超时，强制终止 PID: $pid"
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
    rm -f "$PID_FILE"
    print_success "实例 $INSTANCE_ID 已强制停止"
}

stop_instance