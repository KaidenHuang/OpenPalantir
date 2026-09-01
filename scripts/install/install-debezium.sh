#!/bin/bash
# ============================================================
# OpenPalantir Debezium Server 安装脚本
# 功能: 下载 Debezium Server + 连接器 → 解压 → 配置 → 验证
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "install-debezium"

# ── 常量 ────────────────────────────────────────────────────
DEBEZIUM_VERSION="3.5.2.Final"
MAVEN_BASE="https://repo1.maven.org/maven2/io/debezium"
LOCAL_DIR="$(debezium_local_dir)"
EXTRACTED_DIR="$(debezium_extracted_dir)"
INSTANCES_DIR="$(debezium_instances_dir)"

# 需要下载的组件列表
declare -A COMPONENTS=(
    ["debezium-server-dist"]=".tar.gz"
    ["debezium-connector-mysql"]="-plugin.tar.gz"
    ["debezium-connector-postgres"]="-plugin.tar.gz"
    ["debezium-connector-oracle"]="-plugin.tar.gz"
    ["debezium-connector-sqlserver"]="-plugin.tar.gz"
)

# ── 下载 ────────────────────────────────────────────────────

download_component() {
    local artifact="$1" version="$2" suffix="$3"
    local filename="${artifact}-${version}${suffix}"
    local filepath="$LOCAL_DIR/$filename"
    local url="${MAVEN_BASE}/${artifact}/${version}/${filename}"
    local sha_url="${url}.sha1"

    if [ -f "$filepath" ] && [ -s "$filepath" ]; then
        log_info "已存在，跳过下载: $filename"
        return 0
    fi

    print_info "下载: $filename"
    log_info "从 $url 下载..."

    # 确定下载工具（一次判定）
    local dl_cmd dl_opts
    if command -v wget &> /dev/null; then
        dl_cmd="wget"
        dl_opts="-q -O"
    elif command -v curl &> /dev/null; then
        dl_cmd="curl"
        dl_opts="-L -s -o"
    else
        log_error "需要 wget 或 curl 才能下载"
        return 1
    fi

    run_cmd "下载 $filename" -- $dl_cmd $dl_opts "$filepath" "$url"

    # 下载 SHA1 校验文件
    local sha_file="$filepath.sha1"
    $dl_cmd $dl_opts "$sha_file" "$sha_url" 2>/dev/null || true

    # SHA1 校验
    if [ -f "$sha_file" ] && [ -s "$sha_file" ]; then
        local expected actual
        expected=$(awk '{print $1}' "$sha_file")
        actual=$(sha1sum "$filepath" | awk '{print $1}')
        if [ "$expected" != "$actual" ]; then
            log_error "SHA1 校验失败: $filename"
            log_error "  期望: $expected"
            log_error "  实际: $actual"
            return 1
        fi
        log_info "SHA1 校验通过: $filename"
    else
        log_warn "无法下载 SHA1 文件，跳过校验: $filename"
    fi
}

ensure_packages() {
    print_info "检查 Debezium 安装包..."
    mkdir -p "$LOCAL_DIR"

    for artifact in "${!COMPONENTS[@]}"; do
        local suffix="${COMPONENTS[$artifact]}"
        download_component "$artifact" "$DEBEZIUM_VERSION" "$suffix" || {
            print_error "下载失败: $artifact"
            return 1
        }
    done
    print_success "所有安装包就绪"
}

# ── 解压 ────────────────────────────────────────────────────

extract_server() {
    print_info "解压 Debezium Server..."
    mkdir -p "$EXTRACTED_DIR"

    local server_archive="$LOCAL_DIR/debezium-server-dist-${DEBEZIUM_VERSION}.tar.gz"
    if [ ! -f "$server_archive" ]; then
        print_error "Server 包不存在: $server_archive"
        return 1
    fi

    run_cmd "解压 Debezium Server" -- tar -xzf "$server_archive" -C "$EXTRACTED_DIR"

    # 新版 Debezium 发行版可能解压到子目录，扁平化处理
    local subdirs
    subdirs=$(find "$EXTRACTED_DIR" -maxdepth 1 -type d ! -name '.' ! -name "$(basename "$EXTRACTED_DIR")" 2>/dev/null)
    local subdir_count
    subdir_count=$(echo "$subdirs" | grep -c . 2>/dev/null || echo 0)
    if [ "$subdir_count" -eq 1 ] && [ -d "$subdirs" ]; then
        log_info "检测到子目录: $(basename "$subdirs")，扁平化处理..."
        local tmp_flat="$EXTRACTED_DIR.flat_tmp"
        # 清理可能残留的临时目录
        rm -rf "$tmp_flat" 2>/dev/null || true
        mv "$subdirs" "$tmp_flat"
        # 移动所有内容到 extracted/
        shopt -s dotglob
        mv "$tmp_flat"/* "$EXTRACTED_DIR"/ 2>/dev/null || true
        shopt -u dotglob
        rmdir "$tmp_flat" 2>/dev/null || true
    fi

    # 检查 run.sh 是否存在（Linux 下 Debezium 发行版自带）
    if [ -f "$EXTRACTED_DIR/run.sh" ]; then
        # 确保可执行权限
        chmod +x "$EXTRACTED_DIR/run.sh"
        log_info "run.sh 已就绪（可执行）"
    elif [ -f "$EXTRACTED_DIR/run.bat" ]; then
        # 如果只有 run.bat（Windows 发行版），需要生成 run.sh
        log_warn "未找到 run.sh，根据 run.bat 生成..."
        generate_run_sh
    else
        log_error "未找到 Debezium 启动脚本 (run.sh / run.bat)"
        return 1
    fi

    print_success "Debezium Server 解压完成"
}

generate_run_sh() {
    # 如果发行版只有 run.bat，生成等效的 run.sh
    cat > "$EXTRACTED_DIR/run.sh" <<'RUNSH'
#!/bin/bash
# Debezium Server 启动脚本（由 OpenPalantir 自动生成）
cd "$(dirname "$0")"

# 查找 JAVA_HOME
if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/java" ]; then
    JAVA_BIN="$JAVA_HOME/bin/java"
else
    JAVA_BIN="java"
fi

# 查找 runner.jar
RUNNER_JAR=$(ls "$(dirname "$0")"/debezium-server-*runner.jar 2>/dev/null | head -1)
if [ -z "$RUNNER_JAR" ]; then
    echo "错误: 未找到 debezium-server-*runner.jar" >&2
    exit 1
fi

exec "$JAVA_BIN" -jar "$RUNNER_JAR"
RUNSH
    chmod +x "$EXTRACTED_DIR/run.sh"
    log_info "已生成 run.sh"
}

extract_connectors() {
    print_info "解压连接器插件..."

    local connector_types=("mysql" "postgres" "oracle" "sqlserver")
    for ctype in "${connector_types[@]}"; do
        local archive="$LOCAL_DIR/debezium-connector-${ctype}-${DEBEZIUM_VERSION}-plugin.tar.gz"
        if [ ! -f "$archive" ]; then
            log_warn "连接器包不存在，跳过: $ctype"
            continue
        fi
        run_cmd "解压 ${ctype} 连接器" -- tar -xzf "$archive" -C "$EXTRACTED_DIR"
    done

    print_success "连接器插件解压完成"
}

# ── 配置 ────────────────────────────────────────────────────

configure_debezium() {
    print_info "生成默认 Debezium 配置..."

    local config_dir="$EXTRACTED_DIR/config"
    mkdir -p "$config_dir"

    # 生成各连接器模板配置
    generate_mysql_template "$config_dir"
    generate_postgres_template "$config_dir"

    # 默认 application.properties → 复制 mysql 模板
    cp "$config_dir/application.properties.mysql" "$config_dir/application.properties"
    log_info "默认配置: application.properties (MySQL)"

    print_success "Debezium 配置生成完成"
}

generate_mysql_template() {
    local config_dir="$1"
    cat > "$config_dir/application.properties.mysql" <<'MYSQL'
# ============================================================
# Debezium Server - MySQL Connector 模板
# ============================================================
# 本文件为模板，请通过前端「配置 CDC」按钮自动生成实例配置。
# ============================================================
debezium.sink.type=redis
debezium.sink.redis.address=127.0.0.1:6379
debezium.sink.redis.stream-type=stream

debezium.source.snapshot.mode=no_data

debezium.source.offset.storage=org.apache.kafka.connect.storage.FileOffsetBackingStore
debezium.source.offset.storage.file.filename=data/debezium/offsets/offsets.dat
debezium.source.offset.flush.interval.ms=5000

quarkus.log.level=INFO
quarkus.log.console.json=false
quarkus.http.port=0

debezium.source.connector.class=io.debezium.connector.mysql.MySqlConnector
debezium.source.database.hostname=localhost
debezium.source.database.port=3306
debezium.source.database.user=cdc_user
debezium.source.database.password=cdc_password
debezium.source.database.connectionTimeZone=Asia/Shanghai
debezium.source.database.server.id=18943
debezium.source.topic.prefix=openpalantir
debezium.source.database.include.list=employees

debezium.source.schema.history.internal=io.debezium.storage.redis.history.RedisSchemaHistory
debezium.source.schema.history.internal.redis.address=127.0.0.1:6379
debezium.source.schema.history.internal.redis.key=schemahistory.openpalantir
MYSQL
}

generate_postgres_template() {
    local config_dir="$1"
    cat > "$config_dir/application.properties.postgres" <<'PGSQL'
# ============================================================
# Debezium Server - PostgreSQL Connector 模板
# ============================================================
# 本文件为模板，请通过前端「配置 CDC」按钮自动生成实例配置。
# ============================================================
debezium.sink.type=redis
debezium.sink.redis.address=127.0.0.1:6379
debezium.sink.redis.stream-type=stream

debezium.source.snapshot.mode=no_data

debezium.source.offset.storage=org.apache.kafka.connect.storage.FileOffsetBackingStore
debezium.source.offset.storage.file.filename=data/debezium/offsets/offsets.dat
debezium.source.offset.flush.interval.ms=5000

quarkus.log.level=INFO
quarkus.log.console.json=false
quarkus.http.port=0

debezium.source.connector.class=io.debezium.connector.postgresql.PostgresConnector
debezium.source.database.hostname=localhost
debezium.source.database.port=5432
debezium.source.database.user=cdc_user
debezium.source.database.password=cdc_password
debezium.source.database.dbname=employees
debezium.source.topic.prefix=openpalantir
debezium.source.table.include.list=public.*
debezium.source.plugin.name=pgoutput

debezium.source.schema.history.internal=io.debezium.storage.redis.history.RedisSchemaHistory
debezium.source.schema.history.internal.redis.address=127.0.0.1:6379
debezium.source.schema.history.internal.redis.key=schemahistory.openpalantir
PGSQL
}

# ── 验证 ────────────────────────────────────────────────────

verify_installation() {
    print_info "验证 Debezium 安装..."

    # 检查 Java
    if ! command -v java &> /dev/null; then
        print_error "未找到 Java，请安装 OpenJDK 17 或更高版本"
        print_info "  sudo apt install -y openjdk-17-jdk"
        return 1
    fi
    local java_ver
    java_ver=$(java -version 2>&1 | head -1)
    print_info "Java 版本: $java_ver"

    # 检查关键文件
    local checks=(
        "$EXTRACTED_DIR/run.sh"
        "$EXTRACTED_DIR/lib"
        "$EXTRACTED_DIR/connectors"
    )
    for check in "${checks[@]}"; do
        if [ -e "$check" ]; then
            log_info "  [✓] $check"
        else
            log_error "  [✗] 缺失: $check"
        fi
    done

    print_success "Debezium 安装验证完成"
}

# ── 主流程 ──────────────────────────────────────────────────

main() {
    ensure_packages || exit 1
    extract_server || exit 1
    extract_connectors || exit 1
    configure_debezium || exit 1
    verify_installation || exit 1

    # 创建多实例目录
    mkdir -p "$INSTANCES_DIR"

    print_success "Debezium Server ${DEBEZIUM_VERSION} 安装完成"
    echo ""
    print_info "Debezium 安装目录: $EXTRACTED_DIR"
    print_info "多实例目录:       $INSTANCES_DIR"
    print_info "配置文件:         $EXTRACTED_DIR/config/application.properties"
    echo ""
    print_info "CDC 配置请通过前端「数据库管理」→「配置 CDC」按钮完成"
}

main