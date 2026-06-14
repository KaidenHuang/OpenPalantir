"""
CDC Schema 缓存 — 从 SQLite 加载数据库 Schema 信息供事件处理使用
"""
from typing import Dict, List, Optional, Any
from config.database import SessionLocal
from database_management.database_service import DatabaseService
from system.logger import logger


class SchemaCache:
    """缓存源数据库的 Schema 信息（表/列/PK/FK/entity_type），供 CDC 事件处理使用"""

    def __init__(self, connection_id: str, database_name: str):
        self.connection_id = connection_id
        self.database_name = database_name

        # 按表名索引的数据
        self.table_columns: Dict[str, List[str]] = {}         # {table: [col_name, ...]}
        self.pk_columns: Dict[str, List[str]] = {}            # {table: [pk_col_name, ...]}
        self.fk_columns: Dict[str, List[Dict]] = {}           # {table: [{column, ref_table, ref_column}, ...]}
        self.entity_types: Dict[str, str] = {}                # {table: entity_type}
        self.tables: List[str] = []                           # 表名列表

    def load(self):
        """从 SQLite 加载 Schema 信息"""
        db = SessionLocal()
        try:
            service = DatabaseService()
            schema = service.get_schema(db, self.connection_id)

            if not schema["tables"]:
                raise ValueError(f"未找到 Schema 信息，请先对连接 {self.connection_id} 执行分析任务")

            # 加载表信息
            for table_info in schema["tables"]:
                table_name = table_info["table_name"]
                self.tables.append(table_name)
                self.entity_types[table_name] = table_info.get("entity_type", "其他")

            # 加载列信息（按表分组）
            columns_by_table: Dict[str, List[Dict]] = {}
            for col in schema["columns"]:
                columns_by_table.setdefault(col["table_name"], []).append(col)

            for table_name, cols in columns_by_table.items():
                self.table_columns[table_name] = [c["column_name"] for c in cols]

            # 加载主键信息
            for table_name, cols in columns_by_table.items():
                pk_cols = [c["column_name"] for c in cols
                           if c.get("column_key", "").upper() in ("PRI", "PRIMARY KEY", "PK")]
                if not pk_cols:
                    # 回退：使用第一列作为代理主键
                    pk_cols = [cols[0]["column_name"]] if cols else []
                    logger.warning(f"CDC Schema 缓存: 表 {table_name} 未检测到主键，使用第一列 {pk_cols}")
                self.pk_columns[table_name] = pk_cols

            # 加载外键信息
            for fk in schema["foreign_keys"]:
                table_name = fk.get("table_name", fk.get("TABLE_NAME", ""))
                col_name = fk.get("column_name", fk.get("COLUMN_NAME", ""))
                ref_table = fk.get("referenced_table_name", fk.get("REFERENCED_TABLE_NAME", ""))
                ref_col = fk.get("referenced_column_name", fk.get("REFERENCED_COLUMN_NAME", ""))

                if not all([table_name, col_name, ref_table, ref_col]):
                    continue

                self.fk_columns.setdefault(table_name, []).append({
                    "column": col_name,
                    "referenced_table_name": ref_table,
                    "referenced_column_name": ref_col,
                })

            logger.info(
                f"CDC Schema 缓存加载完成: {len(self.tables)} 个表, "
                f"{sum(len(v) for v in self.fk_columns.values())} 个外键"
            )

        finally:
            db.close()

    def get_stream_keys(self, topic_prefix: str = "openpalantir") -> List[str]:
        """生成要订阅的 Redis Stream key 列表"""
        return [f"{topic_prefix}.{self.database_name}.{t}" for t in self.tables]

    def build_entity_name(self, table_name: str, row: Dict) -> str:
        """构建实体名称: {table_name}:{pk_value1}:{pk_value2}:..."""
        pk_cols = self.pk_columns.get(table_name, [])
        pk_values = []
        for col in pk_cols:
            val = row.get(col)
            if val is None or str(val).strip() == "" or str(val) == "None":
                return ""
            pk_values.append(str(val))
        return f"{table_name}:{':'.join(pk_values)}"

    def get_all_column_names(self, table_name: str) -> List[str]:
        """获取表的所有列名"""
        return self.table_columns.get(table_name, [])
