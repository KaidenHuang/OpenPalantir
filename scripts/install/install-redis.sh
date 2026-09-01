#!/bin/bash
# ============================================================
# OpenPalantir Redis 安装脚本 (Linux)
# 功能: 安装 Redis（优先系统包管理器，回退源码编译）
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "install-redis"

REDIS_LOCAL_DIR="$PROJECT_ROOT/dependencies/redis/local"

install_redis() {
    print_info "安装 Redis..."

    # 方案 A：系统包管理器已安装
    if command -v redis-server &> /dev/null; then
        local ver
        ver=$(redis-server --version 2>&1 | head -1)
        print_success "Redis 已安装: $ver"

        # 确保配置正确
        configure_redis_system
        return 0
    fi

    # 方案 B：系统包管理器安装
    if command -v apt &> /dev/null; then
        print_info "通过 apt 安装 Redis..."
        if sudo apt install -y redis-server; then
            print_success "Redis 安装完成"
            configure_redis_system
            return 0
        fi
        log_warn "apt 安装失败，尝试从本地包安装..."
    elif command -v dnf &> /dev/null; then
        print_info "通过 dnf 安装 Redis..."
        if sudo dnf install -y redis; then
            print_success "Redis 安装完成"
            configure_redis_system
            return 0
        fi
        log_warn "dnf 安装失败，尝试从本地包安装..."
    elif command -v yum &> /dev/null; then
        print_info "通过 yum 安装 Redis..."
        if sudo yum install -y redis; then
            print_success "Redis 安装完成"
            configure_redis_system
            return 0
        fi
        log_warn "yum 安装失败，尝试从本地包安装..."
    fi

    # 方案 C：从本地离线包编译安装
    if [ -d "$REDIS_LOCAL_DIR" ]; then
        local redis_tar
        redis_tar=$(ls "$REDIS_LOCAL_DIR"/redis-*.tar.gz 2>/dev/null | head -1)
        if [ -n "$redis_tar" ]; then
            print_info "从本地包编译 Redis: $redis_tar"
            local build_dir="/tmp/redis-build-$$"
            mkdir -p "$build_dir"
            tar -xzf "$redis_tar" -C "$build_dir"
            cd "$build_dir"/redis-*
            make -j"$(nproc)"
            sudo make install
            cd "$PROJECT_ROOT"
            rm -rf "$build_dir"
            print_success "Redis 编译安装完成"
            configure_redis_system
            return 0
        fi
    fi

    print_error "无法安装 Redis，请手动安装: sudo dnf install redis  或  sudo apt install redis-server"
    return 1
}

configure_redis_system() {
    print_info "配置 Redis..."

    # 确保 Redis 绑定 localhost（安全）
    local redis_conf="/etc/redis/redis.conf"
    if [ -f "$redis_conf" ]; then
        # 修改 bind 地址（仅本地）
        if grep -q "^bind 127.0.0.1" "$redis_conf"; then
            log_info "Redis 已绑定 127.0.0.1"
        else
            log_info "设置 Redis bind 为 127.0.0.1"
            sudo sed -i 's/^bind .*/bind 127.0.0.1/' "$redis_conf"
        fi

        # 关闭保护模式（允许本地 Docker 等连接）
        sudo sed -i 's/^protected-mode yes/protected-mode no/' "$redis_conf"
    fi

    # 启动 Redis
    # 检查 systemd 是否可用（WSL 中 systemctl 命令存在但 systemd 未运行）
    if systemctl is-system-running &>/dev/null; then
        if systemctl is-active --quiet redis-server 2>/dev/null; then
            print_success "Redis 服务已在运行 (systemd)"
            return 0
        elif systemctl is-active --quiet redis 2>/dev/null; then
            print_success "Redis 服务已在运行 (systemd)"
            return 0
        fi
        print_info "启动 Redis 服务 (systemd)..."
        if systemctl start redis-server 2>/dev/null; then
            sudo systemctl enable redis-server 2>/dev/null || true
        elif systemctl start redis 2>/dev/null; then
            sudo systemctl enable redis 2>/dev/null || true
        else
            # 直接启动
            nohup redis-server --daemonize yes --bind 127.0.0.1 --protected-mode no \
                > /dev/null 2>&1 &
        fi
    else
        # 无 systemd（WSL 等），直接启动
        if pgrep -x redis-server > /dev/null 2>&1; then
            print_success "Redis 服务已在运行"
            return 0
        fi
        print_info "启动 Redis 服务（后台进程）..."
        nohup redis-server --daemonize yes --bind 127.0.0.1 --protected-mode no \
            > /dev/null 2>&1 &
    fi

    # 验证连接
    sleep 2
    if redis-cli ping 2>/dev/null | grep -q PONG; then
        print_success "Redis 连接测试通过 (PONG)"
    else
        print_warn "Redis 连接测试失败，请检查服务状态"
    fi
}

install_redis