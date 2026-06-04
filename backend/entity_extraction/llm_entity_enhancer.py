"""
LLM实体增强器

使用LLM对文本进行实体识别和关系提取，支持本地模型和云端模型。
"""

import os
import json
from typing import List, Dict, Any, Optional
from system.logger import logger
from model_management import ModelClient, ModelConfig


class LLMEntityEnhancer:
    """
    LLM实体增强器
    
    使用LLM对文本进行实体识别和关系提取，支持本地模型和云端模型。
    
    Features:
        - 实体识别和增强
        - 关系提取
        - 同时提取实体和关系
        - 支持长文本分块处理
        - JSON格式自动修复
    
    使用示例:
        enhancer = LLMEntityEnhancer(model_config)
        entities = enhancer.enhance_entities(text)
        result = enhancer.extract_entities_and_relationships(text)
    """
    
    def __init__(self, model_config: Optional[Any] = None, max_retries: int = 3, retry_delay: float = 1.0):
        """
        初始化LLM实体增强器
        
        Args:
            model_config: 模型配置，可以是：
                         - ModelConfig实例
                         - 字典格式的配置
                         - None（使用默认配置）
            max_retries: 最大重试次数，默认3次
            retry_delay: 重试间隔（秒），默认1秒
        """
        # 处理model_config为None的情况
        if model_config is None:
            self.model_client = ModelClient()
        elif isinstance(model_config, dict):
            config = ModelConfig.from_dict(model_config)
            config.max_retries = max_retries
            config.retry_delay = retry_delay
            self.model_client = ModelClient(config)
        elif isinstance(model_config, ModelConfig):
            model_config.max_retries = max_retries
            model_config.retry_delay = retry_delay
            self.model_client = ModelClient(model_config)
        else:
            # 尝试从对象属性获取配置
            config = ModelConfig(
                type=getattr(model_config, 'type', 'local'),
                models=getattr(model_config, 'models', ['qwen2.5:7b']),
                api_url=getattr(model_config, 'api_url', 'http://localhost:11434'),
                api_key=getattr(model_config, 'api_key', ''),
                max_retries=max_retries,
                retry_delay=retry_delay
            )
            self.model_client = ModelClient(config)
    
    def enhance_entities(self, text: str, stream: bool = False, on_chunk: callable = None) -> List[Dict[str, Any]]:
        """
        使用LLM增强实体识别
        
        Args:
            text: 要分析的文本
            stream: 是否启用流式输出（暂未实现）
            on_chunk: 流式输出的回调函数（暂未实现）
            
        Returns:
            List[Dict]: 增强后的实体列表
        """
        try:
            prompt = self._build_prompt(text)
            logger.info(f"构建实体识别提示词，长度: {len(prompt)}")
            
            system_prompt = "你是一个实体识别专家，需要根据给定的文本，返回准确的实体列表。"
            
            response_json = self.model_client.call_json(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0,
                max_tokens=8192
            )
            
            if not response_json:
                logger.error("响应为空，无法解析JSON")
                return []
            
            # 处理返回的 {"entities": [...]} 格式
            if isinstance(response_json, dict) and 'entities' in response_json:
                enhanced_entities = response_json['entities']
            elif isinstance(response_json, list):
                enhanced_entities = response_json
            else:
                enhanced_entities = []
            
            logger.debug(f"解析后的增强实体: {enhanced_entities}")
            return enhanced_entities
            
        except Exception as e:
            logger.error(f"实体增强失败: {e}")
            return []
    
    def extract_entities_and_relationships(self, text: str, max_chunk_length: int = 25000) -> Dict[str, List[Dict[str, Any]]]:
        """
        使用LLM同时提取实体和实体关系
        
        Args:
            text: 要分析的文本
            max_chunk_length: 单个文本块的最大长度，超过此长度将自动分块处理
            
        Returns:
            Dict: 包含实体列表和关系列表的字典
        """
        try:
            # 检查文本长度，如果过长则分块处理
            if len(text) <= max_chunk_length:
                prompt = self._build_combined_prompt(text)
                logger.info(f"构建同时提取实体和关系的提示词，长度: {len(prompt)}")
                
                system_prompt = "你是一个实体和关系提取专家，需要根据给定的文本，同时识别实体和提取实体之间的关系。"
                
                response_json = self.model_client.call_json(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=0,
                    max_tokens=8192
                )
                
                if response_json:
                    entities = self._get_entities(response_json)
                    relationships = self._get_relationships(response_json)
                    logger.debug(f"提取到的实体: {entities}")
                    logger.debug(f"提取到的关系: {relationships}")
                    return {"entities": entities, "relationships": relationships}
                else:
                    # 模型返回空但文本足够长，在句子边界切半后分别重试
                    if len(text) > 2000:
                        logger.info(f"LLM返回空，尝试切半后重试（文本长度: {len(text)}）")
                        mid = self._find_split_point(text, len(text) // 2)
                        left = self.extract_entities_and_relationships(text[:mid])
                        right = self.extract_entities_and_relationships(text[mid:])
                        entities = left.get("entities", []) + right.get("entities", [])
                        relationships = left.get("relationships", []) + right.get("relationships", [])
                        seen = set()
                        deduped = []
                        for e in entities:
                            key = f"{e.get('n', '')}_{e.get('t', '')}"
                            if key not in seen:
                                seen.add(key)
                                deduped.append(e)
                        logger.info(f"切半重试完成，共提取 {len(deduped)} 个实体和 {len(relationships)} 个关系")
                        return {"entities": deduped, "relationships": relationships}
                    return {"entities": [], "relationships": []}
            else:
                # 文本过长，需要分块处理
                logger.info(f"文本长度 {len(text)} 超过限制 {max_chunk_length}，开始分块处理")
                return self._extract_combined_with_chunking(text, max_chunk_length)

        except Exception as e:
            logger.error(f"同时提取实体和关系失败: {e}")
            return {"entities": [], "relationships": []}
    
    def _build_prompt(self, text: str) -> str:
        """
        构建实体识别提示词 - 从模板文件动态读取
        
        Args:
            text: 要分析的文本
            
        Returns:
            str: 构建好的提示词
        """
        prompt_template_path = os.path.join(
            os.path.dirname(__file__),
            'prompt_template.md'
        )
        
        try:
            with open(prompt_template_path, 'r', encoding='utf-8') as f:
                template = f.read()
            prompt = template.replace('{text}', text)
            return prompt
        except FileNotFoundError:
            logger.error(f"提示词模板文件未找到: {prompt_template_path}")
            return f"请分析以下文本，并识别其中的实体：{text}"
    
    def _build_combined_prompt(self, text: str) -> str:
        """
        构建同时提取实体和关系的提示词 - 从模板文件动态读取
        
        Args:
            text: 要分析的文本
            
        Returns:
            str: 构建好的提示词
        """
        prompt_template_path = os.path.join(
            os.path.dirname(__file__),
            'prompt_combined_template.md'
        )
        
        try:
            with open(prompt_template_path, 'r', encoding='utf-8') as f:
                template = f.read()
            prompt = template.replace('{text}', text)
            return prompt
        except FileNotFoundError:
            logger.error(f"提示词模板文件未找到: {prompt_template_path}")
            return f"请分析以下文本，提取实体和关系：{text}"
    
    def _extract_combined_with_chunking(self, text: str, max_chunk_length: int = 50000) -> Dict[str, List[Dict[str, Any]]]:
        """
        使用分块方式同时提取实体和关系
        
        Args:
            text: 要分析的文本
            max_chunk_length: 单个文本块的最大长度
            
        Returns:
            Dict: 包含实体列表和关系列表的字典
        """
        try:
            total_length = len(text)
            num_chunks = (total_length + max_chunk_length - 1) // max_chunk_length
            logger.info(f"文本总长度: {total_length}，最大块长度: {max_chunk_length}，需要分割成 {num_chunks} 块")
            
            all_entities = []
            all_relationships = []
            
            for i in range(num_chunks):
                start_pos = i * max_chunk_length
                end_pos = min((i + 1) * max_chunk_length, total_length)
                chunk_text = text[start_pos:end_pos]
                
                logger.info(f"处理第 {i+1}/{num_chunks} 块，文本长度: {len(chunk_text)}，位置: {start_pos}-{end_pos}")
                
                prompt = self._build_combined_prompt(chunk_text)
                logger.info(f"第 {i+1} 块构建提示词长度: {len(prompt)}")
                
                system_prompt = "你是一个实体和关系提取专家，需要根据给定的文本，同时识别实体和提取实体之间的关系。"
                
                response_json = self.model_client.call_json(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=0,
                    max_tokens=8192
                )
                
                if response_json:
                    chunk_entities = self._get_entities(response_json)
                    chunk_relationships = self._get_relationships(response_json)
                    
                    logger.info(f"第 {i+1} 块提取到 {len(chunk_entities)} 个实体和 {len(chunk_relationships)} 个关系")
                    
                    # 调整实体的位置信息（加上偏移量）
                    for entity in chunk_entities:
                        if 'start_pos' in entity:
                            entity['start_pos'] += start_pos
                        if 'end_pos' in entity:
                            entity['end_pos'] += start_pos
                    
                    # 调整关系中的实体位置信息（加上偏移量）
                    for relationship in chunk_relationships:
                        if 'start_pos' in relationship:
                            relationship['start_pos'] += start_pos
                        if 'end_pos' in relationship:
                            relationship['end_pos'] += start_pos
                    
                    all_entities.extend(chunk_entities)
                    all_relationships.extend(chunk_relationships)
            
            # 去重实体（基于名称和类型）
            unique_entities = []
            seen_entity_keys = set()
            for entity in all_entities:
                entity_key = f"{entity.get('n')}_{entity.get('t')}"
                if entity_key not in seen_entity_keys:
                    seen_entity_keys.add(entity_key)
                    unique_entities.append(entity)
            
            logger.info(f"分块处理完成，共提取 {len(unique_entities)} 个实体和 {len(all_relationships)} 个关系（去重前: {len(all_entities)} 个实体）")
            
            return {"entities": unique_entities, "relationships": all_relationships}
            
        except Exception as e:
            logger.error(f"分块处理实体和关系提取失败: {e}")
            return {"entities": [], "relationships": []}

    @staticmethod
    def _get_entities(response_json: dict) -> list:
        """从响应中提取实体列表，兼容 entities/entity 两种 key"""
        return response_json.get('entities') or response_json.get('entity') or []

    @staticmethod
    def _get_relationships(response_json: dict) -> list:
        """从响应中提取关系列表，兼容 relationships/relations/relation 等多种 key"""
        return (response_json.get('relationships')
                or response_json.get('relations')
                or response_json.get('relation')
                or [])

    @staticmethod
    def _find_split_point(text: str, mid: int) -> int:
        """在 mid 附近查找句子边界作为切分点"""
        import re
        # 在 mid 前后 500 字符范围内找句子边界
        search_start = max(0, mid - 500)
        search_end = min(len(text), mid + 500)
        # 优先在 mid 之后找边界，不行再在之前找
        after = re.search(r'(?<=[。！？\n])', text[mid:search_end])
        if after:
            return mid + after.end()
        before = re.search(r'(?<=[。！？\n])', text[search_start:mid])
        if before:
            return search_start + before.end()
        return mid
