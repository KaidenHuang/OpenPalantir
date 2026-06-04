import os
import uuid
from typing import Dict, List, Any, Optional
from urllib.parse import quote
from sqlalchemy import create_engine, text, select, table, column
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import SQLAlchemyError
from config.database import SessionLocal
from system.logger import logger

class DatabaseDialect:
    """数据库方言抽象基类（数据库级别批量操作）"""
    
    def extract_full_schema(self, connection) -> Dict:
        """
        批量提取数据库完整Schema信息（以数据库为单位）
        :param connection: 数据库连接对象
        :return: 包含表名列表、字段列表、主外键约束的完整Schema字典
        {
            "tables": [...],      # 表名列表
            "columns": [...],     # 所有表的字段信息
            "foreign_keys": [...] # 所有外键约束
        }
        """
        pass

    def get_primary_key_columns(self, connection, table_name: str) -> List[str]:
        """使用SQLAlchemy inspect检测主键列，跨方言兼容"""
        try:
            inspector = sa_inspect(connection)
            pk_constraint = inspector.get_pk_constraint(table_name)
            return pk_constraint.get("constrained_columns", [])
        except SQLAlchemyError as e:
            logger.warning(f"检测表 {table_name} 的主键时出错: {e}")
            return []

    def fetch_table_rows_batched(self, connection, table_name: str, columns: List[str],
                                  batch_size: int = 5000, max_rows: int = 0):
        """生成器：分批获取表行数据（基于 LIMIT/OFFSET），每批 yield List[Dict]
        :param max_rows: 最大返回行数（0=不限制）
        大表请使用 fetch_table_rows_keyset() 以避免 OFFSET 性能退化。
        """
        try:
            t = table(table_name, *[column(c) for c in columns])
            offset = 0
            total_yielded = 0
            while True:
                if max_rows > 0 and total_yielded >= max_rows:
                    break
                limit = min(batch_size, max_rows - total_yielded) if max_rows > 0 else batch_size
                stmt = select(t).limit(limit).offset(offset)
                result = connection.execute(stmt)
                db_columns = result.keys()
                rows = result.fetchall()
                if not rows:
                    break
                batch = [dict(zip(db_columns, row)) for row in rows]
                yield batch
                total_yielded += len(batch)
                offset += len(batch)
        except SQLAlchemyError as e:
            logger.error(f"分批查询表 {table_name} 的行数据时出错: {e}")
            return

    def fetch_table_rows_keyset(self, connection, table_name: str, columns: List[str],
                                 pk_columns: List[str], batch_size: int = 5000, max_rows: int = 0):
        """生成器：基于主键游标分页，每页仅 O(1)，避免大偏移量性能退化
        使用 WHERE pk > ? ORDER BY pk LIMIT n，首次查询无 WHERE。
        :param pk_columns: 主键列名列表（单个或多个）
        :param max_rows: 最大返回行数（0=不限制）
        """
        if not pk_columns:
            logger.warning(f"表 {table_name} 无主键，回退 LIMIT/OFFSET 分页")
            yield from self.fetch_table_rows_batched(connection, table_name, columns, batch_size, max_rows)
            return

        try:
            from sqlalchemy import literal_column
            t = table(table_name, *[column(c) for c in columns])
            pk_cols_sa = [literal_column(c) for c in pk_columns]
            total_yielded = 0
            last_values = None  # List of pk values from the last row of previous batch

            while True:
                if max_rows > 0 and total_yielded >= max_rows:
                    break
                limit = min(batch_size, max_rows - total_yielded) if max_rows > 0 else batch_size

                stmt = select(t).limit(limit).order_by(*pk_cols_sa)
                if last_values is not None:
                    if len(pk_columns) == 1:
                        stmt = stmt.where(literal_column(pk_columns[0]) > last_values[0])
                    else:
                        # Composite key: (pk1 > v1) OR (pk1 = v1 AND pk2 > v2) OR ...
                        from sqlalchemy import or_, and_
                        clauses = []
                        for i in range(len(pk_columns)):
                            eq_clauses = [literal_column(pk_columns[j]) == last_values[j] for j in range(i)]
                            gt_clause = literal_column(pk_columns[i]) > last_values[i]
                            if eq_clauses:
                                clauses.append(and_(*eq_clauses, gt_clause))
                            else:
                                clauses.append(gt_clause)
                        stmt = stmt.where(or_(*clauses))

                result = connection.execute(stmt)
                db_columns = list(result.keys())
                rows = result.fetchall()
                if not rows:
                    break

                batch = [dict(zip(db_columns, row)) for row in rows]
                yield batch
                total_yielded += len(batch)

                # 更新游标：取最后一条记录的各主键值
                last_row = rows[-1]
                col_index = {name: idx for idx, name in enumerate(db_columns)}
                last_values = [last_row[col_index[pk]] for pk in pk_columns]

        except Exception as e:
            logger.error(f"游标分页查询表 {table_name} 时出错: {e}，回退 LIMIT/OFFSET")
            yield from self.fetch_table_rows_batched(connection, table_name, columns, batch_size, max_rows)

class MySQLDialect(DatabaseDialect):
    """MySQL方言"""
    
    def extract_full_schema(self, connection) -> Dict:
        """批量提取MySQL数据库完整Schema"""
        result = {"tables": [], "columns": [], "foreign_keys": []}
        
        tables_query = """
            SELECT table_name, table_type, engine, table_rows
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'
        """

        columns_query = """
            SELECT table_name, column_name, data_type, is_nullable,
                   column_type, column_key, extra,
                   character_maximum_length, numeric_precision, numeric_scale,
                   column_default
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
        """

        fk_query = """
            SELECT TABLE_NAME, COLUMN_NAME,
                   REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME,
                   CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE table_schema = DATABASE()
              AND REFERENCED_TABLE_NAME IS NOT NULL
        """

        result["tables"] = self._execute_query(connection, tables_query)
        result["columns"] = self._execute_query(connection, columns_query)
        result["foreign_keys"] = self._execute_query(connection, fk_query)
        
        return result
    
    def _execute_query(self, connection, query) -> List[Dict]:
        """执行SQL查询并返回结果列表"""
        try:
            result = connection.execute(text(query))
            rows = result.fetchall()
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"MySQL查询执行失败: {e}")
            return []

class PostgreSQLDialect(DatabaseDialect):
    """PostgreSQL方言"""
    
    def extract_full_schema(self, connection) -> Dict:
        """批量提取PostgreSQL数据库完整Schema"""
        result = {"tables": [], "columns": [], "foreign_keys": []}
        
        tables_query = """
            SELECT table_name, table_type
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """
        
        columns_query = """
            SELECT table_name, column_name, data_type, is_nullable, 
                   character_maximum_length, numeric_precision, numeric_scale,
                   column_default
            FROM information_schema.columns 
            WHERE table_schema = 'public'
        """
        
        fk_query = """
            SELECT tc.table_name, kcu.column_name, 
                   ccu.table_name AS referenced_table_name, ccu.column_name AS referenced_column_name,
                   tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu 
                ON tc.table_schema = kcu.table_schema 
                AND tc.table_name = kcu.table_name 
                AND tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu 
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
        """
        
        result["tables"] = self._execute_query(connection, tables_query)
        result["columns"] = self._execute_query(connection, columns_query)
        result["foreign_keys"] = self._execute_query(connection, fk_query)
        
        return result
    
    def _execute_query(self, connection, query) -> List[Dict]:
        try:
            result = connection.execute(text(query))
            rows = result.fetchall()
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"PostgreSQL查询执行失败: {e}")
            return []

class SQLiteDialect(DatabaseDialect):
    """SQLite方言"""
    
    def extract_full_schema(self, connection) -> Dict:
        """批量提取SQLite数据库完整Schema"""
        result = {"tables": [], "columns": [], "foreign_keys": []}
        
        tables_query = """
            SELECT name AS table_name, 'table' AS table_type
            FROM sqlite_master 
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        """
        
        columns_query = """
            SELECT m.name AS table_name, 
                   p.name AS column_name, 
                   p.type AS data_type,
                   CASE WHEN p.notnull = 1 THEN 'NO' ELSE 'YES' END AS is_nullable,
                   p.dflt_value AS column_default
            FROM sqlite_master m
            JOIN pragma_table_info(m.name) p
            WHERE m.type = 'table' AND m.name NOT LIKE 'sqlite_%'
        """
        
        fk_query = """
            SELECT m.name AS table_name, 
                   p.name AS column_name,
                   p.fk_table AS referenced_table_name,
                   p.fk_column AS referenced_column_name
            FROM sqlite_master m
            JOIN pragma_foreign_key_list(m.name) p
            WHERE m.type = 'table' AND m.name NOT LIKE 'sqlite_%'
        """
        
        result["tables"] = self._execute_query(connection, tables_query)
        result["columns"] = self._execute_query(connection, columns_query)
        result["foreign_keys"] = self._execute_query(connection, fk_query)
        
        return result
    
    def _execute_query(self, connection, query) -> List[Dict]:
        try:
            result = connection.execute(text(query))
            rows = result.fetchall()
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"SQLite查询执行失败: {e}")
            return []

class OracleDialect(DatabaseDialect):
    """Oracle方言"""
    
    def extract_full_schema(self, connection) -> Dict:
        """批量提取Oracle数据库完整Schema"""
        result = {"tables": [], "columns": [], "foreign_keys": []}
        
        tables_query = """
            SELECT table_name, tablespace_name 
            FROM all_tables 
            WHERE owner = SYS_CONTEXT('USERENV', 'CURRENT_USER')
        """
        
        columns_query = """
            SELECT table_name, column_name, data_type, nullable, 
                   data_length, data_precision, data_scale,
                   data_default
            FROM all_tab_columns 
            WHERE owner = SYS_CONTEXT('USERENV', 'CURRENT_USER')
        """
        
        fk_query = """
            SELECT a.table_name, a.column_name, 
                   c.table_name AS referenced_table_name, c.column_name AS referenced_column_name,
                   b.constraint_name
            FROM all_cons_columns a
            JOIN all_constraints b ON a.owner = b.owner AND a.constraint_name = b.constraint_name
            JOIN all_cons_columns c ON b.r_owner = c.owner AND b.r_constraint_name = c.constraint_name
            WHERE a.owner = SYS_CONTEXT('USERENV', 'CURRENT_USER')
              AND b.constraint_type = 'R'
        """
        
        result["tables"] = self._execute_query(connection, tables_query)
        result["columns"] = self._execute_query(connection, columns_query)
        result["foreign_keys"] = self._execute_query(connection, fk_query)
        
        return result
    
    def _execute_query(self, connection, query) -> List[Dict]:
        try:
            result = connection.execute(text(query))
            rows = result.fetchall()
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Oracle查询执行失败: {e}")
            return []

class SQLServerDialect(DatabaseDialect):
    """SQL Server方言"""
    
    def extract_full_schema(self, connection) -> Dict:
        """批量提取SQL Server数据库完整Schema"""
        result = {"tables": [], "columns": [], "foreign_keys": []}
        
        tables_query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_type = 'BASE TABLE'
        """
        
        columns_query = """
            SELECT table_name, column_name, data_type, is_nullable, 
                   character_maximum_length, numeric_precision, numeric_scale,
                   column_default
            FROM information_schema.columns 
        """
        
        fk_query = """
            SELECT kcu.table_name, kcu.column_name, 
                   ccu.table_name AS referenced_table_name, ccu.column_name AS referenced_column_name,
                   tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu 
                ON tc.table_schema = kcu.table_schema 
                AND tc.table_name = kcu.table_name 
                AND tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu 
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
        """
        
        result["tables"] = self._execute_query(connection, tables_query)
        result["columns"] = self._execute_query(connection, columns_query)
        result["foreign_keys"] = self._execute_query(connection, fk_query)
        
        return result
    
    def _execute_query(self, connection, query) -> List[Dict]:
        try:
            result = connection.execute(text(query))
            rows = result.fetchall()
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"SQL Server查询执行失败: {e}")
            return []

DIALECT_MAP = {
    "mysql": MySQLDialect,
    "postgresql": PostgreSQLDialect,
    "sqlite": SQLiteDialect,
    "oracle": OracleDialect,
    "mssql": SQLServerDialect,
}

DB_STATUS_EXTRACTED = "extracted"
DB_STATUS_DELETED = "deleted"

class DatabaseManager:
    """数据库连接和Schema管理（数据库级别批量操作）"""
    
    def __init__(self):
        self.connections: Dict[str, Dict] = {}
    
    def create_connection(self, config: Dict) -> str:
        """创建数据库连接配置"""
        try:
            connection_id = str(uuid.uuid4())
            
            db = SessionLocal()
            try:
                from database_management.database_service import DatabaseService
                db_service = DatabaseService()
                
                # 检查名称是否重复
                existing = db_service.get_connection_by_name(db, config["name"])
                if existing:
                    raise ValueError(f"连接名称已存在: {config['name']}")
                
                db_service.create_connection(db, {
                    "id": connection_id,
                    **config
                })
            finally:
                db.close()
            
            logger.info(f"数据库连接配置创建成功: {connection_id}")
            return connection_id
        except Exception as e:
            logger.error(f"创建数据库连接配置失败: {e}")
            raise
    
    def get_connection(self, connection_id: str) -> Optional[Dict]:
        """获取连接配置"""
        try:
            db = SessionLocal()
            try:
                from database_management.database_service import DatabaseService
                db_service = DatabaseService()
                return db_service.get_connection(db, connection_id)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"获取数据库连接配置失败: {e}")
            return None
    
    def get_all_connections(self, include_deleted: bool = False) -> List[Dict]:
        """获取所有连接配置"""
        try:
            db = SessionLocal()
            try:
                from database_management.database_service import DatabaseService
                db_service = DatabaseService()
                return db_service.get_all_connections(db, include_deleted=include_deleted)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"获取所有数据库连接配置失败: {e}")
            return []
    
    def update_connection(self, connection_id: str, config: Dict) -> bool:
        """更新连接配置"""
        try:
            db = SessionLocal()
            try:
                from database_management.database_service import DatabaseService
                db_service = DatabaseService()
                return db_service.update_connection(db, connection_id, config)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"更新数据库连接配置失败: {e}")
            return False
    
    def delete_connection(self, connection_id: str) -> bool:
        """删除连接配置"""
        try:
            db = SessionLocal()
            try:
                from database_management.database_service import DatabaseService
                db_service = DatabaseService()
                return db_service.delete_connection(db, connection_id)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"删除数据库连接配置失败: {e}")
            return False
    
    def test_connection(self, connection_id: str) -> bool:
        """测试数据库连接"""
        try:
            connection = self.get_connection(connection_id)
            if not connection:
                return False

            engine = self._create_engine(connection)
            if engine:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                    conn.commit()
                logger.info(f"数据库连接测试成功: {connection_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"数据库连接测试失败: {e}")
            return False

    def test_connection_config(self, config: Dict) -> bool:
        """测试数据库连接配置（直接使用配置，不保存）"""
        try:
            # If no database specified, use bare engine (connect without specific DB)
            has_db = bool(config.get('database'))
            engine = self._create_engine(config) if has_db else self._create_bare_engine(config)
            if engine:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                    conn.commit()
                logger.info(f"数据库连接配置测试成功: {config.get('name', 'unknown')}")
                return True
            return False
        except Exception as e:
            logger.error(f"数据库连接配置测试失败: {e}")
            return False

    def extract_schema(self, connection_id: str, tables: List[str] = None, ignore_tables: List[str] = None, database_name: str = None) -> Dict:
        """
        批量提取数据库Schema信息（数据库级别）
        :param connection_id: 数据库连接ID
        :param tables: 可选，指定要提取的表名列表，不指定则提取所有表
        :param ignore_tables: 可选，指定要忽略的表名列表
        :param database_name: 可选，指定要提取的数据库名（覆盖连接配置中的数据库名）
        :return: 包含所有表结构、字段、主外键关联的Schema信息
        """
        try:
            connection = self.get_connection(connection_id)
            if not connection:
                raise ValueError(f"连接配置不存在: {connection_id}")

            if database_name:
                if isinstance(connection, dict):
                    connection = {**connection, "database": database_name}
                else:
                    connection.database = database_name

            engine = self._create_engine(connection)
            if not engine:
                raise ValueError("无法创建数据库引擎")
            
            if isinstance(connection, dict):
                dialect_type = connection.get("type", "").lower()
            else:
                dialect_type = connection.type.lower() if connection.type else ""
            if dialect_type not in DIALECT_MAP:
                raise ValueError(f"不支持的数据库类型: {dialect_type}")
            
            dialect = DIALECT_MAP[dialect_type]()
            
            with engine.connect() as conn:
                schema = dialect.extract_full_schema(conn)
            
            # 过滤表
            if tables:
                table_names = set(tables)
                schema["tables"] = [t for t in schema["tables"] if t.get("table_name") in table_names]
                schema["columns"] = [c for c in schema["columns"] if c.get("table_name") in table_names]
                schema["foreign_keys"] = [fk for fk in schema["foreign_keys"] 
                                         if fk.get("table_name") in table_names or fk.get("referenced_table_name") in table_names]
            
            if ignore_tables:
                ignore_names = set(ignore_tables)
                schema["tables"] = [t for t in schema["tables"] if t.get("table_name") not in ignore_names]
                schema["columns"] = [c for c in schema["columns"] if c.get("table_name") not in ignore_names]
                schema["foreign_keys"] = [fk for fk in schema["foreign_keys"] 
                                         if fk.get("table_name") not in ignore_names and fk.get("referenced_table_name") not in ignore_names]
            
            logger.info(f"Schema提取成功: {connection_id}, 表数量: {len(schema['tables'])}")
            return schema
        
        except Exception as e:
            logger.error(f"Schema提取失败: {e}")
            raise
    
    def list_databases(self, connection_id: str) -> List[str]:
        """列出数据库服务器上的所有数据库"""
        try:
            connection = self.get_connection(connection_id)
            if not connection:
                raise ValueError(f"连接配置不存在: {connection_id}")

            engine = self._create_bare_engine(connection)
            if not engine:
                raise ValueError("无法创建数据库引擎")

            if isinstance(connection, dict):
                db_type = connection.get("type", "").lower()
            else:
                db_type = connection.type.lower() if connection.type else ""

            with engine.connect() as conn:
                if db_type == "mysql":
                    result = conn.execute(text("SHOW DATABASES"))
                    rows = result.fetchall()
                    # Filter out system databases
                    system_dbs = {"information_schema", "mysql", "performance_schema", "sys"}
                    return [row[0] for row in rows if row[0].lower() not in system_dbs]
                elif db_type == "postgresql":
                    result = conn.execute(text("SELECT datname FROM pg_database WHERE datistemplate = false"))
                    return [row[0] for row in result.fetchall()]
                elif db_type == "mssql":
                    result = conn.execute(text("SELECT name FROM sys.databases"))
                    system_dbs = {"master", "tempdb", "model", "msdb"}
                    return [row[0] for row in result.fetchall() if row[0].lower() not in system_dbs]
                elif db_type == "sqlite":
                    # SQLite is file-based, only single database
                    if isinstance(connection, dict):
                        db_path = connection.get("database", "")
                    else:
                        db_path = connection.database or ""
                    return [os.path.basename(db_path) if db_path else "default"]
                elif db_type == "oracle":
                    # Oracle connects to a specific service/schema
                    if isinstance(connection, dict):
                        svc = connection.get("service_name") or connection.get("database") or "ORCL"
                    else:
                        svc = connection.service_name or connection.database or "ORCL"
                    return [svc]
            return []
        except Exception as e:
            logger.error(f"获取数据库列表失败: {e}")
            raise

    @staticmethod
    def merge_databases_with_status(live_databases: list, analyzed_databases: list) -> list:
        """将实时数据库列表与已分析的数据库记录合并，返回 {name, status} 列表"""
        analyzed_names = {ad["database_name"] for ad in analyzed_databases}
        live_set = set(live_databases)
        result = [{"name": db, "status": DB_STATUS_EXTRACTED if db in analyzed_names else None} for db in live_databases]
        result.extend({"name": ad["database_name"], "status": DB_STATUS_DELETED} for ad in analyzed_databases if ad["database_name"] not in live_set)
        return result

    def _create_bare_engine(self, connection: Any) -> Optional[Any]:
        """创建数据库引擎（不指定具体数据库，用于列举数据库）"""
        try:
            if isinstance(connection, dict):
                db_type = connection.get("type", "").lower()
                host = connection.get("host")
                port = connection.get("port")
                username = connection.get("username")
                password = connection.get("password")
                service_name = connection.get("service_name")
            else:
                db_type = connection.type.lower() if connection.type else ""
                host = connection.host
                port = connection.port
                username = connection.username
                password = connection.password
                service_name = connection.service_name

            user = quote(username) if username else ""
            pw = quote(password) if password else ""

            if db_type == "mysql":
                url = f"mysql+pymysql://{user}:{pw}@{host}:{port}?charset=utf8mb4"
            elif db_type == "postgresql":
                url = f"postgresql://{user}:{pw}@{host}:{port}/postgres"
            elif db_type == "sqlite":
                # For SQLite, we need a database path to connect
                if isinstance(connection, dict):
                    db_path = connection.get("database")
                else:
                    db_path = connection.database
                if db_path:
                    url = f"sqlite:///{db_path}"
                else:
                    return None
            elif db_type == "oracle":
                if service_name:
                    url = f"oracle+cx_oracle://{user}:{pw}@{host}:{port}/{service_name}"
                else:
                    url = f"oracle+cx_oracle://{user}:{pw}@{host}:{port}"
            elif db_type == "mssql":
                url = f"mssql+pyodbc://{user}:{pw}@{host}:{port}?driver=ODBC+Driver+17+for+SQL+Server"
            else:
                logger.error(f"不支持的数据库类型: {db_type}")
                return None

            return create_engine(url)
        except Exception as e:
            logger.error(f"创建数据库引擎失败: {e}")
            return None

    def _create_engine(self, connection: Any) -> Optional[Any]:
        """根据连接配置创建SQLAlchemy引擎"""
        try:
            if isinstance(connection, dict):
                db_type = connection.get("type", "").lower()
                host = connection.get("host")
                port = connection.get("port")
                database = connection.get("database")
                username = connection.get("username")
                password = connection.get("password")
                service_name = connection.get("service_name")
            else:
                db_type = connection.type.lower() if connection.type else ""
                host = connection.host
                port = connection.port
                database = connection.database
                username = connection.username
                password = connection.password
                service_name = connection.service_name

            user = quote(username) if username else ""
            pw = quote(password) if password else ""

            if db_type == "mysql":
                url = f"mysql+pymysql://{user}:{pw}@{host}:{port}/{database}?charset=utf8mb4"
            elif db_type == "postgresql":
                url = f"postgresql://{user}:{pw}@{host}:{port}/{database}"
            elif db_type == "sqlite":
                url = f"sqlite:///{database}"
            elif db_type == "oracle":
                if service_name:
                    url = f"oracle+cx_oracle://{user}:{pw}@{host}:{port}/{service_name}"
                else:
                    url = f"oracle+cx_oracle://{username}:{password}@{host}:{port}/{database}"
            elif db_type == "mssql":
                url = f"mssql+pyodbc://{username}:{password}@{host}:{port}/{database}?driver=ODBC+Driver+17+for+SQL+Server"
            else:
                logger.error(f"不支持的数据库类型: {db_type}")
                return None
            
            return create_engine(url)
        except Exception as e:
            logger.error(f"创建数据库引擎失败: {e}")
            return None

database_manager = DatabaseManager()