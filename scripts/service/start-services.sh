#!/bin/bash
# ============================================================
# OpenPalantir 服务启动脚本
# 功能: 启动 Neo4j + Redis (Docker Compose)
# 注意: Debezium 不由此脚本启动，由后端「配置 CDC」按需管理
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "start-services"

COMPOSE_FILE="$PROJECT_ROOT/deploy/docker-compose.yml"

start_services() {
    print_info "启动基础设施服务 (Neo4j + Redis)..."

    if [ ! -f "$COMPOSE_FILE" ]; then
        print_error "Docker Compose 文件不存在: $COMPOSE_FILE"
        return 1
    fi

    # 检查 Docker 是否运行
    if ! docker info &> /dev/null; then
        print_error "Docker 未运行，请先启动 Docker"
        print_info "  sudo systemctl enable --now docker"
        return 1
    fi

    # 启动容器
    run_cmd "启动 Neo4j + Redis 容器" -- docker compose -f "$COMPOSE_FILE" up -d

    # 等待健康检查
    print_info "等待 Neo4j 就绪..."
    local max_wait=60
    local waited=0
    while [ $waited -lt $max_wait ]; do
        if docker compose -f "$COMPOSE_FILE" ps neo4j 2>/dev/null | grep -q "(healthy)"; then
            print_success "Neo4j 已就绪"
            break
        fi
        sleep 2
        waited=$((waited + 2))
    done
    if [ $waited -ge $max_wait ]; then
        print_warn "Neo4j 健康检查超时，请手动确认"
    fi

    print_info "等待 Redis 就绪..."
    waited=0
    while [ $waited -lt $max_wait ]; do
        if docker compose -f "$COMPOSE_FILE" ps redis 2>/dev/null | grep -q "(healthy)"; then
            print_success "Redis 已就绪"
            break
        fi
        sleep 2
        waited=$((waited + 2))
    done
    if [ $waited -ge $max_wait ]; then
        print_warn "Redis 健康检查超时，请手动确认"
    fi

    # 显示状态
    echo ""
    print_info "服务状态:"
    docker compose -f "$COMPOSE_FILE" ps 2>/dev/null
}

start_services

echo ""
print_info "端口:"
echo "  Neo4j Bolt:   7687"
echo "  Neo4j Browser: 7474 (http://localhost:7474)"
echo "  Redis:         6379"