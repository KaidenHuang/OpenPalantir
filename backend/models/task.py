from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from config.database import Base

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, index=True)
    type = Column(String)
    status = Column(String)
    progress = Column(Integer, nullable=False, server_default="0")  # 0-100，REST 与 WS 双通道同源
    create_time = Column(DateTime(timezone=True), server_default=func.now())
    complete_time = Column(DateTime(timezone=True), nullable=True)
    file_id = Column(String, nullable=True)
    result = Column(String, nullable=True)
    payload = Column(String, nullable=True)  # JSON 序列化的创建 payload，重启重跑的恢复源
