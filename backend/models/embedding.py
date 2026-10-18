from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func
from config.database import Base


class EmbeddingCache(Base):
    """文本向量缓存 — 避免重复调用 embedding 模型"""
    __tablename__ = "embedding_cache"

    text_hash = Column(String(32), primary_key=True)   # MD5(model_name + "\n" + text)
    model_name = Column(String(100), nullable=False)
    vector = Column(Text, nullable=False)              # JSON 数组字符串
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
