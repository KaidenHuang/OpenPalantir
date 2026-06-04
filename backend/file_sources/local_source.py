import os
from typing import List

from file_sources.base import BaseFileSource, FileContent
from document_processing.document_processor import document_processor
from system.logger import logger

# DocumentProcessor 支持的扩展名
SUPPORTED_EXTENSIONS = {'.txt', '.pdf', '.docx', '.md', '.jpg', '.jpeg', '.png', '.bmp'}


class LocalFileSource(BaseFileSource):
    """本地文件系统源，包装 DocumentProcessor 读取本地文件。"""

    def __init__(self, processor=None):
        self.processor = processor or document_processor

    def read(self, path: str) -> FileContent:
        """读取本地文件，通过 DocumentProcessor 解析后返回结构化内容。"""
        if not self.validate_path(path):
            raise FileNotFoundError(f"文件不存在或无法访问: {path}")

        logger.info(f"LocalFileSource 读取文件: {path}")
        result = self.processor.process_document(path)
        stat = os.stat(path)

        return FileContent(
            content=result["content"],
            filename=os.path.basename(path),
            file_type=result["metadata"].get("file_type", "txt"),
            size=stat.st_size,
            metadata=result["metadata"],
            source_type="local",
        )

    def validate_path(self, path: str) -> bool:
        """验证本地路径是否存在且可访问。"""
        return os.path.exists(path) and os.path.isfile(path)

    def list_files(self, path_or_uri: str, recursive: bool = False) -> List[str]:
        """扫描目录，返回所有受支持文件的完整路径列表。"""
        if not os.path.isdir(path_or_uri):
            raise NotADirectoryError(f"路径不是目录: {path_or_uri}")

        logger.info(f"LocalFileSource 扫描目录: {path_or_uri}, recursive={recursive}")
        matched = []
        if recursive:
            for root, _, files in os.walk(path_or_uri):
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        matched.append(os.path.join(root, fname))
        else:
            for entry in os.scandir(path_or_uri):
                if not entry.is_file():
                    continue
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    matched.append(entry.path)

        matched.sort()
        logger.info(f"LocalFileSource 扫描完成，找到 {len(matched)} 个文件")
        return matched
