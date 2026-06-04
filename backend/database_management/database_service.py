import uuid
from sqlalchemy.orm import Session
from models.database import DatabaseConnection, DatabaseTable, DatabaseColumn, DatabaseForeignKey, InferredRelationship, AnalyzedDatabase
from database_management.database_manager import DB_STATUS_EXTRACTED
from typing import Dict, List, Optional
from system.logger import logger
from datetime import datetime

class DatabaseService:
    """数据库连接配置和Schema信息的持久化服务"""
    
    def create_connection(self, db: Session, config: Dict) -> DatabaseConnection:
        """创建数据库连接配置"""
        try:
            connection = DatabaseConnection(
                id=config["id"],
                name=config["name"],
                type=config["type"],
                host=config.get("host"),
                port=config.get("port"),
                database=config.get("database"),
                username=config.get("username"),
                password=config.get("password"),
                service_name=config.get("service_name"),
                description=config.get("description"),
                created_at=datetime.now()
            )
            db.add(connection)
            db.commit()
            db.refresh(connection)
            logger.info(f"数据库连接配置已保存: {connection.id}")
            return connection
        except Exception as e:
            db.rollback()
            logger.error(f"创建数据库连接配置失败: {e}")
            raise
    
    def get_connection(self, db: Session, connection_id: str) -> Optional[DatabaseConnection]:
        """获取连接配置"""
        try:
            return db.query(DatabaseConnection).filter(DatabaseConnection.id == connection_id).first()
        except Exception as e:
            logger.error(f"获取数据库连接配置失败: {e}")
            return None
    
    def get_connection_by_name(self, db: Session, name: str) -> Optional[DatabaseConnection]:
        """根据名称获取连接配置"""
        try:
            return db.query(DatabaseConnection).filter(
                DatabaseConnection.name == name,
                DatabaseConnection.is_deleted == False
            ).first()
        except Exception as e:
            logger.error(f"根据名称获取数据库连接配置失败: {e}")
            return None
    
    def get_all_connections(self, db: Session, include_deleted: bool = False) -> List[DatabaseConnection]:
        """获取所有连接配置"""
        try:
            query = db.query(DatabaseConnection)
            if not include_deleted:
                query = query.filter(DatabaseConnection.is_deleted == False)
            return query.all()
        except Exception as e:
            logger.error(f"获取所有数据库连接配置失败: {e}")
            return []
    
    def update_connection(self, db: Session, connection_id: str, config: Dict) -> bool:
        """更新连接配置"""
        try:
            connection = db.query(DatabaseConnection).filter(DatabaseConnection.id == connection_id).first()
            if not connection:
                return False
            
            if "name" in config:
                connection.name = config["name"]
            if "type" in config:
                connection.type = config["type"]
            if "host" in config:
                connection.host = config["host"]
            if "port" in config:
                connection.port = config["port"]
            if "database" in config:
                connection.database = config["database"]
            if "username" in config:
                connection.username = config["username"]
            if "password" in config:
                connection.password = config["password"]
            if "service_name" in config:
                connection.service_name = config["service_name"]
            if "description" in config:
                connection.description = config["description"]
            
            connection.updated_at = datetime.now()
            db.commit()
            logger.info(f"数据库连接配置已更新: {connection_id}")
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"更新数据库连接配置失败: {e}")
            return False
    
    def delete_connection(self, db: Session, connection_id: str) -> bool:
        """删除连接配置及相关Schema信息"""
        try:
            connection = db.query(DatabaseConnection).filter(DatabaseConnection.id == connection_id).first()
            if not connection:
                return False
            
            db.query(InferredRelationship).filter(InferredRelationship.connection_id == connection_id).delete()
            db.query(DatabaseForeignKey).filter(DatabaseForeignKey.connection_id == connection_id).delete()
            db.query(DatabaseColumn).filter(DatabaseColumn.connection_id == connection_id).delete()
            db.query(DatabaseTable).filter(DatabaseTable.connection_id == connection_id).delete()
            db.query(AnalyzedDatabase).filter(AnalyzedDatabase.connection_id == connection_id).delete()
            db.delete(connection)
            db.commit()
            logger.info(f"数据库连接配置已删除: {connection_id}")
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"删除数据库连接配置失败: {e}")
            return False
    
    def save_schema(self, db: Session, connection_id: str, schema: Dict) -> bool:
        """保存Schema信息到数据库"""
        try:
            self.delete_schema(db, connection_id)
            
            tables = schema.get("tables", [])
            columns = schema.get("columns", [])
            foreign_keys = schema.get("foreign_keys", [])
            
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
                # 支持大小写不同的键名
                table_name = fk_data.get('table_name') or fk_data.get('TABLE_NAME')
                column_name = fk_data.get('column_name') or fk_data.get('COLUMN_NAME')
                ref_table_name = fk_data.get('referenced_table_name') or fk_data.get('REFERENCED_TABLE_NAME')
                ref_column_name = fk_data.get('referenced_column_name') or fk_data.get('REFERENCED_COLUMN_NAME')
                constraint_name = fk_data.get('constraint_name') or fk_data.get('CONSTRAINT_NAME')
                
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