from abc import ABC, abstractmethod
from typing import Any, Callable


class TaskHandler(ABC):
    @abstractmethod
    def execute(self, task, progress_callback: Callable[[int], None]) -> Any:
        """执行任务，通过 progress_callback 报告进度。返回结果。"""
        ...