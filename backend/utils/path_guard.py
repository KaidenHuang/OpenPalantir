"""路径围栏：用户可控相对路径拼接的唯一守卫。

startswith 前缀判断可被同级目录绕过（如 /data/src ≠ /data/src_other），
必须用 commonpath 判定严格包含关系。
"""
import os


def safe_join(base: str, *parts: str) -> str:
    """拼接 base 与相对子路径；任何逃逸出 base（含绝对路径、..、驶入同级目录）的输入直接拒绝。"""
    if any(os.path.isabs(p) for p in parts):
        raise ValueError("路径越界: 不接受绝对路径")
    base_abs = os.path.abspath(base)
    full = os.path.abspath(os.path.join(base_abs, *parts))
    if os.path.commonpath([base_abs, full]) != base_abs:
        raise ValueError(f"路径越界: {os.path.join(*parts)}")
    return full
