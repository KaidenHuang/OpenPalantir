from sqlalchemy import Column, String, Float, DateTime, Text
from sqlalchemy.sql import func
from config.database import Base


class LongTermMemory(Base):
    """长期记忆 ORM —— 稳定的用户偏好与重要决策（无 TTL，由提炼/覆写维护）"""
    __tablename__ = "long_term_memories"

    id = Column(String, primary_key=True)               # UUID
    category = Column(String, nullable=False)           # preference / decision
    content = Column(String, nullable=False)            # 提炼的一句话信息
    created_at = Column(DateTime, default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class ShortTermMemory(Base):
    """短期记忆 ORM 模型 — 历史对话的提炼信息，7 天 TTL"""
    __tablename__ = "short_term_memories"

    id = Column(String, primary_key=True)              # UUID
    content = Column(String, nullable=False)            # 提炼的一句话信息
    category = Column(String, default="fact")           # fact/decision/entity/topic
    importance = Column(Float, default=0.5)             # 0.0-1.0
    session_id = Column(String, default="")
    domain = Column(String, default="general")
    created_at = Column(DateTime, default=func.now())
    expires_at = Column(DateTime, nullable=False)       # created_at + 7 days

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "importance": self.importance,
            "session_id": self.session_id,
            "domain": self.domain,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "expires_at": self.expires_at.isoformat() if self.expires_at else "",
        }