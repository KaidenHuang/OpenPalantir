"""④ 实体抽取（数据库侧）—— 表行批量读取

两套分页策略：
- keyset（WHERE pk > 游标）：大表首选，每页 O(1)，无 OFFSET 退化
- batched（LIMIT/OFFSET）：无主键表回退，需给稳定排序列否则并发写入会丢行/重复

标识符一律过字符白名单（literal_column 无参数化能力）。
"""
import re
from typing import Dict, Iterator, List, Optional

from sqlalchemy import and_, column, literal_column, or_, select, table
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import SQLAlchemyError

from system.logger import logger

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def safe_identifier(name: str) -> str:
    """插进 SQL 的标识符白名单校验"""
    if not _IDENTIFIER_RE.fullmatch(str(name)):
        raise SQLAlchemyError(f"非法标识符: {name!r}")
    return str(name)


def get_primary_key_columns(connection, table_name: str) -> List[str]:
    """用 SQLAlchemy inspect 检测主键列，跨方言兼容"""
    try:
        inspector = sa_inspect(connection)
        pk_constraint = inspector.get_pk_constraint(table_name)
        return pk_constraint.get("constrained_columns", [])
    except SQLAlchemyError as e:
        logger.warning(f"检测表 {table_name} 的主键时出错: {e}")
        return []


def read_rows_batched(connection, table_name: str, columns: List[str],
                      batch_size: int = 5000, max_rows: int = 0,
                      order_keys: Optional[List[str]] = None) -> Iterator[List[Dict]]:
    """LIMIT/OFFSET 分页读取（无主键表回退；order_keys 保证页间稳定）"""
    try:
        order_cols = [safe_identifier(c) for c in (order_keys or [])]
        t = table(table_name, *[column(c) for c in columns])
        offset = 0
        total_yielded = 0
        while True:
            if max_rows > 0 and total_yielded >= max_rows:
                break
            limit = min(batch_size, max_rows - total_yielded) if max_rows > 0 else batch_size
            stmt = select(t).limit(limit).offset(offset)
            if order_cols:
                stmt = stmt.order_by(*[literal_column(c) for c in order_cols])
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


def read_rows_keyset(connection, table_name: str, columns: List[str],
                     pk_columns: List[str], batch_size: int = 5000,
                     max_rows: int = 0) -> Iterator[List[Dict]]:
    """主键游标分页读取；无主键时回退 LIMIT/OFFSET"""
    if not pk_columns:
        logger.warning(f"表 {table_name} 无主键，回退 LIMIT/OFFSET 分页")
        yield from read_rows_batched(
            connection, table_name, columns, batch_size, max_rows, order_keys=columns)
        return

    try:
        t = table(table_name, *[column(c) for c in columns])
        pk_cols_sa = [literal_column(safe_identifier(c)) for c in pk_columns]
        total_yielded = 0
        last_values = None  # 上一批最后一行的各主键值

        while True:
            if max_rows > 0 and total_yielded >= max_rows:
                break
            limit = min(batch_size, max_rows - total_yielded) if max_rows > 0 else batch_size

            stmt = select(t).limit(limit).order_by(*pk_cols_sa)
            if last_values is not None:
                if len(pk_columns) == 1:
                    stmt = stmt.where(
                        literal_column(safe_identifier(pk_columns[0])) > last_values[0])
                else:
                    # 复合键：(pk1 > v1) OR (pk1 = v1 AND pk2 > v2) OR ...
                    clauses = []
                    for i in range(len(pk_columns)):
                        eq_clauses = [
                            literal_column(safe_identifier(pk_columns[j])) == last_values[j]
                            for j in range(i)
                        ]
                        gt_clause = literal_column(safe_identifier(pk_columns[i])) > last_values[i]
                        clauses.append(and_(*eq_clauses, gt_clause) if eq_clauses else gt_clause)
                    stmt = stmt.where(or_(*clauses))

            result = connection.execute(stmt)
            db_columns = list(result.keys())
            rows = result.fetchall()
            if not rows:
                break

            batch = [dict(zip(db_columns, row)) for row in rows]
            yield batch
            total_yielded += len(batch)

            last_row = rows[-1]
            col_index = {name: idx for idx, name in enumerate(db_columns)}
            last_values = [last_row[col_index[pk]] for pk in pk_columns]

    except Exception as e:
        logger.error(f"游标分页查询表 {table_name} 时出错: {e}，回退 LIMIT/OFFSET")
        yield from read_rows_batched(
            connection, table_name, columns, batch_size, max_rows, order_keys=pk_columns)
