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

    # 检查 systemd 是否可用（WSL 中 systemctl 命令存在但 systemd 未运行）
    if systemctl is-system-running &>/dev/null; then
        if systemctl is-active --quiet redis-server 2>/dev/null; then
            print_success "Redis 已在运行 (systemd)"
            return 0
        elif systemctl is-active --quiet redis 2>/dev/null; then
            print_success "Redis 已在运行 (systemd)"
            return 0
        fi

        if systemctl start redis-server 2>/dev/null; then
            print_success "Redis 已启动 (systemd)"
        elif systemctl start redis 2>/dev/null; then
            print_success "Redis 已启动 (systemd)"
        else
            # systemd 启动失败，回退到直接启动 redis-server
            if command -v redis-server &> /dev/null; then
                if pgrep -x redis-server > /dev/null 2>&1; then
                    print_success "Redis 已在运行"
                else
                    nohup redis-server --daemonize yes --bind 127.0.0.1 > /dev/null 2>&1 &
                    print_success "Redis 已启动 (后台进程，systemd 回退)"
                fi
            else
                return 1
            fi
        fi
    elif command -v redis-server &> /dev/null; then
        if pgrep -x redis-server > /dev/null 2>&1; then
            print_success "Redis 已在运行"
            return 0
        fi
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
    local neo4j_pass="${NEO4J_PASSWORD:-1234qwer}"
    local status
    status=$("$neo4j_bin" status 2>/dev/null || echo "not running")

    if echo "$status" | grep -q "is running"; then
        print_success "Neo4j 已在运行"
        return 0
    fi

    export NEO4J_HOME="$neo4j_home"

    # 判断是否可用 systemd（WSL 中 systemctl 存在但 systemd 未运行）
    if systemctl is-system-running &>/dev/null; then
        # 有 systemd，使用 daemon 模式
        "$neo4j_bin" start 2>/dev/null
    else
        # 无 systemd（WSL），使用 console 模式 + setsid 彻底分离进程
        log_info "检测到无 systemd 环境，使用 console 模式启动 Neo4j..."
        setsid "$neo4j_bin" console > "$PROJECT_ROOT/logs/neo4j-console.log" 2>&1 &
        disown
    fi

    # 等待就绪
    print_info "等待 Neo4j 就绪..."
    local max_wait=60 waited=0
    while [ $waited -lt $max_wait ]; do
        if "$neo4j_home/bin/cypher-shell" -u neo4j -p "$neo4j_pass" "RETURN 1" &>/dev/null; then
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
        local ps_output neo4j_ok=0 redis_ok=0
        ps_output=$(docker compose -f "$COMPOSE_FILE" ps 2>/dev/null || true)
        echo "$ps_output" | grep -q "neo4j.*\(healthy\)" && neo4j_ok=1
        echo "$ps_output" | grep -q "redis.*\(healthy\)" && redis_ok=1
        [ "$neo4j_ok" = "1" ] && [ "$redis_ok" = "1" ] && break
        sleep 2
        waited=$((waited + 2))
    done

    if [ "$neo4j_ok" = "1" ] && [ "$redis_ok" = "1" ]; then
        print_success "Neo4j 已就绪" && print_success "Redis 已就绪"
    else
        [ "$neo4j_ok" = "1" ] && print_success "Neo4j 已就绪" || print_warn "Neo4j 可能未就绪（超时）"
        [ "$redis_ok" = "1" ] && print_success "Redis 已就绪" || print_warn "Redis 可能未就绪（超时）"
    fi
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