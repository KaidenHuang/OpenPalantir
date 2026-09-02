#!/bin/bash
# ============================================================
# OpenPalantir MinerU 安装脚本 (Linux)
# 功能: 安装系统依赖 → pip 安装 magic-pdf → 下载模型 → 验证
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "install-mineru"

MAGIC_PDF_PACKAGE="magic-pdf[full]"
MODEL_DIR="$HOME/.cache/modelscope/hub"  # magic-pdf 默认模型缓存路径

# ── 检查 Python 环境 ─────────────────────────────────────────

check_python() {
    print_info "检查 Python 环境..."

    if ! command -v python3 &> /dev/null; then
        print_error "未找到 python3。MinerU 需要 Python 3.10 ~ 3.13"
        return 1
    fi

    local py_ver
    py_ver=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
    local major minor
    major=$(echo "$py_ver" | cut -d'.' -f1)
    minor=$(echo "$py_ver" | cut -d'.' -f2)

    if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ] && [ "$minor" -le 13 ] 2>/dev/null; then
        print_success "Python $py_ver 满足要求（需要 3.10 ~ 3.13）"
    elif [ "$major" -gt 3 ] 2>/dev/null; then
        print_warn "Python $py_ver 可能不兼容，建议使用 3.10 ~ 3.13"
    else
        print_error "Python $py_ver 不满足要求，需要 3.10 ~ 3.13"
        if [ "$major" -eq 3 ] && [ "$minor" -ge 14 ] 2>/dev/null; then
            print_info "Python 3.14+ 太新，magic-pdf 依赖尚未支持。请使用 Python 3.12 或 3.13"
            print_info "  创建虚拟环境: python3.12 -m venv backend/venv"
        fi
        return 1
    fi
}

# ── 安装系统依赖 ─────────────────────────────────────────────

install_system_deps() {
    print_info "安装系统依赖（libGL、libglib）..."

    # 检查 sudo 是否可用
    if ! sudo -n true 2>/dev/null; then
        print_warn "sudo 不可用或需要密码，跳过系统依赖安装"
        print_info "请手动安装: libGL、glib2、libgomp、libSM、libXext、libXrender"
        print_info "  Debian/Ubuntu: sudo apt install -y libgl1-mesa-glx libglib2.0-0 libgomp1 libsm6 libxext6 libxrender-dev"
        print_info "  RHEL/Fedora:   sudo dnf install -y mesa-libGL glib2 libgomp libSM libXext libXrender"
        return 0  # 非致命
    fi

    if command -v apt-get &> /dev/null; then
        print_info "检测到 apt 包管理器"
        run_cmd "安装系统依赖" -- sudo -n apt-get update -qq
        run_cmd "安装系统依赖" -- sudo -n apt-get install -y -qq \
            libgl1-mesa-glx \
            libglib2.0-0 \
            libgomp1 \
            libsm6 \
            libxext6 \
            libxrender-dev 2>/dev/null || true
        # 忽略重复安装的报错
        print_success "系统依赖安装完成 (apt)"
    elif command -v dnf &> /dev/null; then
        print_info "检测到 dnf 包管理器"
        run_cmd "安装系统依赖" -- sudo -n dnf install -y \
            mesa-libGL \
            glib2 \
            libgomp \
            libSM \
            libXext \
            libXrender 2>/dev/null || true
        print_success "系统依赖安装完成 (dnf)"
    elif command -v yum &> /dev/null; then
        print_info "检测到 yum 包管理器"
        run_cmd "安装系统依赖" -- sudo -n yum install -y \
            mesa-libGL \
            glib2 \
            libgomp \
            libSM \
            libXext \
            libXrender 2>/dev/null || true
        print_success "系统依赖安装完成 (yum)"
    else
        print_warn "未检测到已知包管理器，跳过系统依赖安装"
        print_info "请手动安装: libGL、glib2、libgomp、libSM、libXext、libXrender"
    fi
}

# ── 安装 magic-pdf ────────────────────────────────────────────

install_magic_pdf() {
    print_info "安装 magic-pdf（含完整依赖）..."

    local venv_dir="$PROJECT_ROOT/backend/venv"
    local pip_cmd="python3 -m pip"

    # 尝试使用虚拟环境的 pip，不可用时回退到系统 Python 的 pip
    if [ -f "$venv_dir/bin/python3" ]; then
        if "$venv_dir/bin/python3" -m pip --version &>/dev/null; then
            # venv 的 pip 可用，直接使用
            pip_cmd="$venv_dir/bin/python3 -m pip"
        else
            # venv 的 pip 不可用，使用系统 Python 的 pip 安装到 venv
            local py_ver site_pkgs
            py_ver=$("$venv_dir/bin/python3" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "3.14")
            site_pkgs="$venv_dir/lib/python${py_ver}/site-packages"
            mkdir -p "$site_pkgs"
            log_info "venv 的 pip 不可用，使用系统 Python 的 pip 安装到: $site_pkgs"
            pip_cmd="python3 -m pip install --target $site_pkgs"
        fi
    fi

    log_info "pip 命令前缀: $pip_cmd"

    # 优先使用阿里云镜像，失败则回退默认源
    if [[ "$pip_cmd" == *"--target"* ]]; then
        # pip_cmd 已包含 install --target，直接接包名
        if run_cmd "pip 安装 magic-pdf（阿里云镜像）" -- \
            $pip_cmd "$MAGIC_PDF_PACKAGE" \
                -i https://mirrors.aliyun.com/pypi/simple \
                --trusted-host mirrors.aliyun.com; then
            print_success "magic-pdf 安装完成"
        else
            log_warn "阿里云镜像安装失败，尝试默认源..."
            run_cmd "pip 安装 magic-pdf（默认源）" -- \
                $pip_cmd "$MAGIC_PDF_PACKAGE"
            print_success "magic-pdf 安装完成"
        fi
    else
        if run_cmd "pip 安装 magic-pdf（阿里云镜像）" -- \
            $pip_cmd install -U "$MAGIC_PDF_PACKAGE" \
                -i https://mirrors.aliyun.com/pypi/simple \
                --trusted-host mirrors.aliyun.com; then
            print_success "magic-pdf 安装完成"
        else
            log_warn "阿里云镜像安装失败，尝试默认源..."
            run_cmd "pip 安装 magic-pdf（默认源）" -- \
                $pip_cmd install -U "$MAGIC_PDF_PACKAGE"
            print_success "magic-pdf 安装完成"
        fi
    fi
}

# ── 下载模型 ──────────────────────────────────────────────────

download_models() {
    print_info "下载 MinerU 模型文件..."

    # 确定 Python 解释器
    local py_cmd="python3"
    local venv_dir="$PROJECT_ROOT/backend/venv"
    if [ -f "$venv_dir/bin/python3" ]; then
        py_cmd="$venv_dir/bin/python3"
    fi

    # magic-pdf 首次运行时会自动下载模型，这里用一次空跑触发下载
    if $py_cmd -c "from modelscope.hub.snapshot_download import snapshot_download; print('modelscope 可用')" 2>/dev/null; then
        print_info "通过 modelscope 预下载模型..."
        $py_cmd -c "
import os
os.environ['MODELSCOPE_CACHE'] = os.path.expanduser('$MODEL_DIR')
try:
    from modelscope.hub.snapshot_download import snapshot_download
    models = [
        'opendatalab/PDF-Extract-Kit-1.0',
    ]
    for m in models:
        try:
            print(f'下载模型: {m}')
            snapshot_download(m)
        except Exception as e:
            print(f'模型 {m} 下载失败: {e}')
    print('模型下载完成')
except Exception as e:
    print(f'模型预下载失败: {e}')
" 2>/dev/null || {
            print_warn "模型预下载失败（首次运行 magic-pdf 时会自动下载）"
        }
    else
        print_warn "modelscope 不可用，首次运行 magic-pdf 时会自动下载模型"
    fi

    print_success "模型下载步骤完成"
}

# ── 验证安装 ──────────────────────────────────────────────────

verify_installation() {
    print_info "验证 MinerU 安装..."

    local py_cmd="python3"
    local venv_dir="$PROJECT_ROOT/backend/venv"
    if [ -f "$venv_dir/bin/python3" ]; then
        py_cmd="$venv_dir/bin/python3"
    fi

    # 验证 CLI 可用
    if $py_cmd -m magic_pdf.tools.cli --help &>/dev/null; then
        print_success "magic-pdf CLI 可用"
    else
        print_warn "magic-pdf CLI 验证失败，请手动检查"
        return 1
    fi

    # 输出版本信息
    local version
    version=$($py_cmd -c "import magic_pdf; print(getattr(magic_pdf, '__version__', 'unknown'))" 2>/dev/null || echo "unknown")
    print_info "magic-pdf 版本: $version"
}

# ── 主流程 ────────────────────────────────────────────────────

main() {
    echo ""
    echo "============================================================"
    echo "  OpenPalantir MinerU 安装"
    echo "  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"

    check_python || exit 1
    install_system_deps || print_warn "系统依赖安装失败（非致命，magic-pdf 可能仍可运行）"
    install_magic_pdf || exit 1
    download_models || print_warn "模型下载失败（非致命，首次运行时会自动下载）"
    verify_installation || exit 1

    echo ""
    print_success "MinerU 安装完成"
    print_info "magic-pdf CLI:  python -m magic_pdf.tools.cli"
    print_info "模型缓存目录:  $MODEL_DIR"
    echo ""
    print_info "验证命令:"
    echo "  python3 -m magic_pdf.tools.cli --help"
}

main