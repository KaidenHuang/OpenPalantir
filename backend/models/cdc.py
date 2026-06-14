from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Text, UniqueConstraint
from config.database import Base
from sqlalchemy.sql import func
from datetime import datetime
import uuid
from typing import Dict


class CdcSyncState(Base):
    __tablename__ = "cdc_sync_states"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id = Column(String(36), nullable=False, index=True)
    database_name = Column(String(255), nullable=False)

    # 全量→增量衔接位点
    binlog_file = Column(String(255), nullable=True)       # MySQL: binlog 文件名
    binlog_position = Column(BigInteger, nullable=True)     # MySQL: binlog 位点
    wal_lsn = Column(String(100), nullable=True)            # PostgreSQL: WAL LSN

    # 运行状态: idle / running / stopped / paused / error
    status = Column(String(20), default="idle")
    last_event_ts = Column(BigInteger, nullable=True)       # Debezium 事件时间戳 (ms)
    events_processed = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)

    # Redis Streams 消费位点
    last_message_id = Column(String(100), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('connection_id', 'database_name', name='uq_cdc_conn_db'),
    )

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "database_name": self.database_name,
            "binlog_file": self.binlog_file,
            "binlog_position": self.binlog_position,
            "wal_lsn": self.wal_lsn,
            "status": self.status,
            "last_event_ts": self.last_event_ts,
            "events_processed": self.events_processed,
            "last_error": self.last_error,
            "last_message_id": self.last_message_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
