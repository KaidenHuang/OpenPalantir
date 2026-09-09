from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean, UniqueConstraint
from config.database import Base
from datetime import datetime
from typing import Dict
import uuid

class DatabaseConnection(Base):
    __tablename__ = "database_connections"
    
    id = Column(String(36), primary_key=True)
    name = Column(String(100), nullable=False)
    type = Column(String(50), nullable=False)
    host = Column(String(255))
    port = Column(Integer)
    database = Column(String(100))
    username = Column(String(100))
    password = Column(String(255))
    service_name = Column(String(100))
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, onupdate=datetime.now)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "username": self.username,
            "service_name": self.service_name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None
        }

class DatabaseTable(Base):
    __tablename__ = "database_tables"
    
    id = Column(String(255), primary_key=True)
    connection_id = Column(String(36), nullable=False)
    table_name = Column(String(255), nullable=False)
    table_type = Column(String(50))
    engine = Column(String(50))
    row_count = Column(Integer)
    business_description = Column(Text)
    entity_type = Column(String(100))
    table_role = Column(String(50), default="entity")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, onupdate=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "table_name": self.table_name,
            "table_type": self.table_type,
            "engine": self.engine,
            "row_count": self.row_count,
            "business_description": self.business_description,
            "entity_type": self.entity_type,
            "table_role": self.table_role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class DatabaseColumn(Base):
    __tablename__ = "database_columns"
    
    id = Column(String(500), primary_key=True)
    connection_id = Column(String(36), nullable=False)
    table_name = Column(String(255), nullable=False)
    column_name = Column(String(255), nullable=False)
    data_type = Column(String(100))
    is_nullable = Column(String(10))
    column_type = Column(String(255))
    column_key = Column(String(50))
    extra = Column(String(255))
    character_maximum_length = Column(Integer)
    numeric_precision = Column(Integer)
    numeric_scale = Column(Integer)
    column_default = Column(String(255))
    business_description = Column(Text)
    semantic_type = Column(String(100))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, onupdate=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "data_type": self.data_type,
            "is_nullable": self.is_nullable,
            "column_type": self.column_type,
            "column_key": self.column_key,
            "extra": self.extra,
            "character_maximum_length": self.character_maximum_length,
            "numeric_precision": self.numeric_precision,
            "numeric_scale": self.numeric_scale,
            "column_default": self.column_default,
            "business_description": self.business_description,
            "semantic_type": self.semantic_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class DatabaseForeignKey(Base):
    __tablename__ = "database_foreign_keys"
    
    id = Column(String(500), primary_key=True)
    connection_id = Column(String(36), nullable=False)
    table_name = Column(String(255), nullable=False)
    column_name = Column(String(255), nullable=False)
    referenced_table_name = Column(String(255), nullable=False)
    referenced_column_name = Column(String(255), nullable=False)
    constraint_name = Column(String(255))
    created_at = Column(DateTime, default=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "referenced_table_name": self.referenced_table_name,
            "referenced_column_name": self.referenced_column_name,
            "constraint_name": self.constraint_name,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class InferredRelationship(Base):
    __tablename__ = "inferred_relationships"

    id = Column(String(500), primary_key=True)
    connection_id = Column(String(36), nullable=False, index=True)
    source_table = Column(String(255), nullable=False)
    source_column = Column(String(255))
    target_table = Column(String(255), nullable=False)
    target_column = Column(String(255))
    relationship_type = Column(String(50))
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "source_table": self.source_table,
            "source_column": self.source_column,
            "target_table": self.target_table,
            "target_column": self.target_column,
            "relationship_type": self.relationship_type,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class AnalyzedDatabase(Base):
    __tablename__ = "analyzed_databases"
    __table_args__ = (
        UniqueConstraint('connection_id', 'database_name', name='uq_connection_database'),
    )

    id = Column(String(36), primary_key=True)
    connection_id = Column(String(36), nullable=False, index=True)
    database_name = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="extracted")  # extracted, deleted
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, onupdate=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "database_name": self.database_name,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class AnalyzedTable(Base):
    __tablename__ = "analyzed_tables"

    id = Column(String(36), primary_key=True)
    connection_id = Column(String(36), nullable=False, index=True)
    database_name = Column(String(255), nullable=False)
    table_name = Column(String(255), nullable=False)
    uri = Column(String(500), nullable=False)
    entity_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


# ── 实体类型元数据 ──

class EntityType(Base):
    """实体类型元数据（动态管理，替代前端硬编码）"""
    __tablename__ = "entity_types"

    type_key = Column(String(50), primary_key=True)
    display_name = Column(String(100), nullable=False)
    color = Column(String(20), nullable=False, default="#95A5A6")
    sort_order = Column(Integer, default=0)
    is_builtin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "type_key": self.type_key,
            "display_name": self.display_name,
            "color": self.color,
            "sort_order": self.sort_order,
            "is_builtin": self.is_builtin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# 默认实体类型（首次启动时写入）
_DEFAULT_ENTITY_TYPES = [
    {"type_key": "person",       "display_name": "人物",   "color": "#3498db", "sort_order": 1},
    {"type_key": "organization", "display_name": "组织",   "color": "#e74c3c", "sort_order": 2},
    {"type_key": "location",     "display_name": "地点",   "color": "#27ae60", "sort_order": 3},
    {"type_key": "event",        "display_name": "事件",   "color": "#f39c12", "sort_order": 4},
    {"type_key": "concept",      "display_name": "概念",   "color": "#9b59b6", "sort_order": 5},
    {"type_key": "other",        "display_name": "其他",   "color": "#95A5A6", "sort_order": 99},
]


def init_entity_types():
    """初始化默认实体类型（幂等：已有则跳过）"""
    from config.database import SessionLocal
    db = SessionLocal()
    try:
        existing = {row.type_key for row in db.query(EntityType).all()}
        for t in _DEFAULT_ENTITY_TYPES:
            if t["type_key"] not in existing:
                db.add(EntityType(**t, is_builtin=True))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()