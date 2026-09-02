#!/bin/bash
PY=/mnt/f/Code/OpenPalantir/backend/venv/bin/python3
PDF=/mnt/f/Code/OpenPalantir/tests/test_sample.pdf
OUT=/tmp/mineru_test_$(date +%s)

echo "=== 输入 PDF ==="
ls -lh "$PDF"

echo ""
echo "=== 运行 magic-pdf CLI ==="
mkdir -p "$OUT"
$PY -m magic_pdf.tools.cli -p "$PDF" -o "$OUT" -m auto -l zh 2>&1
echo "退出码: $?"

echo ""
echo "=== 输出目录结构 ==="
find "$OUT" -type f 2>&1

echo ""
echo "=== Markdown 输出 ==="
find "$OUT" -name "*.md" -exec cat {} \; 2>&1

echo ""
echo "=== 清理 ==="
rm -rf "$OUT"
echo "完成"