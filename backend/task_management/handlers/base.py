"""任务契约 — 每个 task_type 的显式协议（类型常量 + 必填键 + 可选默认值）

旧版 base 是 9 行不起作用的空 ABC：task_type → handler 与 payload 字段两份协议
都是隐式的（创建点裸字符串 + handler 里逆向发现 .get(...)）。本基类让契约显式化：

1. ``TASK_TYPE``          —— 单一来源的类型常量（创建点与注册表共用）
2. ``REQUIRED_KEYS``      —— create_task 入口即校验（offline 可测）
3. ``OPTIONAL_DEFAULTS``  —— 可选参数默认值只写在这份契约里，handler 经
   :meth:`payload_value` 取值，默认值不再散落在 .get() 调用中
"""
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Tuple


class TaskHandler(ABC):

    TASK_TYPE: str = ""
    REQUIRED_KEYS: Tuple[str, ...] = ()
    OPTIONAL_DEFAULTS: Dict[str, Any] = {}

    @abstractmethod
    def execute(self, task, progress_callback: Callable[[int], None]) -> Any:
        """执行任务，通过 progress_callback 报告进度。返回结果。"""
        ...

    def payload_value(self, task, key: str) -> Any:
        """按本 handler 的契约从 task.payload 取值：显式值优先，否则取契约默认"""
        value = task.payload.get(key)
        if value is not None:
            return value
        if key in self.OPTIONAL_DEFAULTS:
            return self.OPTIONAL_DEFAULTS[key]
        raise KeyError(
            f"{self.__class__.__name__}: payload 缺少参数 '{key}'"
            f"（REQUIRED_KEYS/OPTIONAL_DEFAULTS 未声明）"
        )

    @classmethod
    def validate_payload(cls, payload: Dict[str, Any]) -> None:
        """create_task 入口校验：缺失必填键直接拒绝（interface 即测试面）"""
        missing = [k for k in cls.REQUIRED_KEYS if payload.get(k) in (None, "")]
        if missing:
            raise ValueError(f"{cls.__name__}({cls.TASK_TYPE}) payload 缺少必要参数: {missing}")
