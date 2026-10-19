"""文档源注册 —— 存在性与可达性管理

职责：文档源的注册/列表/软删/恢复/目录浏览/路径解析。
不涉及内容提取与摘要；删除前的「是否有产出数据」判定通过回调注入，
避免组件间反向依赖（组件自治：本模块不 import 下游组件）。
"""
import os
from datetime import datetime
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from models.source import DocumentSource
from system.logger import logger
from utils.path_guard import safe_join


class DocumentSourceRegistry:
    """文档源注册表（数据访问层，路由只做 HTTP 映射）"""

    def __init__(self):
        # has_output_data(source_id) → bool：删除前判定该源是否已有产出数据
        self._has_output_data: Optional[Callable[[str], bool]] = None

    def bind_output_check(self, has_output_data: Callable[[str], bool]) -> None:
        """由产出侧（摘要落盘组件）在启动时注入判定函数"""
        self._has_output_data = has_output_data

    def _has_data(self, source_id: str) -> bool:
        if self._has_output_data is None:
            return False
        try:
            return bool(self._has_output_data(source_id))
        except Exception as e:
            logger.warning(f"[source_registry] 产出数据判定失败 source={source_id}: {e}")
            return True  # 判定失败按有数据处理，走软删除更安全

    # ── 查询 ──

    def get(self, db: Session, source_id: str) -> Optional[DocumentSource]:
        return db.query(DocumentSource).filter_by(id=source_id).first()

    def require(self, db: Session, source_id: str) -> DocumentSource:
        source = self.get(db, source_id)
        if not source:
            raise ValueError(f"文档源不存在: {source_id}")
        return source

    def require_alive(self, db: Session, source_id: str) -> DocumentSource:
        source = self.require(db, source_id)
        if source.is_deleted:
            raise ValueError(f"文档源已删除: {source_id}")
        return source

    def list(self, db: Session, include_deleted: bool = False) -> List[DocumentSource]:
        query = db.query(DocumentSource)
        if not include_deleted:
            query = query.filter(DocumentSource.is_deleted == False)
        return query.order_by(DocumentSource.created_at.desc()).all()

    # ── 注册与生命周期 ──

    def create(self, db: Session, name: str, path: str, source_type: str = "local") -> DocumentSource:
        """注册文档源（本地路径需已存在，S3 需以 s3:// 开头）"""
        if not name or not name.strip() or not path or not path.strip():
            raise ValueError("name 和 path 不能为空")
        name, path = name.strip(), path.strip()
        source_type = (source_type or "local").strip()

        if source_type == "local":
            if not os.path.exists(path):
                raise ValueError(f"路径不存在: {path}")
        elif source_type == "s3":
            if not path.startswith("s3://"):
                raise ValueError("S3路径必须以 s3:// 开头")
        else:
            raise ValueError("不支持的source_type，仅支持 local 或 s3")

        source = DocumentSource(name=name, path=path, source_type=source_type)
        db.add(source)
        db.commit()
        db.refresh(source)
        logger.info(f"[source_registry] 文档源已注册: id={source.id}, name={name}, path={path}")
        return source

    def delete(self, db: Session, source_id: str) -> bool:
        """删除文档源：无产出数据硬删，有产出数据软删"""
        source = self.get(db, source_id)
        if not source or source.is_deleted:
            raise ValueError(f"文档源不存在: {source_id}")

        if not self._has_data(source_id):
            db.delete(source)
            db.commit()
            logger.info(f"[source_registry] 文档源硬删除（无产出数据）: id={source_id}")
            return True

        source.is_deleted = True
        source.deleted_at = datetime.now()
        db.commit()
        logger.info(f"[source_registry] 文档源软删除: id={source_id}")
        return False

    def restore(self, db: Session, source_id: str) -> None:
        source = db.query(DocumentSource).filter(
            DocumentSource.id == source_id,
            DocumentSource.is_deleted == True,
        ).first()
        if not source:
            raise ValueError(f"已删除的文档源不存在: {source_id}")
        source.is_deleted = False
        source.deleted_at = None
        db.commit()
        logger.info(f"[source_registry] 文档源已恢复: id={source_id}")

    # ── 路径 ──

    def root_path(self, db: Session, source_id: str, *, quiet: bool = False) -> str:
        """文档源的本地根路径；源不存在/已删除/非本地时返回空串（quiet）或抛错"""
        try:
            source = self.require_alive(db, source_id)
        except ValueError:
            if quiet:
                return ""
            raise
        if source.source_type != "local":
            if quiet:
                return ""
            raise ValueError(f"仅本地文档源支持该操作: {source_id}")
        return source.path

    def resolve_file(self, base_path: str, file_path: str) -> str:
        """源内相对路径 → 绝对路径，越界直接拒绝"""
        return safe_join(base_path, file_path)


document_source_registry = DocumentSourceRegistry()
