#!/bin/bash
# ============================================================
# OpenPalantir 公共日志/执行辅助函数库
# 所有 install/uninstall/service 脚本通过 source 加载此文件。
# ============================================================

set -euo pipefail

# 项目根目录（scripts/lib/ → scripts/ → 项目根）
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE=""

# ── 日志函数 ────────────────────────────────────────────────

init_log() {
    # 初始化日志文件。参数: <action> [log_file_path]
    # 若已传入 LOG_FILE 路径（由父脚本合并），则沿用；否则新建时间戳日志。
    local action="$1"
    local log_path="${2:-}"

    if [ -n "$log_path" ] && [ -f "$log_path" ]; then
        LOG_FILE="$log_path"
        log_info "--- $action 开始 ---"
        return
    fi

    mkdir -p "$LOG_DIR"
    local timestamp
    timestamp=$(date +"%Y%m%d-%H%M%S")
    LOG_FILE="$LOG_DIR/${action}-${timestamp}.log"

    cat > "$LOG_FILE" <<EOF
========================================
OpenPalantir $action
开始时间: $(date '+%Y-%m-%d %H:%M:%S')
========================================
EOF
}

log_info()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO]  $*" | tee -a "${LOG_FILE:-/dev/null}"; }
log_warn()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN]  $*" | tee -a "${LOG_FILE:-/dev/null}"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "${LOG_FILE:-/dev/null}"; }

# ── 执行辅助 ────────────────────────────────────────────────

run_cmd() {
    # 执行命令并记录输出。参数: <描述> -- <命令...>
    # 示例: run_cmd "安装 Python 依赖" -- pip install -r requirements.txt
    local desc="$1"; shift
    # 跳过 "--" 分隔符
    if [ "$1" = "--" ]; then shift; fi

    log_info "执行: $desc"
    log_info "命令: $*"

    if "$@" >> "$LOG_FILE" 2>&1; then
        log_info "$desc - 完成"
        return 0
    else
        local rc=$?
        log_error "$desc - 失败 (退出码: $rc)"
        return $rc
    fi
}

run_cmd_no_fail() {
    # 执行命令，失败时仅警告不退出。参数同 run_cmd。
    local desc="$1"; shift
    if [ "$1" = "--" ]; then shift; fi

    log_info "执行: $desc"
    if "$@" >> "$LOG_FILE" 2>&1; then
        log_info "$desc - 完成"
    else
        log_warn "$desc - 失败（非致命，继续）"
    fi
}

# ── 进程检测 ────────────────────────────────────────────────

kill_by_pattern() {
    # 按进程名模式查找并终止进程。参数: <pattern>
    local pattern="$1"
    local pids
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        log_info "终止进程: $pattern (PID: $pids)"
        echo "$pids" | xargs kill 2>/dev/null || true
        sleep 2
        # 强制终止残留
        pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "$pids" | xargs kill -9 2>/dev/null || true
        fi
    fi
}

# ── 颜色输出 ────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_success() { echo -e "${GREEN}[✓]${NC} $*"; }
print_error()   { echo -e "${RED}[✗]${NC} $*"; }
print_warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
print_info()    { echo -e "${BLUE}[i]${NC} $*"; }

# ── 路径辅助 ────────────────────────────────────────────────

# 确保以项目根目录为基准的相对路径正确
backend_dir()  { echo "$PROJECT_ROOT/backend"; }
frontend_dir() { echo "$PROJECT_ROOT/frontend"; }
debezium_local_dir() { echo "$PROJECT_ROOT/dependencies/debezium/local"; }
debezium_extracted_dir() { echo "$PROJECT_ROOT/dependencies/debezium/extracted"; }
debezium_instances_dir() { echo "$PROJECT_ROOT/dependencies/debezium/instances"; }