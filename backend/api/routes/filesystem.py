import os
import string
from fastapi import APIRouter, HTTPException
from system.logger import logger

router = APIRouter()


def _list_drive_letters():
    """Windows 下列出所有可用驱动器"""
    drives = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.exists(root):
            drives.append({
                "name": root,
                "path": root,
                "is_dir": True,
                "size": 0,
            })
    return drives


def _list_directory(path: str):
    """列出目录内容"""
    items = []
    try:
        for entry in os.scandir(path):
            try:
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if not entry.is_dir() else 0,
                })
            except (PermissionError, OSError):
                items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "is_dir": True,  # 无法访问时假设为目录
                    "size": 0,
                })
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"无权限访问: {path}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"路径不存在: {path}")

    # 排序：目录在前，文件在后，按名称排序
    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return items


@router.get("/browse")
async def browse_filesystem(path: str = ""):
    """浏览文件系统，返回指定路径下的文件和目录列表"""
    try:
        # 空路径或根路径 → 返回驱动器列表
        if not path or path.strip() in ("", "/", "\\"):
            items = _list_drive_letters()
            return {
                "current_path": "",
                "parent_path": None,
                "items": items,
            }

        path = os.path.abspath(path.strip())

        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"路径不存在: {path}")

        if os.path.isfile(path):
            # 如果是文件，返回其所在目录
            parent = os.path.dirname(path)
            items = _list_directory(parent)
            return {
                "current_path": parent,
                "parent_path": os.path.dirname(parent) if parent else None,
                "items": items,
            }

        # 是目录
        items = _list_directory(path)
        parent_path = os.path.dirname(path) if path else None

        return {
            "current_path": path,
            "parent_path": parent_path,
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"浏览文件系统失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
