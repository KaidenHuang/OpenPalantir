"""任务契约 — 每个 task_type 的显式协议（类型常量 + 必填键 + 可选默认值）

旧版 base 是 9 行不起作用的空 ABC：task_type → handler 与 payload 字段两份协议
都是隐式的（创建点裸字符串 + handler 里逆向发现 .get(...)）。本基类让契约显式化：

1. ``TASK_TYPE``          —— 单一来源的类型常量（创建点与注册表共用）
2. ``REQUIRED_KEYS``      —— create_task 入口即校验（offline 可测）
3. ``OPTIONAL_DEFAULTS``  —— 可选参数默认值只写在这份契约里，handler 经
   :meth:`payload_value` 取值，默认值不再散落在 .get() 调用中
"""
from abc import ABC, abstractmethod
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from threading import Event, Lock
from typing import Any, Callable, Dict, List, Tuple


# 批量任务文件间并发的默认值与上限（上限防止单参数配置打爆模型服务）
CONCURRENCY_DEFAULT = 4
MAX_FILE_CONCURRENCY = 16


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


class TaskStopped(Exception):
    """stop_event 在单文件开始前命中 —— 计入 skipped 而非失败"""


def run_files_concurrently(
    task,
    files: List[str],
    concurrency: int,
    work_one: Callable[[str], Any],
    on_processed: Callable[[int, int], None],
) -> Dict[str, Any]:
    """批量任务并发骨架：文件间线程池 + 失败隔离 + 停止取消未启动项

    - work_one(file_path)：单文件完整流程。返回 False = 语义跳过（如指纹
      一致的幂等 skip），返回其他值 = 成功；抛 TaskStopped = 停止命中，
      抛其他异常 = 该文件失败（不终止整批）
    - on_processed(processed_done, total)：每收到一个结果回调一次，
      用于换算任务进度（在运行本函数的线程回调，回调方内部自带安全措施）

    stop 语义（文件粒度）：首个 TaskStopped 命中即取消队列中未启动项。
    已在运行的文件等待自然结束，结果照常计入 —— 不浪费已花的 LLM token。
    收尾统计 skipped 时，被取消项与停止项统一计入。

    Returns:
        {"succeeded": int, "skipped": int, "failures": [{"file", "reason"}]}
    """
    workers = max(1, min(int(concurrency or 1), MAX_FILE_CONCURRENCY))
    total = len(files)
    counters = {"succeeded": 0, "skipped": 0}
    failures: List[Dict[str, str]] = []
    processed = [0]
    lock = Lock()
    stop_requested = Event()

    def _advance(file_path: str, outcome: str, reason: str = "") -> None:
        with lock:
            if outcome == "succeeded":
                counters["succeeded"] += 1
            elif outcome == "skipped":
                counters["skipped"] += 1
            else:
                failures.append({"file": file_path, "reason": reason})
            processed[0] += 1
            done = processed[0]
        on_processed(done, total)

    def _guard(file_path: str):
        # 文件级停止粒度：开始前检查，命中即不发起本文件的 LLM 调用
        if stop_requested.is_set() or task.stop_event.is_set():
            raise TaskStopped()
        return work_one(file_path)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_guard, f): f for f in files}
        for future in as_completed(futures):
            file_path = futures[future]
            try:
                outcome = future.result()
                _advance(file_path, "skipped" if outcome is False else "succeeded")
            except TaskStopped:
                with lock:
                    already = stop_requested.is_set()
                    stop_requested.set()
                if not already:
                    # 未启动的项直接取消（cancelled → 也按 skipped 计）
                    executor.shutdown(wait=False, cancel_futures=True)
                _advance(file_path, "skipped")
            except CancelledError:
                _advance(file_path, "skipped")
            except Exception as e:
                _advance(file_path, "failed", str(e))
    return {"succeeded": counters["succeeded"], "skipped": counters["skipped"], "failures": failures}
