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
import time
import traceback
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import requests
from system.logger import logger
from utils.json_utils import extract_json as _extract_json_unified, fix_json


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
            type=config.get('model_type') or config.get('type', 'local'),
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
    
    def _with_retry(self, fn, label: str):
        """通用重试循环。fn() 应返回结果或在失败时抛出异常。"""
        last_error = None
        last_exception = None
        for attempt in range(self.config.max_retries):
            try:
                logger.info(f"[{label}] 尝试 {attempt + 1}/{self.config.max_retries}")
                return fn()
            except requests.exceptions.Timeout as e:
                last_error = f"请求超时: {e}"
                last_exception = e
            except requests.exceptions.RequestException as e:
                last_error = f"请求异常: {e}"
                last_exception = e
            except Exception as e:
                last_error = f"未知异常: {e}"
                last_exception = e
                logger.warning(f"[{label}] 异常堆栈: {traceback.format_exc()}")
            logger.warning(f"[{label}] 尝试 {attempt + 1} 失败: {last_error}")
            if attempt < self.config.max_retries - 1:
                time.sleep(self.config.retry_delay)
        logger.error(f"[{label}] {self.config.max_retries} 次尝试后失败: {last_error}")
        if last_exception:
            logger.error(f"[{label}] 异常详情: {repr(last_exception)}")
        return None

    def call_raw(self, prompt: str, system_prompt: str = "你是一个AI助手。",
                 temperature: float = 0, max_tokens: int = 8192) -> str:
        """调用模型并返回原始文本（不做 JSON 解析），供 pageindex 等模块使用。"""
        if self.config.type == "local":
            return self._call_local_model(prompt, "json", temperature, max_tokens)
        else:
            return self._call_cloud_model(prompt, system_prompt, "json_object", temperature, max_tokens)

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
        
        # 使用统一 JSON 提取入口
        result = _extract_json_unified(response_text)
        if result is not None:
            if isinstance(result, dict):
                entities = result.get('entities') or result.get('entity') or []
                relationships = result.get('relationships') or result.get('relations') or result.get('relation') or []
                if entities or relationships:
                    logger.info(f"JSON解析成功，实体: {len(entities)} 个，关系: {len(relationships)} 条")
            elif isinstance(result, list):
                logger.info(f"JSON解析成功，列表长度: {len(result)}")
        else:
            logger.warning(f"JSON提取失败，原始响应长度: {len(response_text)}")
            logger.info(f"原始响应前500字符: {response_text[:500]}")
        return result

    def _call_local_model(
        self,
        prompt: str,
        expected_format: str = "json",
        temperature: float = 0,
        max_tokens: int = 8192
    ) -> str:
        """调用本地模型API（Ollama）"""
        def _do_call():
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
            if response.status_code == 200:
                text = response.json().get('response', '')
                if text:
                    logger.info(f"本地模型响应成功，响应长度: {len(text)}")
                    return text
                raise ValueError("响应内容为空")
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")

        return self._with_retry(_do_call, "local/generate") or ""
    
    def _call_cloud_model(
        self,
        prompt: str,
        system_prompt: str,
        expected_format: str = "json_object",
        temperature: float = 0,
        max_tokens: int = 8192
    ) -> str:
        """调用云端模型API（OpenAI兼容）"""
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

        def _do_call():
            response = requests.post(
                f"{self.config.api_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json"
                },
                json=request_params,
                timeout=self.config.timeout
            )
            if response.status_code == 200:
                text = response.json()['choices'][0]['message']['content']
                if text:
                    logger.info(f"云端模型响应成功，响应长度: {len(text)}")
                    return text
                raise ValueError("响应内容为空")
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")

        return self._with_retry(_do_call, "cloud/chat") or ""
    
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

    def call_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        temperature: float = 0,
        max_tokens: int = 8192,
        tool_choice: str = "auto",
    ) -> Optional[Dict[str, Any]]:
        """
        调用模型并支持 tool calling（OpenAI 兼容格式）

        Args:
            messages: 对话消息列表，格式 [{"role": "...", "content": "..."}]
            tools: OpenAI 兼容的 tools 定义列表
            system_prompt: 系统提示词（如果 messages 中未包含 system 角色）
            temperature: 温度参数
            max_tokens: 最大生成 token 数
            tool_choice: "auto" | "none" | "required"

        Returns:
            {
                "content": str,        # 模型文本输出
                "tool_calls": [        # 工具调用列表
                    {
                        "id": str,
                        "type": "function",
                        "function": {"name": str, "arguments": str}
                    }
                ]
            }
            失败返回 None
        """
        if self.config.type == "local":
            return self._call_local_chat(messages, tools, system_prompt, temperature, max_tokens, tool_choice)
        else:
            return self._call_cloud_chat(messages, tools, system_prompt, temperature, max_tokens, tool_choice)

    def _call_local_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        temperature: float = 0,
        max_tokens: int = 8192,
        tool_choice: str = "auto",
    ) -> Optional[Dict[str, Any]]:
        """调用本地 Ollama /api/chat 端点（支持 tools）"""
        req_messages = list(messages)
        if system_prompt and (not req_messages or req_messages[0].get("role") != "system"):
            req_messages.insert(0, {"role": "system", "content": system_prompt})

        request_body = {
            "model": self.config.model_name,
            "messages": req_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            request_body["tools"] = tools
            request_body["tool_choice"] = tool_choice

        def _do_call():
            response = requests.post(
                f"{self.config.api_url}/api/chat",
                json=request_body,
                timeout=self.config.timeout,
            )
            if response.status_code == 200:
                msg = response.json().get("message", {})
                return {"content": msg.get("content", ""), "tool_calls": msg.get("tool_calls", [])}
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")

        return self._with_retry(_do_call, "local/chat")

    def _call_cloud_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        temperature: float = 0,
        max_tokens: int = 8192,
        tool_choice: str = "auto",
    ) -> Optional[Dict[str, Any]]:
        """调用云端 /chat/completions 端点（原生支持 tools）"""
        full_messages: List[Dict[str, Any]] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        request_params = {
            "model": self.config.model_name,
            "messages": full_messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            request_params["tools"] = tools
            request_params["tool_choice"] = tool_choice

        def _do_call():
            response = requests.post(
                f"{self.config.api_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_params,
                timeout=self.config.timeout,
            )
            if response.status_code == 200:
                msg = response.json()["choices"][0].get("message", {})
                return {"content": msg.get("content", ""), "tool_calls": msg.get("tool_calls", [])}
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")

        return self._with_retry(_do_call, "cloud/chat")


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
