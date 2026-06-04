from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass
class FileContent:
    """标准化输出，统一不同来源的文件读取结果。"""
    content: str                   # 提取的文本内容
    filename: str                  # 基本文件名（例如 report.pdf）
    file_type: str                 # 标准化文件类型（txt, pdf, docx, markdown, image）
    size: int                      # 文件大小（字节）
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_type: str = "local"     # 来源类型，用于审计/日志


class BaseFileSource(ABC):
    """文件源抽象基类。

    所有文件源（本地、S3、其他对象存储）需实现此接口。
    """

    @abstractmethod
    def read(self, path_or_uri: str) -> FileContent:
        """读取文件并返回结构化内容。"""
        ...

    @abstractmethod
    def validate_path(self, path_or_uri: str) -> bool:
        """验证路径/URI 是否可访问。"""
        ...

    def list_files(self, path_or_uri: str, recursive: bool = False) -> List[str]:
        """列出路径下所有受支持的文件路径列表。"""
        raise NotImplementedError
