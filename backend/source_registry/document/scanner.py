"""文档源目录浏览 —— 本地源目录列举 / 可处理文件枚举（前端选择 + 批量任务共用）"""
import os
from typing import Dict, Iterator, List, Optional, Set, Tuple

from system.logger import logger
from utils.path_guard import safe_join


def _entry_path(entry: str) -> str:
    """清单条目 / 相对子目录 → "/" 分隔的相对路径口径（任务 payload 与前端都这么传）"""
    return str(entry).replace("\\", "/").strip("/")


def _relative(path: str, base_abs: str) -> str:
    return _entry_path(os.path.relpath(path, base_abs))


def _supported_extensions() -> Tuple[str, ...]:
    """扩展名白名单的唯一事实源是 ② 的转换器注册表；① 不在模块级依赖下游组件"""
    from content_extraction.document.converters import supported_extensions

    return supported_extensions()


def _is_supported(rel_path: str, exts: Tuple[str, ...]) -> bool:
    return os.path.splitext(rel_path)[1].lower() in exts


def browse_directory(base_path: str, prefix: str = "") -> dict:
    """列出 base_path 下 prefix 相对目录的文件与子目录（安全路径）"""
    try:
        current_path = safe_join(base_path, prefix)
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
            entries.append({"name": entry.name, "type": "dir",
                            "path": _relative(entry.path, base_abs)})
        elif entry.is_file():
            entries.append({"name": entry.name, "type": "file",
                            "path": _relative(entry.path, base_abs),
                            "size": entry.stat().st_size,
                            "ext": os.path.splitext(entry.name)[1].lower()})

    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    return {"base_path": base_abs,
            "current_path": _relative(current_path, base_abs),
            "entries": entries}


# ── 可处理文件枚举（批量任务的清单来源） ─────────────────────────

def _walk_files(root: str) -> Iterator[str]:
    """root 是文件时只产出它自己，是目录时递归产出其下全部文件"""
    if os.path.isfile(root):
        yield root
        return
    for dirpath, _, names in os.walk(root):
        for name in names:
            yield os.path.join(dirpath, name)


def list_supported_files(base_path: str, subdirs: Optional[List[str]] = None) -> List[str]:
    """递归扫描出可解析文件的相对路径清单（"/" 分隔，去重排序）

    subdirs 条目经 safe_join 越界拒绝（ValueError 由调用方按不合法清单处理）。
    """
    base_abs = os.path.abspath(base_path)
    roots = [safe_join(base_abs, _entry_path(s)) for s in subdirs] if subdirs else [base_abs]
    exts = _supported_extensions()
    collected: Set[str] = set()
    for root in roots:
        for path in _walk_files(root):
            rel = _relative(path, base_abs)
            if _is_supported(rel, exts):
                collected.add(rel)
    return sorted(collected)


def collect_source_files(base_path: str, entries: Optional[List[str]]) -> Tuple[List[str], List[Dict[str, str]]]:
    """批量任务 payload 的文件条目 → (可处理清单, 清单级失败)

    entries=None → 全源扫描；条目是目录 → 递归展开；条目是文件但不在
    扩展名白名单 → 丢弃并记日志（任务语义是"可处理文件"，不按失败报）。
    条目不存在 → 以清单级失败返回，让任务结果里可解释。
    """
    if entries is None:
        return list_supported_files(base_path), []

    base_abs = os.path.abspath(base_path)
    failures: List[Dict[str, str]] = []
    candidates: Set[str] = set()
    for entry in entries:
        path = _entry_path(entry)
        if not path:
            failures.append({"file": str(entry), "reason": "空路径条目"})
            continue
        try:
            full = safe_join(base_abs, path)
        except ValueError as e:
            raise ValueError(f"文件清单条目越界: {path} ({e})")
        if os.path.isdir(full):
            candidates.update(list_supported_files(base_path, [path]))
        elif os.path.isfile(full):
            candidates.add(path)
        else:
            failures.append({"file": path, "reason": "文件不存在"})

    exts = _supported_extensions()
    files: List[str] = []
    for rel in sorted(candidates):
        if _is_supported(rel, exts):
            files.append(rel)
        else:
            logger.info(f"[scanner] 清单条目不支持解析，已过滤: {rel}")
    return files, failures


def collect_for_source(source_id: str, entries: Optional[List[str]] = None) -> Tuple[str, List[str], List[Dict[str, str]]]:
    """批量任务入口：校验存在且本地的文档源 → (root_path, 可处理清单, 清单级失败)"""
    from config.database import SessionLocal
    from source_registry.document.registry import document_source_registry

    db = SessionLocal()
    try:
        base_path = document_source_registry.root_path(db, source_id)
    finally:
        db.close()
    files, failures = collect_source_files(base_path, entries)
    return base_path, files, failures
