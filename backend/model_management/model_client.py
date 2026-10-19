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

import glob
import json
import os
import shutil
import subprocess
import time
import traceback
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import requests
from system.logger import logger
from utils.json_utils import extract_json as _extract_json_unified, fix_json


class _EmbedEndpointMissing(Exception):
    """Ollama 旧版本无 /api/embed 端点，触发降级"""
    pass


def _resolve_opencode_cli() -> str:
    """定位本机 opencode CLI。

    优先级：环境变量 OPENCODE_CLI → PATH（opencode-cli / opencode）
    → OpenCode Desktop 内置 CLI（Windows 下 %APPDATA%\\ai.opencode.desktop\\cli\\*）。
    """
    explicit = os.environ.get('OPENCODE_CLI')
    if explicit and os.path.exists(explicit):
        return explicit
    for name in ("opencode-cli", "opencode"):
        found = shutil.which(name)
        if found:
            return found
    candidates = glob.glob(os.path.join(
        os.environ.get('APPDATA', ''), 'ai.opencode.desktop', 'cli', '*', 'opencode-cli.exe'
    ))
    if candidates:
        return sorted(candidates)[-1]
    raise RuntimeError(
        "未找到 opencode CLI：请将 CLI 加入 PATH，或设置环境变量 OPENCODE_CLI 指向可执行文件"
    )


def _ensure_opencode_workdir() -> str:
    """确保 opencode run 的工作目录存在，并写入工具拒绝配置（仅首次）。"""
    workdir = os.environ.get('OPENCODE_CLI_WORKDIR')
    if not workdir:
        workdir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'data', 'opencode_bridge_ws'
        )
    os.makedirs(workdir, exist_ok=True)
    config_path = os.path.join(workdir, 'opencode.json')
    if not os.path.exists(config_path):
        config = {
            "$schema": "https://opencode.ai/config.json",
            "permissions": [
                {"action": "shell", "resource": "*", "effect": "deny"},
                {"action": "edit", "resource": "*", "effect": "deny"},
                {"action": "webfetch", "resource": "*", "effect": "deny"},
                {"action": "websearch", "resource": "*", "effect": "deny"},
                {"action": "subagent", "resource": "*", "effect": "deny"}
            ]
        }
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[opencode] 写入工作目录 opencode.json 失败: {e}")
    return workdir


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
    embedding_model: Optional[str] = None

    def __post_init__(self):
        """初始化后处理，设置默认模型名称"""
        if not self.model_name and self.models:
            self.model_name = self.models[0]
        if not self.embedding_model:
            self.embedding_model = os.environ.get('EMBED_MODEL', 'bge-m3')
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> 'ModelConfig':
        """
        从字典创建ModelConfig实例

        Args:
            config: 配置字典

        Returns:
            ModelConfig实例
        """
        model_type = config.get('model_type') or config.get('type', 'local')
        return cls(
            type=model_type,
            models=config.get('models', None) or (
                ['opencode/glm-5.3-flash-free'] if model_type == 'opencode' else ['qwen2.5:7b']
            ),
            api_url=config.get('api_url', 'http://localhost:11434'),
            api_key=config.get('api_key', ''),
            priority=config.get('priority', 'local'),
            model_name=config.get('model_name'),
            max_retries=config.get('max_retries', 3),
            retry_delay=config.get('retry_delay', 1.0),
            timeout=config.get('timeout', 600),
            embedding_model=config.get('embedding_model')
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
        """调用模型并返回原始文本（不做 JSON 解析），供 content_summarization 等模块使用。"""
        if self.config.type == "local":
            return self._call_local_model(prompt, "json", temperature, max_tokens)
        elif self.config.type == "opencode":
            return self._call_opencode_cli(prompt, system_prompt)
        else:
            return self._call_cloud_model(prompt, system_prompt, "json_object", temperature, max_tokens)

    def call_text(self, prompt: str, system_prompt: str = "你是一个专业的文档写作助手。",
                  temperature: float = 0.3, max_tokens: int = 8192) -> str:
        """调用模型返回纯文本（Markdown 等长文），供 Wiki 页面生成等模块使用。"""
        if self.config.type == "local":
            return self._call_local_model(prompt, "text", temperature, max_tokens)
        elif self.config.type == "opencode":
            return self._call_opencode_cli(prompt, system_prompt)
        else:
            return self._call_cloud_model(prompt, system_prompt, "text", temperature, max_tokens)

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
        # opencode CLI：prompt 自带指令，不做服务端格式约束
        expected_format = "json_object" if self.config.type == "cloud" else "json"

        # 调用底层模型API
        if self.config.type == "local":
            response_text = self._call_local_model(prompt, expected_format, temperature, max_tokens)
        elif self.config.type == "opencode":
            response_text = self._call_opencode_cli(prompt, system_prompt or "你是一个AI助手。")
        else:
            response_text = self._call_cloud_model(prompt, system_prompt or "你是一个AI助手。", expected_format, temperature, max_tokens)
        
        if not response_text:
            return None
        
        # 使用统一 JSON 提取入口
        result = _extract_json_unified(response_text)
        if result is not None:
            logger.info(f"JSON解析成功，类型: {type(result).__name__}")
        else:
            logger.warning(f"JSON提取失败，原始响应长度: {len(response_text)}")
            logger.info(f"原始响应前500字符: {response_text[:500]}")
        return result

    def _call_opencode_cli(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """调用本机 OpenCode CLI（opencode run），用于 'opencode' 类型模型。

        - 模型 ID 来自 model_name（如 opencode/glm-5.3-flash-free）
        - 工作目录默认 backend/data/opencode_bridge_ws，目录内 opencode.json
          拒绝 shell/edit/webfetch/websearch/subagent 等工具，保证纯文本生成
        - 子进程解析 --format json 事件流，聚合 type=text 的正文

        注意：Windows 命令行长度上限约 32K 字符，超长 prompt 会调用失败。
        """
        def _do_call():
            cli = _resolve_opencode_cli()
            model = self.config.model_name or (
                self.config.models[0] if self.config.models else None
            )
            if not model:
                raise ValueError("opencode 类型模型缺少模型 ID（models 为空）")

            workdir = _ensure_opencode_workdir()
            if system_prompt:
                text_prompt = f"{system_prompt}\n\n{prompt}"
            else:
                text_prompt = prompt

            try:
                result = subprocess.run(
                    [cli, "run", "--format", "json", "--agent", "plan", "--model", model, text_prompt],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=max(self.config.timeout, 300),
                    cwd=workdir,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"opencode run 超时（>{max(self.config.timeout, 300)}s）: {e}")

            if not result.stdout:
                stderr_tail = (result.stderr or "").strip()[-300:]
                raise RuntimeError(f"opencode run 无输出 (exit={result.returncode}): {stderr_tail}")

            texts: List[str] = []
            errors: List[str] = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type == "text":
                    text = (event.get("part") or {}).get("text") or ""
                    if text:
                        texts.append(text)
                elif event_type == "error":
                    err = event.get("error") or {}
                    errors.append(err.get("message") or "opencode 运行失败")

            if not texts and errors:
                raise RuntimeError(f"opencode 运行失败: {'; '.join(errors[:3])}")
            if not texts:
                raise ValueError("opencode 响应内容为空")

            logger.info(f"opencode CLI 响应成功，响应长度: {len(''.join(texts))}")
            return "".join(texts)

        return self._with_retry(_do_call, "opencode/run") or ""

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
            elif self.config.type == "opencode":
                response = self._call_opencode_cli("Reply with a single word: ok", "你是一个AI助手。")
            else:
                # 使用较高的 max_tokens (100) 以支持带 reasoning 的模型（如 DeepSeek V4）
                response = self._call_cloud_model("Hello", "你是一个AI助手。", "text", 0, 100)
            return bool(response)
        except Exception as e:
            logger.error(f"测试连接失败: {e}")
            return False

    def embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        """批量计算文本向量（embedding 模型）。失败返回 None，调用方需优雅降级。"""
        if not texts:
            return []
        if self.config.type == "opencode":
            # CLI 调用方式无 embedding 端点，直接降级
            return None
        model = self.config.embedding_model
        if not model:
            return None
        if self.config.type == "local":
            return self._embed_local(model, texts)
        return self._embed_cloud(model, texts)

    def _embed_local(self, model: str, texts: List[str]) -> Optional[List[List[float]]]:
        """Ollama embedding：优先新版 /api/embed，404 时降级旧版 /api/embeddings"""
        def _do_embed():
            response = requests.post(
                f"{self.config.api_url}/api/embed",
                json={"model": model, "input": texts},
                timeout=self.config.timeout,
            )
            if response.status_code == 404:
                raise _EmbedEndpointMissing()
            if response.status_code == 200:
                embeddings = response.json().get("embeddings")
                if embeddings:
                    return embeddings
                raise ValueError("embedding 响应为空")
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")

        try:
            return _do_embed()
        except _EmbedEndpointMissing:
            pass
        except Exception as e:
            logger.warning(f"[embed] /api/embed 失败: {e}")
            return None

        def _do_legacy():
            vectors = []
            for text in texts:
                response = requests.post(
                    f"{self.config.api_url}/api/embeddings",
                    json={"model": model, "prompt": text},
                    timeout=self.config.timeout,
                )
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
                vectors.append(response.json().get("embedding", []))
            return vectors

        return self._with_retry(_do_legacy, "embed/legacy")

    def _embed_cloud(self, model: str, texts: List[str]) -> Optional[List[List[float]]]:
        """OpenAI 兼容 /embeddings 端点"""
        def _do_call():
            response = requests.post(
                f"{self.config.api_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "input": texts},
                timeout=self.config.timeout,
            )
            if response.status_code == 200:
                items = sorted(response.json().get("data", []), key=lambda d: d.get("index", 0))
                return [item.get("embedding", []) for item in items]
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")

        return self._with_retry(_do_call, "embed/cloud")

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
        elif self.config.type == "opencode":
            return self._call_opencode_chat(messages, system_prompt)
        else:
            return self._call_cloud_chat(messages, tools, system_prompt, temperature, max_tokens, tool_choice)

    def _call_opencode_chat(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """opencode 类型不支持 tool calling 协商：把消息序列化为文本 prompt，
        返回纯文本回复（tool_calls 恒为空）。决策引擎收到空 tool_calls 时会
        把 content 当作最终回答，循环可正常收敛。"""
        blocks: List[str] = []

        def _append(role: str, content: Any) -> None:
            if isinstance(content, list):
                content = "\n".join(
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in content
                )
            if content:
                blocks.append(f"{role}: {content}")

        if system_prompt:
            blocks.append(f"system: {system_prompt}")
        for msg in messages:
            _append(msg.get("role", "user"), msg.get("content"))
        blocks.append("assistant:")
        prompt = "\n\n".join(blocks)

        text = self._call_opencode_cli(prompt)
        return {"content": text, "tool_calls": []}

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


# ModelClient 全局工厂：版本化缓存单例 —— 配置（类型/模型名/地址/密钥）变化即重建，
# 未变化则复用。解决「改模型配置何时生效」无 locality 的问题：所有调用点一处刷新。
_client_cache: Optional[ModelClient] = None
_client_cache_sig: tuple = ()


def get_model_client() -> Optional[ModelClient]:
    """从可用模型配置获取缓存的 ModelClient（配置版本变化即重建）。"""
    global _client_cache, _client_cache_sig
    from config.database import SessionLocal
    from model_management.model_service import ModelService
    db = None
    try:
        db = SessionLocal()
        config = ModelService.get_available_model(db)
        if not config:
            return None
        sig = (config.get('type'), config.get('model_name'), tuple(config.get('models') or []),
               config.get('api_url'), config.get('api_key'))
        if _client_cache is not None and _client_cache_sig == sig:
            return _client_cache
        _client_cache = ModelClient(config)
        _client_cache_sig = sig
        return _client_cache
    except Exception:
        # DB 抖动等临时故障时返回当前缓存实例，避免调用方拿到 None 中断任务
        return _client_cache
    finally:
        if db:
            db.close()
