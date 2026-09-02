#!/bin/bash
PY=/mnt/f/Code/OpenPalantir/backend/venv/bin/python3
MODELS_DIR=/root/.cache/modelscope/hub

export MODELSCOPE_CACHE=/root/.cache/modelscope

$PY -c "
import os
from modelscope.hub.snapshot_download import snapshot_download
print('下载 PDF-Extract-Kit-1.0 模型...')
snapshot_download('opendatalab/PDF-Extract-Kit-1.0', cache_dir='$MODELS_DIR')
print('下载完成')
" 2>&1
echo "退出码: $?"