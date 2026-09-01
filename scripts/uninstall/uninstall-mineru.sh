#!/bin/bash
# ============================================================
# OpenPalantir MinerU 卸载脚本 (Linux)
# 功能: 卸载 magic-pdf 及其依赖，清理模型缓存
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/helpers.sh"

init_log "uninstall-mineru"

MODEL_DIR="$HOME/.cache/modelscope/hub"

print_info "卸载 MinerU..."

# ── 卸载 magic-pdf ────────────────────────────────────────────

# 激活虚拟环境
venv_dir="$PROJECT_ROOT/backend/venv"
if [ -f "$venv_dir/bin/activate" ]; then
    source "$venv_dir/bin/activate"
    log_info "已激活虚拟环境"
fi

# 卸载 magic-pdf
if pip show magic-pdf &>/dev/null 2>&1; then
    print_info "卸载 magic-pdf..."
    run_cmd_no_fail "pip uninstall magic-pdf" -- pip uninstall -y magic-pdf
    print_success "magic-pdf 已卸载"
else
    print_info "magic-pdf 未安装，跳过 pip 卸载"
fi

# 卸载相关依赖（可选，交互式确认）
print_info "以下为 magic-pdf 相关的重型依赖，可根据需要手动卸载:"
echo "  pip uninstall -y torch torchvision torchaudio"
echo "  pip uninstall -y transformers"
echo "  pip uninstall -y modelscope"
echo "  pip uninstall -y opencv-python-headless"

deactivate 2>/dev/null || true

# ── 清理模型缓存 ──────────────────────────────────────────────

if [ -d "$MODEL_DIR" ]; then
    print_warn "模型缓存目录存在: $MODEL_DIR"
    print_info "如需清理请手动执行: rm -rf $MODEL_DIR"
    print_info "（模型文件较大，保留可避免下次安装重新下载）"
else
    print_info "模型缓存目录不存在，无需清理"
fi

print_success "MinerU 卸载完成"