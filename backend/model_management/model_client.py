"""
模型调用客户端

提供统一的模型调用接口，支持本地模型（Ollama）和云端模型（OpenAI兼容API）。
支持重试机制、超时控制、JSON格式修复等功能。

主要方法:
    - call_json(): 调用模型并返回JSON格式响应
    - test_connection(): 测试模型连接是否正常

使用示例:
    config = ModelConfig(type='local', api_url='http://localhost:11434')
    client = ModelClient(config)
    
    # 调用模型并获取JSON响应
    result = client.call_json("请提取实体...")
    
    # 测试连接
    is_connected = client.test_connection()
"""

import json
import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import requests
from system.logger import logger


@dataclass
class ModelConfig:
    """
    模型配置数据类
    
    用于封装模型配置信息，便于在模块间传递。
    
    Attributes:
        type: 模型类型，'local' 或 'cloud'
        models: 支持的模型列表
        api_url: API地址
        api_key: API密钥
        priority: 优先级
        model_name: 当前使用的模型名称（默认取models列表第一个）
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）
        timeout: 请求超时时间（秒）
    """
    type: str = 'local'
    models: List[str] = field(default_factory=lambda: ['qwen2.5:7b'])
    api_url: str = 'http://localhost:11434'
    api_key: str = ''
    priority: str = 'local'
    model_name: Optional[str] = None
    max_retries: int = 3
    retry_delay: float = 1.0
    timeout: int = 600
    
    def __post_init__(self):
        """初始化后处理，设置默认模型名称"""
        if not self.model_name and self.models:
            self.model_name = self.models[0]
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> 'ModelConfig':
        """
        从字典创建ModelConfig实例
        
        Args:
            config: 配置字典
            
        Returns:
            ModelConfig实例
        """
        return cls(
            type=config.get('type', 'local'),
            models=config.get('models', ['qwen2.5:7b']),
            api_url=config.get('api_url', 'http://localhost:11434'),
            api_key=config.get('api_key', ''),
            priority=config.get('priority', 'local'),
            model_name=config.get('model_name'),
            max_retries=config.get('max_retries', 3),
            retry_delay=config.get('retry_delay', 1.0),
            timeout=config.get('timeout', 600)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典
        
        Returns:
            Dict: 配置字典
        """
        return {
            'type': self.type,
            'models': self.models,
            'api_url': self.api_url,
            'api_key': self.api_key,
            'priority': self.priority,
            'model_name': self.model_name,
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay,
            'timeout': self.timeout
        }


def _iter_json_aware(text: str):
    """遍历JSON字符串，产出 (index, char, in_str)，正确处理转义和字符串边界。

    in_str 为处理完当前字符后的字符串状态（True=在字符串内部）。
    """
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            yield i, ch, in_str
            continue
        if ch == '\\' and in_str:
            escape = True
            yield i, ch, in_str
            continue
        if ch == '"':
            in_str = not in_str
        yield i, ch, in_str


def _extract_json_body(text: str) -> Optional[str]:
    """从文本中提取JSON体：移除markdown代码围栏等前缀，定位到第一个 { 或 [。"""
    cleaned = text.strip()

    if cleaned.startswith('```'):
        first_nl = cleaned.find('\n')
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1:]
        else:
            cleaned = cleaned[3:]
        cleaned = cleaned.strip()

    if cleaned.endswith('```'):
        cleaned = cleaned[:-3].strip()

    first_brace = cleaned.find('{')
    first_bracket = cleaned.find('[')
    positions = [p for p in (first_brace, first_bracket) if p != -1]
    if not positions:
        return None
    return cleaned[min(positions):]


def _close_brackets(text: str) -> str:
    """在text末尾补全缺失的闭合括号（JSON-aware，跳过字符串内部）。"""
    stack: List[str] = []
    for _, ch, in_str in _iter_json_aware(text):
        if in_str:
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch == '}':
            if stack and stack[-1] == '{':
                stack.pop()
        elif ch == ']':
            if stack and stack[-1] == '[':
                stack.pop()

    result = text.rstrip(', \t\n\r')
    for ch in reversed(stack):
        result += '}' if ch == '{' else ']'
    return result


def _extract_array_objects(text: str, array_start: int) -> List[str]:
    """从JSON数组起始位置提取所有完整的扁平对象。"""
    objects: List[str] = []
    if array_start >= len(text) or text[array_start] != '[':
        return objects

    i = array_start + 1
    while i < len(text):
        while i < len(text) and (text[i].isspace() or text[i] == ','):
            i += 1
        if i >= len(text) or text[i] == ']':
            break
        if text[i] != '{':
            i += 1
            continue

        depth = 0
        for pos, ch, in_str in _iter_json_aware(text[i:]):
            actual_pos = i + pos
            if in_str:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    objects.append(text[i:actual_pos + 1])
                    i = actual_pos + 1
                    break
        else:
            break

    return objects


def _repair_entity_relationship(text: str) -> Optional[str]:
    """针对实体/关系JSON格式的修复：提取完整对象后重建JSON。"""
    entities_match = re.search(r'"entities"\s*:\s*(\[)', text)
    rel_match = re.search(r'"relationships"\s*:\s*(\[)', text)

    entities_objects: List[str] = []
    rel_objects: List[str] = []

    if entities_match:
        entities_objects = _extract_array_objects(text, entities_match.start(1))
    if rel_match:
        rel_objects = _extract_array_objects(text, rel_match.start(1))

    result = '{"entities": [' + ','.join(entities_objects) + '], "relationships": [' + ','.join(rel_objects) + ']}'

    try:
        json.loads(result)
        return result
    except json.JSONDecodeError:
        return None


def _repair_by_closing(text: str) -> Optional[str]:
    """通用修复：补全缺失括号，必要时从后向前截断不完整内容。"""
    result = _close_brackets(text.rstrip(', \t\n\r'))
    try:
        json.loads(result)
        return result
    except json.JSONDecodeError:
        pass

    n = len(text)
    in_str_at = [False] * (n + 1)
    for pos, _, in_str in _iter_json_aware(text):
        in_str_at[pos + 1] = in_str

    for end in range(n, 0, -1):
        if in_str_at[end]:
            continue
        candidate = text[:end].rstrip(', \t\n\r')
        if not candidate:
            continue
        result = _close_brackets(candidate)
        try:
            json.loads(result)
            return result
        except json.JSONDecodeError:
            continue

    return None


def fix_json(json_str: str) -> Optional[str]:
    """修复JSON尾部被截断导致的不完整问题。

    优先尝试针对实体/关系JSON格式的精准修复，失败后回退到通用括号闭合修复。
    """
    if not json_str or not json_str.strip():
        return None

    cleaned = json_str.strip()

    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    body = _extract_json_body(cleaned)
    if not body:
        return None

    result = _repair_entity_relationship(body)
    if result:
        return result

    result = _repair_by_closing(body)
    if result:
        return result

    return None


class ModelClient:
    """
    模型调用客户端
    
    提供统一的模型调用接口，支持本地模型（Ollama）和云端模型（OpenAI兼容API）。
    
    Features:
        - 支持本地模型（Ollama）和云端模型（OpenAI兼容API）
        - 自动重试机制
        - JSON格式修复
        - 超时控制
        - 详细的日志记录
    
    使用示例:
        config = ModelConfig(type='local', api_url='http://localhost:11434')
        client = ModelClient(config)
        response = client.call("请分析这段文本...")
    """
    
    def __init__(self, config: Any = None):
        """
        初始化模型客户端
        
        Args:
            config: 模型配置，可以是ModelConfig实例、字典或None
                   如果为None，使用默认配置
        """
        if config is None:
            self.config = ModelConfig()
        elif isinstance(config, ModelConfig):
            self.config = config
        elif isinstance(config, dict):
            self.config = ModelConfig.from_dict(config)
        else:
            # 尝试从对象属性获取配置
            self.config = ModelConfig(
                type=getattr(config, 'type', 'local'),
                models=getattr(config, 'models', ['qwen2.5:7b']),
                api_url=getattr(config, 'api_url', 'http://localhost:11434'),
                api_key=getattr(config, 'api_key', ''),
                priority=getattr(config, 'priority', 'local')
            )
    
    def call_json(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: float = 0,
        max_tokens: int = 8192
    ) -> Optional[Dict[str, Any]]:
        """
        调用模型并返回JSON格式的响应
        
        根据配置的模型类型自动选择本地模型或云端模型进行调用。
        自动处理JSON解析和格式修复。
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词（仅云端模型使用）
            temperature: 温度参数
            max_tokens: 最大生成token数
            
        Returns:
            Dict: 解析后的JSON对象，解析失败返回None
        """
        # 根据模型类型选择正确的格式参数
        # 本地模型（Ollama）使用 "json"
        # 云端模型（OpenAI兼容）使用 "json_object"
        expected_format = "json_object" if self.config.type == "cloud" else "json"
        
        # 调用底层模型API
        if self.config.type == "local":
            response_text = self._call_local_model(prompt, expected_format, temperature, max_tokens)
        else:
            response_text = self._call_cloud_model(prompt, system_prompt or "你是一个AI助手。", expected_format, temperature, max_tokens)
        
        if not response_text:
            return None
        
        # 清洗常见非JSON包裹：BOM、markdown 代码围栏
        cleaned = response_text.strip().lstrip('﻿')
        if cleaned.startswith('```'):
            first_nl = cleaned.find('\n')
            if first_nl != -1:
                cleaned = cleaned[first_nl + 1:]
            if cleaned.endswith('```'):
                cleaned = cleaned[:-3].rstrip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON解析失败: {e}")
            logger.info(f"原始响应: {response_text}")
            fixed_json = fix_json(cleaned)
            if fixed_json:
                try:
                    result = json.loads(fixed_json)
                    if isinstance(result, dict):
                        entities = result.get('entities') or result.get('entity') or []
                        relationships = result.get('relationships') or result.get('relations') or result.get('relation') or []
                        logger.info(f"JSON修复成功，原始长度: {len(response_text)}，修复后长度: {len(fixed_json)}，"
                                    f"实体: {len(entities)} 个，关系: {len(relationships)} 条")
                    elif isinstance(result, list):
                        logger.info(f"JSON修复成功，原始长度: {len(response_text)}，修复后长度: {len(fixed_json)}，"
                                    f"实体: {len(result)} 个")
                    else:
                        logger.info(f"JSON修复成功，原始长度: {len(response_text)}，修复后长度: {len(fixed_json)}")
                    return result
                except json.JSONDecodeError as e2:
                    logger.error(f"修复后仍解析失败: {e2}")
                    logger.info(f"修复后全文: {fixed_json}")
                    return None
            logger.warning(f"修复失败，原始响应长度: {len(response_text)}")
            return None
    
    def _call_local_model(
        self, 
        prompt: str, 
        expected_format: str = "json",
        temperature: float = 0,
        max_tokens: int = 8192
    ) -> str:
        """
        调用本地模型API（Ollama）
        
        Args:
            prompt: 用户提示词
            expected_format: 期望的响应格式
            temperature: 温度参数
            max_tokens: 最大生成token数
            
        Returns:
            str: 模型响应文本
        """
        last_error = None
        last_exception = None
        
        for attempt in range(self.config.max_retries):
            try:
                logger.info(f"调用本地模型API，模型: {self.config.model_name}, API: {self.config.api_url} (尝试 {attempt + 1}/{self.config.max_retries})")
                
                response = requests.post(
                    f"{self.config.api_url}/api/generate",
                    json={
                        "model": self.config.model_name,
                        "prompt": prompt,
                        "format": expected_format,
                        "stream": False,
                        "max_tokens": max_tokens,
                        "temperature": temperature
                    },
                    timeout=self.config.timeout
                )
                
                logger.info(f"本地模型API响应状态码: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    response_text = result.get('response', '')
                    if response_text:
                        logger.info(f"本地模型响应成功，响应长度: {len(response_text)}")
                        return response_text
                    else:
                        logger.warning(f"响应内容为空，输入prompt长度: {len(prompt)}，末尾内容: {prompt[-2000:]}")
                        logger.warning(f"跳过重试（模型已正常处理，判定无实体可提取）")
                        return ""
                else:
                    error_msg = f"API调用失败，状态码: {response.status_code}, 响应: {response.text}"
                    logger.warning(f"第 {attempt + 1} 次尝试：{error_msg}")
                    last_error = error_msg
                    
            except requests.exceptions.Timeout as e:
                error_msg = f"请求超时: {str(e)}"
                logger.warning(f"第 {attempt + 1} 次尝试：{error_msg}")
                last_error = error_msg
                last_exception = e
            except requests.exceptions.RequestException as e:
                error_msg = f"请求异常: {str(e)}"
                logger.warning(f"第 {attempt + 1} 次尝试：{error_msg}")
                last_error = error_msg
                last_exception = e
            except Exception as e:
                error_msg = f"未知异常: {str(e)}"
                logger.warning(f"第 {attempt + 1} 次尝试：{error_msg}")
                logger.warning(f"异常堆栈: {traceback.format_exc()}")
                last_error = error_msg
                last_exception = e
            
            if attempt < self.config.max_retries - 1:
                logger.info(f"等待 {self.config.retry_delay} 秒后重试...")
                time.sleep(self.config.retry_delay)
        
        logger.error(f"本地模型API调用在 {self.config.max_retries} 次尝试后仍然失败")
        logger.error(f"最后错误: {last_error}")
        if last_exception:
            logger.error(f"异常详情: {repr(last_exception)}")
        return ""
    
    def _call_cloud_model(
        self, 
        prompt: str, 
        system_prompt: str,
        expected_format: str = "json_object",
        temperature: float = 0,
        max_tokens: int = 8192
    ) -> str:
        """
        调用云端模型API（OpenAI兼容）
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            expected_format: 期望的响应格式
            temperature: 温度参数
            max_tokens: 最大生成token数
            
        Returns:
            str: 模型响应文本
        """
        last_error = None
        last_exception = None
        
        # 构建请求参数
        request_params = {
            "model": self.config.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        # DeepSeek 等 API 的 json_object 模式在复杂提取任务中
        # 可能导致空响应。prompt 已明确要求输出纯 JSON，无需 API 层约束。
        # 注释掉 response_format 约束，让模型按 prompt 指令自然输出 JSON。
        # if expected_format == "json_object":
        #     combined = (prompt or "") + " " + (system_prompt or "")
        #     if "json" in combined.lower():
        #         request_params["response_format"] = {"type": "json_object"}

        for attempt in range(self.config.max_retries):
            try:
                api_url = f"{self.config.api_url}/chat/completions"
                logger.info(f"调用云端模型API，模型: {self.config.model_name}, API: {api_url} (尝试 {attempt + 1}/{self.config.max_retries})")

                response = requests.post(
                    api_url,
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=request_params,
                    timeout=self.config.timeout
                )
                
                logger.info(f"云端模型API响应状态码: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    response_content = result['choices'][0]['message']['content']
                    if response_content:
                        logger.info(f"云端模型响应成功，响应长度: {len(response_content)}")
                        return response_content
                    else:
                        logger.warning(f"响应内容为空，输入prompt长度: {len(prompt)}，末尾内容: {prompt[-2000:]}")
                        logger.warning(f"跳过重试（模型已正常处理，判定无实体可提取）")
                        return ""
                else:
                    error_msg = f"API调用失败，状态码: {response.status_code}, 响应: {response.text}"
                    logger.warning(f"第 {attempt + 1} 次尝试：{error_msg}")
                    last_error = error_msg
                    
            except requests.exceptions.Timeout as e:
                error_msg = f"请求超时: {str(e)}"
                logger.warning(f"第 {attempt + 1} 次尝试：{error_msg}")
                last_error = error_msg
                last_exception = e
            except requests.exceptions.RequestException as e:
                error_msg = f"请求异常: {str(e)}"
                logger.warning(f"第 {attempt + 1} 次尝试：{error_msg}")
                last_error = error_msg
                last_exception = e
            except Exception as e:
                error_msg = f"未知异常: {str(e)}"
                logger.warning(f"第 {attempt + 1} 次尝试：{error_msg}")
                logger.warning(f"异常堆栈: {traceback.format_exc()}")
                last_error = error_msg
                last_exception = e
            
            if attempt < self.config.max_retries - 1:
                logger.info(f"等待 {self.config.retry_delay} 秒后重试...")
                time.sleep(self.config.retry_delay)
        
        logger.error(f"云端模型API调用在 {self.config.max_retries} 次尝试后仍然失败")
        logger.error(f"最后错误: {last_error}")
        if last_exception:
            logger.error(f"异常详情: {repr(last_exception)}")
        return ""
    
    def test_connection(self) -> bool:
        """
        测试模型连接是否正常

        Returns:
            bool: 连接正常返回True，否则返回False
        """
        try:
            # 直接调用底层模型API进行连接测试
            if self.config.type == "local":
                response = self._call_local_model("Hello", "text", 0, 10)
            else:
                # 使用较高的 max_tokens (100) 以支持带 reasoning 的模型（如 DeepSeek V4）
                response = self._call_cloud_model("Hello", "你是一个AI助手。", "text", 0, 100)
            return bool(response)
        except Exception as e:
            logger.error(f"测试连接失败: {e}")
            return False


# 创建默认客户端实例
default_client = ModelClient()


def get_model_client() -> Optional[ModelClient]:
    """Create a fresh ModelClient from the available model config."""
    from config.database import SessionLocal
    from model_management.model_service import ModelService
    db = None
    try:
        db = SessionLocal()
        config = ModelService.get_available_model(db)
        if config:
            return ModelClient(config)
    except Exception:
        return None
    finally:
        if db:
            db.close()
    return None
