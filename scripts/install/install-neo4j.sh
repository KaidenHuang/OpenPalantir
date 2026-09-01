#!/bin/bash
# ============================================================
# OpenPalantir Neo4j 安装脚本 (Linux)
# 功能: 从本地离线包解压 Neo4j → 配置 → 设置初始密码 → 启动
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "install-neo4j"

NEO4J_LOCAL_DIR="$PROJECT_ROOT/dependencies/neo4j/local"
NEO4J_EXTRACTED_DIR="$PROJECT_ROOT/dependencies/neo4j/extracted"
NEO4J_VERSION="2026.07.1"
NEO4J_PASSWORD="1234qwer"
NEO4J_HOME_DIR=""

# ── 检查 Java ───────────────────────────────────────────────

check_java() {
    print_info "检查 Java 版本..."

    if ! command -v java &> /dev/null; then
        print_error "未找到 Java。Neo4j 需要 Java 17 或更高版本"
        print_info "安装: sudo dnf install -y java-21-openjdk-devel  或  sudo apt install -y openjdk-21-jdk"
        return 1
    fi

    local java_ver
    java_ver=$(java -version 2>&1 | head -1)
    print_info "Java: $java_ver"

    local major
    major=$(echo "$java_ver" | grep -oP '"(\d+)' | tr -d '"')

    # 根据 Neo4j 版本判断 Java 需求
    # Neo4j 2025+ (日历版本) 需要 Java 21+
    # Neo4j 5.x 需要 Java 17 或 21
    local neo4j_major
    neo4j_major=$(echo "$NEO4J_VERSION" | cut -d'.' -f1)
    if [ "$neo4j_major" -ge 2025 ] 2>/dev/null; then
        # Neo4j 2025+ 日历版本
        if [ "$major" -ge 21 ] 2>/dev/null; then
            print_success "Java $major 支持 Neo4j $NEO4J_VERSION"
        else
            print_error "Neo4j $NEO4J_VERSION 需要 Java 21 或更高版本，当前 Java $major"
            print_info "安装: sudo dnf install -y java-21-openjdk-devel  或  sudo apt install -y openjdk-21-jdk"
            return 1
        fi
    else
        # Neo4j 5.x 传统版本
        if [ "$major" = "17" ] || [ "$major" = "21" ]; then
            print_success "Java $major 支持 Neo4j"
        else
            print_warn "Java $major 非推荐版本，建议 Java 17 或 21"
        fi
    fi
}

# ── 解压 ────────────────────────────────────────────────────

extract_neo4j() {
    print_info "解压 Neo4j..."

    # 清理旧版解压目录，避免多版本冲突
    if [ -d "$NEO4J_EXTRACTED_DIR" ]; then
        local old_dirs
        old_dirs=$(find "$NEO4J_EXTRACTED_DIR" -maxdepth 1 -type d -name "neo4j-community-*" 2>/dev/null)
        if [ -n "$old_dirs" ]; then
            print_info "清理旧版 Neo4j 解压目录..."
            echo "$old_dirs" | while read -r dir; do
                log_info "删除: $dir"
                rm -rf "$dir"
            done
        fi
    fi

    mkdir -p "$NEO4J_EXTRACTED_DIR"

    # 检查分块文件并重新组装
    local first_part
    first_part=$(ls "$NEO4J_LOCAL_DIR"/neo4j-community-*.tar.gz.part00 2>/dev/null | head -1)
    if [ -n "$first_part" ]; then
        local base_name="${first_part%.part00}"
        if [ ! -f "$base_name" ]; then
            print_info "检测到分块文件，正在组装..."
            cat "$NEO4J_LOCAL_DIR"/neo4j-community-*.tar.gz.part* > "$base_name"
            print_success "安装包组装完成: $(basename "$base_name")"
        fi
    fi

    # 尝试从本地包解压
    local neo4j_archive
    neo4j_archive=$(ls "$NEO4J_LOCAL_DIR"/neo4j-community-*.tar.gz 2>/dev/null | head -1)
    if [ -z "$neo4j_archive" ]; then
        neo4j_archive=$(ls "$NEO4J_LOCAL_DIR"/neo4j-community-*.zip 2>/dev/null | head -1)
    fi

    if [ -z "$neo4j_archive" ]; then
        print_error "未找到 Neo4j 安装包"
        print_info "请下载 neo4j-community-$NEO4J_VERSION-unix.tar.gz 到:"
        print_info "  $NEO4J_LOCAL_DIR/"
        print_info "下载地址: https://neo4j.com/download-center/#community"
        return 1
    fi

    print_info "安装包: $neo4j_archive"

    # 解压
    if [[ "$neo4j_archive" == *.tar.gz ]]; then
        run_cmd "解压 Neo4j" -- tar -xzf "$neo4j_archive" -C "$NEO4J_EXTRACTED_DIR"
    else
        run_cmd "解压 Neo4j" -- unzip -q "$neo4j_archive" -d "$NEO4J_EXTRACTED_DIR"
    fi

    # 查找解压后的目录
    NEO4J_HOME_DIR=$(find "$NEO4J_EXTRACTED_DIR" -maxdepth 1 -type d -name "neo4j-community-*" | head -1)
    if [ -z "$NEO4J_HOME_DIR" ]; then
        print_error "解压后未找到 Neo4j 目录"
        return 1
    fi

    print_success "Neo4j 解压到: $NEO4J_HOME_DIR"
}

# ── 配置 ────────────────────────────────────────────────────

configure_neo4j() {
    print_info "配置 Neo4j..."

    local conf_file="$NEO4J_HOME_DIR/conf/neo4j.conf"
    local data_dir="$PROJECT_ROOT/backend/data/neo4j/data"
    local logs_dir="$PROJECT_ROOT/backend/data/neo4j/logs"

    mkdir -p "$data_dir" "$logs_dir"

    if [ ! -f "$conf_file" ]; then
        print_error "配置文件不存在: $conf_file"
        return 1
    fi

    # 备份原始配置
    cp "$conf_file" "$conf_file.bak"

    # 更新数据目录（Neo4j 5.x 使用 server.directories.*）
    if grep -q "^#\?server\.directories\.data=" "$conf_file"; then
        sed -i "s|^#\?server\.directories\.data=.*|server.directories.data=$data_dir|" "$conf_file"
    else
        echo "server.directories.data=$data_dir" >> "$conf_file"
    fi

    # 更新日志目录
    if grep -q "^#\?server\.directories\.logs=" "$conf_file"; then
        sed -i "s|^#\?server\.directories\.logs=.*|server.directories.logs=$logs_dir|" "$conf_file"
    else
        echo "server.directories.logs=$logs_dir" >> "$conf_file"
    fi

    # 更新事务日志目录
    if grep -q "^#\?server\.directories\.transaction\.logs\.root=" "$conf_file"; then
        sed -i "s|^#\?server\.directories\.transaction\.logs\.root=.*|server.directories.transaction.logs.root=$data_dir/transactions|" "$conf_file"
    else
        echo "server.directories.transaction.logs.root=$data_dir/transactions" >> "$conf_file"
    fi

    # 设置监听地址为 0.0.0.0（WSL2/Docker 环境需要）
    if grep -q "^#\?server\.default_listen_address=" "$conf_file"; then
        sed -i "s|^#\?server\.default_listen_address=.*|server.default_listen_address=0.0.0.0|" "$conf_file"
    else
        echo "server.default_listen_address=0.0.0.0" >> "$conf_file"
    fi

    print_success "Neo4j 配置完成"
}

# ── 初始化 ──────────────────────────────────────────────────

initialize_neo4j() {
    print_info "设置 Neo4j 初始密码..."

    local neo4j_admin="$NEO4J_HOME_DIR/bin/neo4j-admin"

    if [ ! -f "$neo4j_admin" ]; then
        print_error "neo4j-admin 不存在: $neo4j_admin"
        return 1
    fi

    export NEO4J_ACCEPT_LICENSE_AGREEMENT="yes"

    if run_cmd "设置初始密码" -- "$neo4j_admin" dbms set-initial-password "$NEO4J_PASSWORD"; then
        print_success "初始密码已设置"
        return 0
    else
        # 可能已初始化过，忽略错误
        log_warn "设置密码失败（可能已初始化过）"
        return 0
    fi
}

# ── 启动 ────────────────────────────────────────────────────

start_neo4j() {
    print_info "启动 Neo4j..."

    local neo4j_bin="$NEO4J_HOME_DIR/bin/neo4j"

    # 设置 NEO4J_HOME
    export NEO4J_HOME="$NEO4J_HOME_DIR"

    # 判断是否可用 systemd（WSL 中 systemctl 存在但 systemd 未运行）
    if systemctl is-system-running &>/dev/null; then
        # 有 systemd，使用 daemon 模式
        if run_cmd "启动 Neo4j" -- "$neo4j_bin" start; then
            print_success "Neo4j 已启动"
        else
            print_warn "Neo4j 启动可能失败，查看日志: $NEO4J_HOME_DIR/logs/neo4j.log"
            return 1
        fi
    else
        # 无 systemd（WSL），使用 console 模式 + setsid 彻底分离进程
        log_info "检测到无 systemd 环境，使用 console 模式启动 Neo4j..."
        setsid "$neo4j_bin" console > "$PROJECT_ROOT/logs/neo4j-console.log" 2>&1 &
        disown
        print_success "Neo4j 已启动（console 模式）"
    fi

    # 等待就绪
    print_info "等待 Neo4j 就绪..."
    local max_wait=60 waited=0
    while [ $waited -lt $max_wait ]; do
        if "$NEO4J_HOME_DIR/bin/cypher-shell" -u neo4j -p "$NEO4J_PASSWORD" "RETURN 1" &>/dev/null; then
            print_success "Neo4j 已就绪"
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done
    print_warn "Neo4j 启动超时，请手动检查"
    return 1
}

# ── 主流程 ──────────────────────────────────────────────────

main() {
    check_java || exit 1
    extract_neo4j || exit 1
    configure_neo4j || exit 1
    initialize_neo4j || exit 1
    start_neo4j || exit 1

    echo ""
    print_success "Neo4j $NEO4J_VERSION 安装完成"
    print_info "NEO4J_HOME: $NEO4J_HOME_DIR"
    print_info "Bolt:       bolt://localhost:7687"
    print_info "Browser:    http://localhost:7474"
    print_info "用户:       neo4j / $NEO4J_PASSWORD"
}

main