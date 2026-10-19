"""数据库 Schema 分析结果的 SQLite 持久化（阶段②提取结果 / 阶段③标注产物）

连接配置的 CRUD 已归 source_registry/database/registry.py；
本模块只管分析产物的存取：Schema（表/字段/外键/推断关系）与已分析库记录。
"""
import json
import os
import uuid
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy.orm import Session

from models.database import (DB_STATUS_EXTRACTED, AnalyzedDatabase, DatabaseColumn,
                             DatabaseConnection, DatabaseForeignKey,
                             DatabaseTable, InferredRelationship)
from system.logger import logger


class SchemaRepository:
    """Schema 分析产物仓储（save/get/删除 + 已分析库记录）"""

    def save_schema(self, db: Session, connection_id: str, schema: Dict) -> bool:
        """保存Schema信息到数据库"""
        try:
            self.delete_schema(db, connection_id)

            # 统一键名大小写（不同数据库驱动返回的列名大小写不一致）
            tables = [{k.lower(): v for k, v in t.items()} for t in schema.get("tables", [])]
            columns = [{k.lower(): v for k, v in c.items()} for c in schema.get("columns", [])]
            foreign_keys = [{k.lower(): v for k, v in fk.items()} for fk in schema.get("foreign_keys", [])]

            for table_data in tables:
                table = DatabaseTable(
                    id=f"{connection_id}_{table_data['table_name']}",
                    connection_id=connection_id,
                    table_name=table_data["table_name"],
                    table_type=table_data.get("table_type"),
                    engine=table_data.get("engine"),
                    row_count=table_data.get("table_rows"),
                    business_description=table_data.get("business_description"),
                    entity_type=table_data.get("entity_type"),
                    table_role=table_data.get("table_role", "entity"),
                    created_at=datetime.now()
                )
                db.add(table)

            for column_data in columns:
                column = DatabaseColumn(
                    id=f"{connection_id}_{column_data['table_name']}_{column_data['column_name']}",
                    connection_id=connection_id,
                    table_name=column_data["table_name"],
                    column_name=column_data["column_name"],
                    data_type=column_data["data_type"],
                    is_nullable=column_data.get("is_nullable"),
                    column_type=column_data.get("column_type"),
                    column_key=column_data.get("column_key"),
                    extra=column_data.get("extra"),
                    character_maximum_length=column_data.get("character_maximum_length"),
                    numeric_precision=column_data.get("numeric_precision"),
                    numeric_scale=column_data.get("numeric_scale"),
                    column_default=column_data.get("column_default"),
                    business_description=column_data.get("business_description"),
                    semantic_type=column_data.get("semantic_type"),
                    created_at=datetime.now()
                )
                db.add(column)

            for fk_data in foreign_keys:
                table_name = fk_data.get('table_name')
                column_name = fk_data.get('column_name')
                ref_table_name = fk_data.get('referenced_table_name')
                ref_column_name = fk_data.get('referenced_column_name')
                constraint_name = fk_data.get('constraint_name')

                if table_name and column_name and ref_table_name and ref_column_name:
                    fk = DatabaseForeignKey(
                        id=f"{connection_id}_{constraint_name or (table_name + '_' + column_name)}",
                        connection_id=connection_id,
                        table_name=table_name,
                        column_name=column_name,
                        referenced_table_name=ref_table_name,
                        referenced_column_name=ref_column_name,
                        constraint_name=constraint_name,
                        created_at=datetime.now()
                    )
                    db.add(fk)
                else:
                    logger.warning(f"跳过不完整的外键数据: {fk_data}")

            inferred_relationships = schema.get("inferred_relationships", [])
            for rel in inferred_relationships:
                rel_id = f"{connection_id}_{rel.get('source_table')}_{rel.get('target_table')}_{rel.get('relationship_type', 'unknown')}"
                inferred = InferredRelationship(
                    id=rel_id,
                    connection_id=connection_id,
                    source_table=rel.get("source_table", ""),
                    source_column=rel.get("source_column"),
                    target_table=rel.get("target_table", ""),
                    target_column=rel.get("target_column"),
                    relationship_type=rel.get("relationship_type"),
                    description=rel.get("description"),
                    created_at=datetime.now()
                )
                db.add(inferred)

            db.commit()
            logger.info(f"Schema信息已保存: {connection_id}, 表数量: {len(tables)}, 推断关系: {len(inferred_relationships)}")
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"保存Schema信息失败: {e}")
            return False

    def delete_schema(self, db: Session, connection_id: str) -> bool:
        """删除指定连接的Schema信息"""
        try:
            db.query(InferredRelationship).filter(InferredRelationship.connection_id == connection_id).delete()
            db.query(DatabaseForeignKey).filter(DatabaseForeignKey.connection_id == connection_id).delete()
            db.query(DatabaseColumn).filter(DatabaseColumn.connection_id == connection_id).delete()
            db.query(DatabaseTable).filter(DatabaseTable.connection_id == connection_id).delete()
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"删除Schema信息失败: {e}")
            return False

    def get_schema(self, db: Session, connection_id: str) -> Dict:
        """获取Schema信息"""
        try:
            tables = db.query(DatabaseTable).filter(DatabaseTable.connection_id == connection_id).all()
            columns = db.query(DatabaseColumn).filter(DatabaseColumn.connection_id == connection_id).all()
            foreign_keys = db.query(DatabaseForeignKey).filter(DatabaseForeignKey.connection_id == connection_id).all()
            inferred = db.query(InferredRelationship).filter(InferredRelationship.connection_id == connection_id).all()

            return {
                "tables": [t.to_dict() for t in tables],
                "columns": [c.to_dict() for c in columns],
                "foreign_keys": [fk.to_dict() for fk in foreign_keys],
                "inferred_relationships": [r.to_dict() for r in inferred]
            }
        except Exception as e:
            logger.error(f"获取Schema信息失败: {e}")
            return {"tables": [], "columns": [], "foreign_keys": [], "inferred_relationships": []}

    def save_analyzed_database(self, db: Session, connection_id: str, database_name: str) -> AnalyzedDatabase:
        """保存或更新已分析的数据库记录（幂等）"""
        try:
            existing = db.query(AnalyzedDatabase).filter(
                AnalyzedDatabase.connection_id == connection_id,
                AnalyzedDatabase.database_name == database_name
            ).first()

            if existing:
                existing.status = DB_STATUS_EXTRACTED
                existing.updated_at = datetime.now()
                db.commit()
                db.refresh(existing)
                logger.info(f"已分析的数据库记录已更新: {connection_id}/{database_name}")
                return existing

            record = AnalyzedDatabase(
                id=str(uuid.uuid4()),
                connection_id=connection_id,
                database_name=database_name,
                status=DB_STATUS_EXTRACTED,
                created_at=datetime.now()
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            logger.info(f"已分析的数据库记录已保存: {connection_id}/{database_name}")
            return record
        except Exception as e:
            db.rollback()
            logger.error(f"保存已分析的数据库记录失败: {e}")
            raise

    def get_analyzed_databases(self, db: Session, connection_id: str) -> list:
        """获取连接的所有已分析数据库记录"""
        try:
            return db.query(AnalyzedDatabase).filter(
                AnalyzedDatabase.connection_id == connection_id
            ).all()
        except Exception as e:
            logger.error(f"获取已分析的数据库记录失败: {e}")
            return []

    def save_analyzed_tables(self, db: Session, connection_id: str,
                             database_name: Optional[str], tables: list) -> None:
        """为每个表创建 AnalyzedTable 记录（幂等，已存在跳过）"""
        for tbl in tables:
            table_uri = f"DBS://{connection_id}/{database_name or ''}/{tbl['table_name']}"
            existing = db.query(AnalyzedTable).filter(
                AnalyzedTable.connection_id == connection_id,
                AnalyzedTable.table_name == tbl["table_name"],
            ).first()
            if existing:
                continue
            db.add(AnalyzedTable(
                id=str(uuid.uuid4()),
                connection_id=connection_id,
                database_name=database_name or "",
                table_name=tbl["table_name"],
                uri=table_uri,
            ))


db_service = SchemaRepository()
