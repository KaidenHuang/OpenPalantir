#!/bin/bash
# ============================================================
# OpenPalantir 服务停止脚本
# 功能: 停止 Neo4j + Redis (Docker Compose) + 所有 Debezium 实例
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "stop-services"

COMPOSE_FILE="$PROJECT_ROOT/deploy/docker-compose.yml"
INSTANCES_DIR="$(debezium_instances_dir)"

stop_services() {
    print_info "停止所有服务..."

    # 1. 停止所有 Debezium 实例
    print_info "停止所有 Debezium 实例..."
    if [ -d "$INSTANCES_DIR" ]; then
        for instance_dir in "$INSTANCES_DIR"/*/; do
            [ -d "$instance_dir" ] || continue
            local instance_id
            instance_id=$(basename "$instance_dir")
            local pid_file="$instance_dir/debezium.pid"

            if [ -f "$pid_file" ]; then
                local pid
                pid=$(cat "$pid_file")
                if kill -0 "$pid" 2>/dev/null; then
                    log_info "停止 Debezium 实例: $instance_id (PID: $pid)"
                    kill "$pid" 2>/dev/null || true
                    sleep 2
                    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
                fi
                rm -f "$pid_file"
            fi
        done
    fi
    # 兜底：按进程名杀
    kill_by_pattern "io.debezium.server"

    # 2. 停止 Docker 容器
    if [ -f "$COMPOSE_FILE" ]; then
        print_info "停止 Neo4j + Redis 容器..."
        run_cmd_no_fail "停止 Neo4j + Redis" -- docker compose -f "$COMPOSE_FILE" down
    else
        log_warn "Docker Compose 文件不存在: $COMPOSE_FILE"
    fi
}

stop_services

print_success "所有服务已停止"