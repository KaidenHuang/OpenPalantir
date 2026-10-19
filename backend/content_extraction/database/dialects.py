"""数据库方言与 Schema 提取（阶段②数据库侧提取核心）

连接 CRUD 归 source_registry/database/registry.py，引擎构建归
content_extraction/database/connector.py，行级批量读取归 entity_extraction/database/row_reader.py。
"""
from typing import Dict, List, Optional

from sqlalchemy import text
from system.logger import logger


class DatabaseDialect:
    """数据库方言抽象基类（数据库级别批量操作）"""

    def capture_binlog_position(self, connection) -> Optional[Dict]:
        """捕获当前 binlog/WAL 位点（供 CDC 衔接使用）

        Returns:
            MySQL: {"file": "mysql-bin.000003", "position": 154}
            PostgreSQL: {"wal_lsn": "0/16B3748"}
            不支持的数据库: None
        """
        return None

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
        raise NotImplementedError

    def extract_views(self, connection) -> List[Dict]:
        """提取视图信息（默认不支持，方言可选实现）"""
        return []

    def _execute_query(self, connection, query) -> List[Dict]:
        """执行SQL查询并返回结果列表（子类共享实现）"""
        try:
            result = connection.execute(text(query))
            rows = result.fetchall()
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"{type(self).__name__} 查询执行失败: {e}")
            return []

class MySQLDialect(DatabaseDialect):
    """MySQL方言"""

    def capture_binlog_position(self, connection) -> Optional[Dict]:
        """获取 MySQL binlog 当前位点"""
        try:
            result = connection.execute(text("SHOW MASTER STATUS"))
            row = result.fetchone()
            if row:
                columns = list(result.keys())
                data = dict(zip(columns, row))
                return {
                    "file": data.get("File", ""),
                    "position": data.get("Position", 0),
                }
        except Exception as e:
            logger.warning(f"获取 MySQL binlog 位点失败: {e}")
        return None

    def extract_full_schema(self, connection) -> Dict:
        """批量提取MySQL数据库完整Schema"""
        result: Dict = {"tables": [], "columns": [], "foreign_keys": []}

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
        result["views"] = self.extract_views(connection)
        return result

    def extract_views(self, connection) -> List[Dict]:
        """提取视图定义与视图列"""
        views_query = """
            SELECT TABLE_NAME AS view_name,
                   VIEW_DEFINITION AS definition
            FROM information_schema.views
            WHERE TABLE_SCHEMA = DATABASE()
        """
        view_columns_query = """
            SELECT TABLE_NAME AS view_name,
                   COLUMN_NAME AS column_name,
                   DATA_TYPE AS data_type,
                   IS_NULLABLE AS is_nullable
            FROM information_schema.columns
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME IN (SELECT TABLE_NAME FROM information_schema.views
                                 WHERE TABLE_SCHEMA = DATABASE())
        """
        views = self._execute_query(connection, views_query)
        view_columns = self._execute_query(connection, view_columns_query)

        columns_by_view: Dict[str, List[Dict]] = {}
        for col in view_columns:
            columns_by_view.setdefault(col.get("view_name", ""), []).append({
                "column_name": col.get("column_name", ""),
                "data_type": col.get("data_type", ""),
                "is_nullable": col.get("is_nullable", ""),
            })
        for view in views:
            view["columns"] = columns_by_view.get(view.get("view_name", ""), [])
        return views


class PostgreSQLDialect(DatabaseDialect):
    """PostgreSQL方言"""

    def capture_binlog_position(self, connection) -> Optional[Dict]:
        """获取 PostgreSQL WAL 当前 LSN"""
        try:
            result = connection.execute(text("SELECT pg_current_wal_lsn()"))
            lsn = result.scalar()
            if lsn:
                return {"wal_lsn": str(lsn)}
        except Exception as e:
            logger.warning(f"获取 PostgreSQL WAL LSN 失败: {e}")
        return None

    def extract_full_schema(self, connection) -> Dict:
        """批量提取PostgreSQL数据库完整Schema"""
        result: Dict = {"tables": [], "columns": [], "foreign_keys": []}

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
        result["views"] = self.extract_views(connection)
        return result

    def extract_views(self, connection) -> List[Dict]:
        """提取视图定义与视图列（public schema）"""
        views_query = """
            SELECT view_name, definition
            FROM (
                SELECT c.relname AS view_name,
                       pg_get_viewdef(c.oid, true) AS definition
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'v'
            ) v
        """
        view_columns_query = """
            SELECT table_name AS view_name,
                   column_name,
                   data_type,
                   is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN (
                  SELECT c.relname FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                  WHERE n.nspname = 'public' AND c.relkind = 'v'
              )
        """
        views = self._execute_query(connection, views_query)
        view_columns = self._execute_query(connection, view_columns_query)

        columns_by_view: Dict[str, List[Dict]] = {}
        for col in view_columns:
            columns_by_view.setdefault(col.get("view_name", ""), []).append({
                "column_name": col.get("column_name", ""),
                "data_type": col.get("data_type", ""),
                "is_nullable": col.get("is_nullable", ""),
            })
        for view in views:
            view["columns"] = columns_by_view.get(view.get("view_name", ""), [])
        return views


class SQLiteDialect(DatabaseDialect):
    """SQLite方言"""

    def extract_full_schema(self, connection) -> Dict:
        """批量提取SQLite数据库完整Schema"""
        result: Dict = {"tables": [], "columns": [], "foreign_keys": []}

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
        result["views"] = self.extract_views(connection)
        return result

    def extract_views(self, connection) -> List[Dict]:
        """提取视图定义与视图列"""
        views_query = """
            SELECT name AS view_name,
                   COALESCE(sql, '') AS definition
            FROM sqlite_master
            WHERE type = 'view' AND name NOT LIKE 'sqlite_%'
        """
        views = self._execute_query(connection, views_query)

        all_view_columns = self._execute_query(connection, """
            SELECT m.name AS view_name,
                   p.name AS column_name,
                   p.type AS data_type,
                   CASE WHEN p.notnull = 1 THEN 'NO' ELSE 'YES' END AS is_nullable
            FROM sqlite_master m
            JOIN pragma_table_info(m.name) p
            WHERE m.type = 'view' AND m.name NOT LIKE 'sqlite_%'
        """)
        columns_by_view: Dict[str, List[Dict]] = {}
        for col in all_view_columns:
            columns_by_view.setdefault(col.get("view_name", ""), []).append({
                "column_name": col.get("column_name", ""),
                "data_type": col.get("data_type", ""),
                "is_nullable": col.get("is_nullable", ""),
            })
        for view in views:
            view["columns"] = columns_by_view.get(view.get("view_name", ""), [])
        return views


class OracleDialect(DatabaseDialect):
    """Oracle方言"""

    def extract_full_schema(self, connection) -> Dict:
        """批量提取Oracle数据库完整Schema"""
        result: Dict = {"tables": [], "columns": [], "foreign_keys": []}

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
        result["views"] = self.extract_views(connection)
        return result

    def extract_views(self, connection) -> List[Dict]:
        """提取视图定义与视图列"""
        owner = "SYS_CONTEXT('USERENV', 'CURRENT_USER')"
        views_query = f"""
            SELECT view_name, text AS definition
            FROM all_views
            WHERE owner = {owner}
        """
        view_columns_query = f"""
            SELECT view_name, column_name, data_type, nullable AS is_nullable
            FROM all_tab_columns
            WHERE owner = {owner}
              AND table_name IN (SELECT view_name FROM all_views WHERE owner = {owner})
        """
        views = self._execute_query(connection, views_query)
        view_columns = self._execute_query(connection, view_columns_query)

        columns_by_view: Dict[str, List[Dict]] = {}
        for col in view_columns:
            columns_by_view.setdefault(col.get("view_name", ""), []).append({
                "column_name": col.get("column_name", ""),
                "data_type": col.get("data_type", ""),
                "is_nullable": col.get("is_nullable", ""),
            })
        for view in views:
            view["columns"] = columns_by_view.get(view.get("view_name", ""), [])
        return views


class SQLServerDialect(DatabaseDialect):
    """SQL Server方言"""

    def extract_full_schema(self, connection) -> Dict:
        """批量提取SQL Server数据库完整Schema"""
        result: Dict = {"tables": [], "columns": [], "foreign_keys": []}

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
        result["views"] = self.extract_views(connection)
        return result

    def extract_views(self, connection) -> List[Dict]:
        """提取视图定义与视图列"""
        views_query = """
            SELECT i.table_name AS view_name,
                   ISNULL(sm.definition, '') AS definition
            FROM information_schema.views i
            LEFT JOIN sys.sql_modules sm ON sm.object_id = OBJECT_ID(i.table_name)
        """
        view_columns_query = """
            SELECT table_name AS view_name,
                   column_name,
                   data_type,
                   is_nullable
            FROM information_schema.columns
            WHERE table_name IN (SELECT table_name FROM information_schema.views)
        """
        views = self._execute_query(connection, views_query)
        view_columns = self._execute_query(connection, view_columns_query)

        columns_by_view: Dict[str, List[Dict]] = {}
        for col in view_columns:
            columns_by_view.setdefault(col.get("view_name", ""), []).append({
                "column_name": col.get("column_name", ""),
                "data_type": col.get("data_type", ""),
                "is_nullable": col.get("is_nullable", ""),
            })
        for view in views:
            view["columns"] = columns_by_view.get(view.get("view_name", ""), [])
        return views


DIALECT_MAP = {
    "mysql": MySQLDialect,
    "postgresql": PostgreSQLDialect,
    "sqlite": SQLiteDialect,
    "oracle": OracleDialect,
    "mssql": SQLServerDialect,
}


class SchemaExtractor:
    """Schema 提取编排：引擎 + 方言 + 过滤"""

    def extract(self, connection_cfg: Dict, engine, tables: List[str] = None,
                ignore_tables: List[str] = None) -> Dict:
        """按方言提取完整 Schema（含视图），并按表过滤"""
        dialect_type = (connection_cfg.get("type") or "").lower()
        if dialect_type not in DIALECT_MAP:
            raise ValueError(f"不支持的数据库类型: {dialect_type}")

        dialect = DIALECT_MAP[dialect_type]()
        with engine.connect() as conn:
            schema = dialect.extract_full_schema(conn)

        if tables:
            table_names = set(tables)
            schema["tables"] = [t for t in schema["tables"] if t.get("table_name") in table_names]
            schema["columns"] = [c for c in schema["columns"] if c.get("table_name") in table_names]
            schema["foreign_keys"] = [fk for fk in schema["foreign_keys"]
                                      if fk.get("table_name") in table_names
                                      or fk.get("referenced_table_name") in table_names]
            schema["views"] = [v for v in schema.get("views", [])
                               if v.get("view_name") in table_names]

        if ignore_tables:
            ignore_names = set(ignore_tables)
            schema["tables"] = [t for t in schema["tables"] if t.get("table_name") not in ignore_names]
            schema["columns"] = [c for c in schema["columns"] if c.get("table_name") not in ignore_names]
            schema["foreign_keys"] = [fk for fk in schema["foreign_keys"]
                                      if fk.get("table_name") not in ignore_names
                                      and fk.get("referenced_table_name") not in ignore_names]
            schema["views"] = [v for v in schema.get("views", [])
                               if v.get("view_name") not in ignore_names]

        logger.info(f"Schema提取成功, 表数量: {len(schema['tables'])}, 视图数量: {len(schema.get('views', []))}")
        return schema

    def capture_position(self, connection_cfg: Dict, conn) -> Optional[Dict]:
        """捕获 binlog/WAL 位点（CDC 衔接）"""
        dialect_type = (connection_cfg.get("type") or "").lower()
        if dialect_type not in DIALECT_MAP:
            return None
        return DIALECT_MAP[dialect_type]().capture_binlog_position(conn)


schema_extractor = SchemaExtractor()
