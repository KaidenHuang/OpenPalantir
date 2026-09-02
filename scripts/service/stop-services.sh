#!/bin/bash
# ============================================================
# OpenPalantir 服务停止脚本
# 功能: 停止 Neo4j + Redis + 所有 Debezium 实例（原生 + Docker）
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "stop-services"

# 忽略 SIGTERM，防止 kill_by_pattern 发送的信号在 WSL 中传播到自身
trap '' SIGTERM

COMPOSE_FILE="$PROJECT_ROOT/deploy/docker-compose.yml"
INSTANCES_DIR="$(debezium_instances_dir)"
NEO4J_EXTRACTED_DIR="$PROJECT_ROOT/dependencies/neo4j/extracted"

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
    kill_by_pattern "io.debezium.server"

    # 2. 停止原生 Neo4j
    local neo4j_home
    neo4j_home=$(find "$NEO4J_EXTRACTED_DIR" -maxdepth 1 -type d -name "neo4j-community-*" 2>/dev/null | head -1)
    if [ -n "$neo4j_home" ] && [ -f "$neo4j_home/bin/neo4j" ]; then
        print_info "停止 Neo4j（原生）..."
        "$neo4j_home/bin/neo4j" stop 2>/dev/null || true
    fi
    kill_by_pattern "org.neo4j"

    # 3. 停止原生 Redis
    print_info "停止 Redis（原生）..."
    systemctl stop redis-server 2>/dev/null || true
    systemctl stop redis 2>/dev/null || true
    redis-cli shutdown 2>/dev/null || true
    kill_by_pattern "redis-server"

    # 4. 停止后端 (FastAPI)
    print_info "停止后端 (FastAPI)..."
    kill_by_pattern "uvicorn main:app"

    # 5. 停止前端 (Vite)
    print_info "停止前端 (Vite)..."
    kill_by_pattern "vite"

    # 6. 停止 Docker 容器
    if [ -f "$COMPOSE_FILE" ] && docker info &>/dev/null 2>&1; then
        print_info "停止 Docker 容器..."
        run_cmd_no_fail "停止 Neo4j + Redis 容器" -- docker compose -f "$COMPOSE_FILE" down
    fi
}

stop_services

print_success "所有服务已停止"