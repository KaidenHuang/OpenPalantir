from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.sql import func
import uuid
from config.database import Base


class DocumentSource(Base):
    __tablename__ = "document_sources"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    path = Column(String, nullable=False)
    source_type = Column(String, nullable=False, default="local")  # "local" or "s3"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
