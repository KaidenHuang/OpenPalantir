"""③ 数据库侧概要结构组装 —— Schema（含视图）→ 决策引擎可检索的概要 dict

纯转换无 IO；落盘走同目录 store.save。
"""
from typing import Any, Dict, List


def build_db_summary_file(connection_id: str, analyzed_db_name: str,
                          db_summary: Dict[str, Any],
                          annotated_schema: Dict) -> Dict:
    """把标注后的 Schema 组装为数据库概要 JSON 结构（structure 节点含键信息）"""
    table_list = [
        {k.lower(): v for k, v in t.items()}
        for t in annotated_schema.get("tables", [])
    ]
    columns_list = [
        {k.lower(): v for k, v in c.items()}
        for c in annotated_schema.get("columns", [])
    ]
    raw_columns = columns_list
    raw_fks = [
        {k.lower(): v for k, v in fk.items()}
        for fk in annotated_schema.get("foreign_keys", [])
    ]

    views_list = [
        {k.lower(): v for k, v in v.items()}
        for v in annotated_schema.get("views", [])
    ]

    columns_by_table: Dict[str, List[Dict]] = {}
    for col in columns_list:
        columns_by_table.setdefault(col["table_name"], []).append(col)

    col_types: Dict[tuple, str] = {}
    for col in raw_columns:
        tn = col.get("table_name", "")
        cn = col.get("column_name", "")
        dt = col.get("data_type", "")
        if tn and cn:
            col_types[(tn, cn)] = dt

    fk_by_table: Dict[str, List[Dict]] = {}
    for fk in raw_fks:
        table = fk.get("table_name", "")
        col = fk.get("column_name", "")
        ref_table = fk.get("referenced_table_name", "")
        ref_col = fk.get("referenced_column_name", "")
        if table:
            fk_by_table.setdefault(table, []).append({
                "column": col,
                "references": f"{ref_table}.{ref_col}",
            })

    pk_columns: Dict[str, List[str]] = {}
    uk_columns: Dict[str, List[str]] = {}
    for col in raw_columns:
        tn = col.get("table_name", "")
        cn = col.get("column_name", "")
        ck = col.get("column_key", "")
        if tn and cn:
            if ck == "PRI":
                pk_columns.setdefault(tn, []).append(cn)
            elif ck == "UNI":
                uk_columns.setdefault(tn, []).append(cn)

    structure_nodes = []
    for idx, tbl in enumerate(table_list):
        tbl_name = tbl["table_name"]
        col_names = [c["column_name"] for c in columns_by_table.get(tbl_name, [])]
        cols_with_types = [
            f'{c}({col_types.get((tbl_name, c), "")})'
            for c in col_names
        ]

        table_keys = []
        seen = set()
        for c in pk_columns.get(tbl_name, []):
            table_keys.append({"column": c, "type": "PRIMARY KEY"})
            seen.add(c)
        for c in uk_columns.get(tbl_name, []):
            if c not in seen:
                table_keys.append({"column": c, "type": "UNIQUE KEY"})
                seen.add(c)
        for fk_entry in fk_by_table.get(tbl_name, []):
            table_keys.append({
                "column": fk_entry["column"],
                "type": "FOREIGN KEY",
                "references": fk_entry["references"],
            })

        structure_nodes.append({
            "table_name": tbl_name,
            "node_id": str(idx + 1).zfill(8),
            "description": f"包含字段: {', '.join(cols_with_types)}",
            "summary": tbl.get("business_description", ""),
            "entity_type": tbl.get("entity_type", ""),
            "table_role": tbl.get("table_role", "entity"),
            "keys": table_keys,
        })

    return {
        "db_name": analyzed_db_name or "default",
        "db_description": db_summary.get("overview", ""),
        "business_domain": db_summary.get("business_domain", ""),
        "key_entities": db_summary.get("key_entities", ""),
        "table_count": len(table_list),
        "structure": structure_nodes,
        "views": [
            {
                "view_name": v.get("view_name", ""),
                "definition": v.get("definition", ""),
                "columns": [
                    {
                        "column_name": c.get("column_name", ""),
                        "data_type": c.get("data_type", ""),
                    }
                    for c in v.get("columns", [])
                ],
            }
            for v in views_list
        ],
    }
