#!/bin/bash
# ============================================================
# OpenPalantir 服务启动脚本
# 功能: 启动 Neo4j + Redis（优先原生，回退 Docker Compose）
# 注意: Debezium 不由此脚本启动，由后端「配置 CDC」按需管理
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "start-services"

COMPOSE_FILE="$PROJECT_ROOT/deploy/docker-compose.yml"
NEO4J_EXTRACTED_DIR="$PROJECT_ROOT/dependencies/neo4j/extracted"

# ── 原生 Redis ──────────────────────────────────────────────

start_redis_native() {
    print_info "启动 Redis（原生）..."

    if systemctl is-active --quiet redis-server 2>/dev/null; then
        print_success "Redis 已在运行 (systemd)"
        return 0
    elif systemctl is-active --quiet redis 2>/dev/null; then
        print_success "Redis 已在运行 (systemd)"
        return 0
    fi

    # 尝试启动 systemd 服务
    if systemctl start redis-server 2>/dev/null; then
        print_success "Redis 已启动 (systemd)"
    elif systemctl start redis 2>/dev/null; then
        print_success "Redis 已启动 (systemd)"
    elif command -v redis-server &> /dev/null; then
        nohup redis-server --daemonize yes --bind 127.0.0.1 > /dev/null 2>&1 &
        print_success "Redis 已启动 (后台进程)"
    else
        return 1
    fi

    sleep 1
    redis-cli ping 2>/dev/null | grep -q PONG && print_success "Redis 连接测试通过"
}

# ── 原生 Neo4j ──────────────────────────────────────────────

start_neo4j_native() {
    print_info "启动 Neo4j（原生）..."

    local neo4j_home
    neo4j_home=$(find "$NEO4J_EXTRACTED_DIR" -maxdepth 1 -type d -name "neo4j-community-*" 2>/dev/null | head -1)

    if [ -z "$neo4j_home" ]; then
        return 1
    fi

    local neo4j_bin="$neo4j_home/bin/neo4j"
    local status
    status=$("$neo4j_bin" status 2>/dev/null || echo "not running")

    if echo "$status" | grep -q "is running"; then
        print_success "Neo4j 已在运行"
        return 0
    fi

    export NEO4J_HOME="$neo4j_home"
    "$neo4j_bin" start 2>/dev/null

    # 等待就绪
    print_info "等待 Neo4j 就绪..."
    local max_wait=60 waited=0
    while [ $waited -lt $max_wait ]; do
        if "$neo4j_home/bin/cypher-shell" -u neo4j -p 1234qwer "RETURN 1" &>/dev/null; then
            print_success "Neo4j 已就绪"
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done
    print_warn "Neo4j 启动超时"
    return 1
}

# ── Docker 回退 ─────────────────────────────────────────────

start_docker() {
    print_info "启动 Neo4j + Redis（Docker Compose）..."

    if [ ! -f "$COMPOSE_FILE" ]; then
        print_error "Docker Compose 文件不存在: $COMPOSE_FILE"
        return 1
    fi

    if ! docker info &> /dev/null; then
        print_error "Docker 未运行"
        return 1
    fi

    run_cmd "启动 Neo4j + Redis 容器" -- docker compose -f "$COMPOSE_FILE" up -d

    print_info "等待服务就绪..."
    local max_wait=60 waited=0
    while [ $waited -lt $max_wait ]; do
        local neo4j_ok redis_ok
        docker compose -f "$COMPOSE_FILE" ps neo4j 2>/dev/null | grep -q "(healthy)" && neo4j_ok=1 || neo4j_ok=0
        docker compose -f "$COMPOSE_FILE" ps redis 2>/dev/null | grep -q "(healthy)" && redis_ok=1 || redis_ok=0
        [ "$neo4j_ok" = "1" ] && print_success "Neo4j 已就绪"
        [ "$redis_ok" = "1" ] && print_success "Redis 已就绪"
        [ "$neo4j_ok" = "1" ] && [ "$redis_ok" = "1" ] && break
        sleep 2
        waited=$((waited + 2))
    done

    docker compose -f "$COMPOSE_FILE" ps 2>/dev/null
}

# ── 主流程 ──────────────────────────────────────────────────

start_services() {
    print_info "启动基础设施服务 (Neo4j + Redis)..."

    local redis_ok=0 neo4j_ok=0

    # 优先原生，失败回退 Docker
    start_redis_native && redis_ok=1 || log_info "Redis 原生启动失败，尝试 Docker..."
    start_neo4j_native && neo4j_ok=1 || log_info "Neo4j 原生启动失败，尝试 Docker..."

    if [ "$redis_ok" = "0" ] || [ "$neo4j_ok" = "0" ]; then
        start_docker || {
            print_error "无法启动 Neo4j/Redis，请检查安装"
            return 1
        }
    fi
}

start_services

echo ""
print_info "端口:"
echo "  Neo4j Bolt:     7687"
echo "  Neo4j Browser:  7474 (http://localhost:7474)"
echo "  Redis:          6379"