"""
数据库Schema业务标注器

使用LLM对数据库Schema进行业务标注，包括表的业务描述、实体类型、字段的语义类型等。
"""

import json
from typing import Dict, List, Any, Optional
from system.logger import logger
from model_management import ModelClient, ModelConfig, ModelService


def check_and_get_available_model(db) -> Optional[Dict[str, Any]]:
    """
    检查并获取可用的模型配置（供外部调用）
    
    在数据库分析模块进行业务标注前调用此函数，确保有可用的模型。
    
    Args:
        db: 数据库会话
        
    Returns:
        Dict: 可用模型的配置字典，如果没有可用模型返回None
    """
    return ModelService.get_available_model(db)


class SchemaAnnotator:
    """
    数据库Schema业务标注器
    
    使用LLM对数据库Schema进行业务标注，支持本地模型和云端模型。
    
    Features:
        - 批量标注数据库表和字段
        - 自动推断表间关系
        - 支持多种数据库类型
        - 统一的模型调用接口
        - 自动获取可用模型
    
    使用示例:
        annotator = SchemaAnnotator(model_config)
        annotated_schema = annotator.batch_annotate(schema)
    """
    
    def __init__(self, model_config: Optional[Any] = None, db_session=None):
        """
        初始化Schema标注器
        
        Args:
            model_config: 模型配置，可以是：
                         - ModelConfig实例
                         - 字典格式的配置
                         - None（自动获取可用模型）
            db_session: 数据库会话（当model_config为None时用于获取可用模型）
        """
        # 如果没有提供模型配置，尝试自动获取可用模型
        if model_config is None:
            if db_session is not None:
                model_config = ModelService.get_available_model(db_session)
                if model_config:
                    logger.info(f"自动获取到可用模型: {model_config.get('name')}")
                else:
                    logger.warning("未提供模型配置，且未找到可用模型，将使用默认配置")
        
        self.model_config = model_config
        self.model_client = ModelClient(model_config)
        self.has_available_model = model_config is not None
    
    def batch_annotate(self, schema: Dict) -> Dict:
        """
        批量标注数据库Schema（数据库级别）
        
        Args:
            schema: 包含tables、columns、foreign_keys的Schema字典
            
        Returns:
            Dict: 标注后的完整Schema，包含业务描述和实体类型
        """
        # 检查是否有可用模型
        if not self.has_available_model:
            logger.warning("没有可用的模型，跳过业务标注")
            return schema
        
        try:
            # ===== 标注前日志输出 =====
            logger.debug("===== Schema标注前 =====")
            tables_before = schema.get('tables', [])
            columns_before = schema.get('columns', [])
            fks_before = schema.get('foreign_keys', [])

            logger.debug(f"tables_before: {json.dumps(tables_before, ensure_ascii=False, indent=2)}")
            logger.debug(f"columns_before: {json.dumps(columns_before, ensure_ascii=False, indent=2)}")
            logger.debug(f"foreign_keys_before: {json.dumps(fks_before, ensure_ascii=False, indent=2)}")
            
            prompt = self._build_annotate_prompt(schema)
            
            system_prompt = "你是一个数据库Schema分析专家，请分析数据库结构并提供业务标注。"
            
            logger.info("开始调用LLM进行业务标注...")
            response_json = self.model_client.call_json(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=16384
            )
            
            if not response_json:
                logger.error("标注模型响应为空或解析失败")
                return schema
            
            # 打印LLM响应结果
            logger.debug(f"LLM响应成功，响应类型: {type(response_json)}")
            logger.debug(f"LLM响应内容: {json.dumps(response_json, ensure_ascii=False, indent=2)[:2000]}")
            
            annotated_result = self._parse_annotated_result(response_json)
            logger.debug(f"解析后的标注结果 - 表数量: {len(annotated_result.get('tables', []))}, 字段数量: {len(annotated_result.get('columns', []))}, 关系数量: {len(annotated_result.get('relationships', []))}")
            
            schema = self._merge_annotations(schema, annotated_result)

            # 从标注结果中提取数据库概要，写入返回的schema
            db_summary = annotated_result.get("database_summary", {})
            if db_summary:
                schema["database_summary"] = db_summary
                logger.debug(f"数据库概要: {json.dumps(db_summary, ensure_ascii=False)}")

            # ===== 标注后日志输出 =====
            logger.debug("===== Schema标注后 =====")
            tables_after = schema.get('tables', [])
            columns_after = schema.get('columns', [])
            inferred_rels = schema.get('inferred_relationships', [])

            logger.debug(f"tables_after: {json.dumps(tables_after, ensure_ascii=False, indent=2)}")
            logger.debug(f"columns_after: {json.dumps(columns_after, ensure_ascii=False, indent=2)}")
            logger.debug(f"inferred_relationships: {json.dumps(inferred_rels, ensure_ascii=False, indent=2)}")
            
            return schema
        
        except Exception as e:
            logger.error(f"Schema标注失败: {e}")
            import traceback
            logger.error(f"异常堆栈: {traceback.format_exc()}")
            return schema
    
    def _normalize_keys(self, d: Dict) -> Dict:
        """将字典的键统一转为小写，处理不同数据库驱动返回列名大小写不一致的问题"""
        return {k.lower(): v for k, v in d.items()}

    def _build_annotate_prompt(self, schema: Dict) -> str:
        """
        构建标注提示词

        Args:
            schema: Schema字典

        Returns:
            str: 构建好的提示词
        """
        import os

        tables = [self._normalize_keys(t) for t in schema.get('tables', [])]
        columns = [self._normalize_keys(c) for c in schema.get('columns', [])]
        foreign_keys = [self._normalize_keys(fk) for fk in schema.get('foreign_keys', [])]

        tables_info = "\n".join([f"- {t['table_name']}: {t.get('table_type', 'TABLE')}" for t in tables])
        
        columns_info = []
        table_columns = {}
        for col in columns:
            table_name = col['table_name']
            if table_name not in table_columns:
                table_columns[table_name] = []
            table_columns[table_name].append(col)

        for table_name, cols in table_columns.items():
            cols_info = ", ".join([f"{c['column_name']}({c['data_type']})" for c in cols])
            columns_info.append(f"- {table_name}: [{cols_info}]")

        columns_text = "\n".join(columns_info)

        fk_info = []
        for fk in foreign_keys:
            table_name = fk.get('table_name')
            column_name = fk.get('column_name')
            ref_table_name = fk.get('referenced_table_name')
            ref_column_name = fk.get('referenced_column_name')

            if table_name and column_name and ref_table_name and ref_column_name:
                fk_info.append(f"- {table_name}.{column_name} -> {ref_table_name}.{ref_column_name}")
            else:
                logger.warning(f"外键数据不完整: {fk}")
        
        fk_text = "\n".join(fk_info) if fk_info else "无外键约束"
        
        # 读取提示词模板文件
        prompt_template_path = os.path.join(
            os.path.dirname(__file__),
            "prompt_schema_annotate.md"
        )
        
        with open(prompt_template_path, 'r', encoding='utf-8') as f:
            prompt_template = f.read()
        
        # 替换模板变量（使用简单的字符串替换，避免format的解析问题）
        prompt = prompt_template.replace('{tables_info}', tables_info)\
                               .replace('{columns_text}', columns_text)\
                               .replace('{fk_text}', fk_text)
        
        return prompt
    
    def _parse_annotated_result(self, result: Dict) -> Dict:
        """
        解析标注结果（新缩写格式 → 内部展开格式）

        LLM返回的紧凑格式：
          tables: [{t, d, et, cols: [{c, d}]}]
          rels: [{s, sc, t, tc, r, d}]
          db: {ov, dom, ke}

        展开为内部格式：
          tables: [{table_name, business_description, entity_type}]
          columns: [{table_name, column_name, business_description}]
          relationships: [{source_table, source_column, target_table, ...}]
          database_summary: {overview, business_domain, key_entities}
        """
        tables_out = []
        columns_out = []
        for tbl in result.get("tables", []):
            tables_out.append({
                "table_name": tbl["t"],
                "business_description": tbl.get("d", ""),
                "entity_type": tbl.get("et", "other"),
            })
            for col in tbl.get("cols", []):
                columns_out.append({
                    "table_name": tbl["t"],
                    "column_name": col["c"],
                    "business_description": col.get("d", ""),
                })

        db_src = result.get("db", {})
        return {
            "tables": tables_out,
            "columns": columns_out,
            "relationships": [
                {
                    "source_table": r["s"],
                    "source_column": r.get("sc", ""),
                    "target_table": r["t"],
                    "target_column": r.get("tc", ""),
                    "relationship_type": r.get("r", ""),
                    "description": r.get("d", ""),
                }
                for r in result.get("rels", [])
            ],
            "database_summary": {
                "overview": db_src.get("ov", ""),
                "business_domain": db_src.get("dom", ""),
                "key_entities": db_src.get("ke", ""),
            },
        }
    
    def _merge_annotations(self, schema: Dict, annotated: Dict) -> Dict:
        """
        合并标注信息到Schema

        Args:
            schema: 原始Schema
            annotated: LLM标注结果

        Returns:
            Dict: 合并后的Schema
        """
        # 构建表名和字段名的精确匹配映射
        table_annotations = {t["table_name"]: t for t in annotated.get("tables", [])}
        column_annotations = {(c["table_name"], c["column_name"]): c for c in annotated.get("columns", [])}

        for table in schema.get("tables", []):
            name = self._resolve_key(table, 'table_name')
            if not name:
                continue
            annotation = table_annotations.get(name)
            if annotation:
                table["business_description"] = annotation.get("business_description")
                table["entity_type"] = annotation.get("entity_type")

        for column in schema.get("columns", []):
            col_name = self._resolve_key(column, 'column_name')
            tbl_name = self._resolve_key(column, 'table_name')
            if not col_name or not tbl_name:
                continue
            annotation = column_annotations.get((tbl_name, col_name))
            if annotation:
                column["business_description"] = annotation.get("business_description")

        schema["inferred_relationships"] = annotated.get("relationships", [])

        return schema

    @staticmethod
    def _resolve_key(d: Dict, key: str) -> Optional[str]:
        """不区分大小写从字典中获取键值"""
        for k, v in d.items():
            if k.lower() == key.lower():
                return v
        return None


# 创建默认实例
schema_annotator = SchemaAnnotator()
