"""文档源目录浏览 —— 本地源的目录列举（前端文件选择用）"""
import os
from typing import List

from system.logger import logger


def browse_directory(base_path: str, prefix: str = "") -> dict:
    """列出 base_path 下 prefix 相对目录的文件与子目录（安全路径）"""
    try:
        current_path = prefix
        if prefix:
            from utils.path_guard import safe_join
            current_path = safe_join(base_path, prefix)
        else:
            current_path = os.path.abspath(base_path)
    except ValueError as e:
        raise ValueError(f"路径不合法: {e}")

    if not os.path.exists(current_path):
        raise FileNotFoundError(f"路径不存在: {current_path}")
    if os.path.isfile(current_path):
        raise NotADirectoryError(f"路径是文件而非目录: {current_path}")

    base_abs = os.path.abspath(base_path)
    entries: List[dict] = []
    for entry in os.scandir(current_path):
        if entry.is_dir():
            entries.append({
                "name": entry.name,
                "type": "dir",
                "path": os.path.relpath(entry.path, base_abs).replace("\\", "/"),
            })
        elif entry.is_file():
            ext = os.path.splitext(entry.name)[1].lower()
            entries.append({
                "name": entry.name,
                "type": "file",
                "path": os.path.relpath(entry.path, base_abs).replace("\\", "/"),
                "size": entry.stat().st_size,
                "ext": ext,
            })

    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    rel = os.path.relpath(current_path, base_abs).replace("\\", "/") or ""
    return {"base_path": base_abs, "current_path": rel, "entries": entries}
