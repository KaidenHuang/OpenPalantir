"""
模型调用客户端

提供统一的模型调用接口，支持本地模型（Ollama）和云端模型（OpenAI兼容API），
带重试、超时与 JSON 格式修复。

主要方法:
    - call_json(): 调用模型并返回JSON格式响应
    - call_json_ex(): 同上，额外返回「输出是否被 max_tokens 截断」
    - call_text(): 调用模型并返回纯文本
    - test_connection(): 测试模型连接是否正常
"""

import os
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
import requests
from system.logger import logger
from utils.json_utils import extract_json as _extract_json_unified


class _EmbedEndpointMissing(Exception):
    """Ollama 旧版本无 /api/embed 端点，触发降级"""
    pass


@dataclass
class LlmReply:
    """一次调用的结果：正文 + 是否被 max_tokens 掐断 + 已生成 token 数

    截断标志只能随返回值走：get_model_client() 是跨线程共享的缓存单例，摘要与
    批量抽取又用 asyncio.gather 并发，记在实例属性上会串台。
    """
    text: str = ""
    truncated: bool = False
    generated_tokens: int = 0


# 探测不到服务端窗口时的兜底值（token）：够单节点正文一次调用，又不至于让本地模型爆显存
DEFAULT_CONTEXT_LENGTH = 32768


@dataclass
class ModelConfig:
    """模型配置：type 为 'local'（Ollama）或 'cloud'（OpenAI 兼容 API）。

    context_length 是服务端上下文窗口（token），探测不到用 DEFAULT_CONTEXT_LENGTH；
    timeout 单位为秒，retry_delay 单位为秒。
    """
    type: str = 'local'
    models: List[str] = field(default_factory=lambda: ['qwen2.5:7b'])
    api_url: str = 'http://localhost:11434'
    api_key: str = ''
    model_name: Optional[str] = None
    context_length: int = DEFAULT_CONTEXT_LENGTH
    max_retries: int = 3
    retry_delay: float = 1.0
    timeout: int = 600
    embedding_model: Optional[str] = None

    def __post_init__(self):
        if not self.model_name and self.models:
            self.model_name = self.models[0]
        if not self.embedding_model:
            self.embedding_model = os.environ.get('EMBED_MODEL', 'bge-m3')

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> 'ModelConfig':
        """由内部配置字典创建（键名 `type`；库记录的 `model_type` 在出口处已映射）"""
        return cls(
            type=config.get('type', 'local'),
            models=config.get('models') or ['qwen2.5:7b'],
            api_url=config.get('api_url', 'http://localhost:11434'),
            api_key=config.get('api_key', ''),
            model_name=config.get('model_name'),
            context_length=int(config.get('context_length') or DEFAULT_CONTEXT_LENGTH),
            max_retries=config.get('max_retries', 3),
            retry_delay=config.get('retry_delay', 1.0),
            timeout=config.get('timeout', 600),
            embedding_model=config.get('embedding_model')
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为配置字典"""
        return {
            'type': self.type,
            'models': self.models,
            'api_url': self.api_url,
            'api_key': self.api_key,
            'model_name': self.model_name,
            'context_length': self.context_length,
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay,
            'timeout': self.timeout
        }


class ModelClient:
    """统一模型调用客户端（本地 Ollama / 云端 OpenAI 兼容），带重试、超时与 JSON 修复。"""
    
    def __init__(self, config: Optional[Union[ModelConfig, Dict[str, Any]]] = None):
        """
        初始化模型客户端
        
        Args:
            config: 模型配置，ModelConfig 实例、字典或 None（使用默认配置）
        """
        if config is None:
            config = ModelConfig()
        elif isinstance(config, dict):
            config = ModelConfig.from_dict(config)
        self.config = config
    
    def _with_retry(self, fn, label: str):
        """通用重试循环。fn() 应返回结果或在失败时抛出异常；次数耗尽返回 None。"""
        for attempt in range(self.config.max_retries):
            try:
                logger.info(f"[{label}] 尝试 {attempt + 1}/{self.config.max_retries}")
                return fn()
            except requests.exceptions.RequestException as e:
                logger.warning(f"[{label}] 尝试 {attempt + 1} 失败: 请求异常: {e}")
            except Exception as e:
                logger.warning(f"[{label}] 尝试 {attempt + 1} 失败: 未知异常: {e} "
                               f"| 堆栈: {traceback.format_exc()}")
            if attempt < self.config.max_retries - 1:
                time.sleep(self.config.retry_delay)
        logger.error(f"[{label}] {self.config.max_retries} 次尝试后失败")
        return None

    def _warn_if_truncated(self, reply: LlmReply, max_tokens: int, label: str) -> None:
        """截断留痕：内容看起来完整，实则是半截结果，只进日志不回调用方等于没告警"""
        if reply.truncated:
            logger.warning(f"[{label}] 输出达到 max_tokens={max_tokens} 被截断"
                           f"（已生成 {reply.generated_tokens} token），结果可能不完整")

    def call_text(self, prompt: str, system_prompt: str = "你是一个专业的文档写作助手。",
                  temperature: float = 0.3, max_tokens: int = 8192) -> str:
        """调用模型返回纯文本（Markdown 等长文），供 Wiki 页面生成等模块使用。

        本地模型走 format="text"：调用方要的是白话（摘要、Wiki 正文），套上 JSON 约束
        会把引号和花括号一起写进库里。
        """
        reply = self._dispatch(prompt, system_prompt, "text", temperature, max_tokens)
        self._warn_if_truncated(reply, max_tokens, "text")
        return reply.text

    def call_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0,
        max_tokens: int = 8192
    ) -> Optional[Dict[str, Any]]:
        """调用模型并返回 JSON 解析结果；解析失败返回 None。

        只关心「有没有结果」时用这个；要分清额度不够与模型吐垃圾，用 call_json_ex。
        """
        return self.call_json_ex(prompt, system_prompt, temperature, max_tokens)[0]

    def call_json_ex(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0,
        max_tokens: int = 8192
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        """(解析结果, 输出是否被截断)

        两个信号必须分开：截断说明加额度重发有用，解析失败而没截断说明模型吐的是
        不合格式的文本，加额度没用——调用方据此才能决定「砍半重发」还是「按无标注降级」。

        云端不做服务端格式约束（response_format 各家支持度不一，OpenAI 还要求消息里
        出现 "json" 字样），JSON 一律靠 prompt 约束 + 统一提取修复；本地的 format 有效。
        """
        reply = self._dispatch(prompt, system_prompt or "你是一个AI助手。", "json",
                               temperature, max_tokens)
        self._warn_if_truncated(reply, max_tokens, "json")

        if not reply.text:
            return None, reply.truncated

        result = _extract_json_unified(reply.text)
        if result is not None:
            logger.info(f"JSON解析成功，类型: {type(result).__name__}")
        else:
            logger.warning(f"JSON提取失败，原始响应长度: {len(reply.text)}"
                           + ("（输出被 max_tokens 截断）" if reply.truncated else ""))
            logger.info(f"原始响应前500字符: {reply.text[:500]}")
        return result, reply.truncated

    def _dispatch(self, prompt: str, system_prompt: str, expected_format: str,
                  temperature: float, max_tokens: int) -> LlmReply:
        """按模型类型分派底层调用；expected_format 只对本地（Ollama）生效"""
        if self.config.type == "local":
            return self._call_local_model(prompt, expected_format, temperature, max_tokens)
        return self._call_cloud_model(prompt, system_prompt, temperature, max_tokens)

    def _call_local_model(
        self,
        prompt: str,
        expected_format: str = "json",
        temperature: float = 0,
        max_tokens: int = 8192
    ) -> LlmReply:
        """调用本地模型API（Ollama）

        参数必须放进 options：/api/generate 只认 options.num_predict / options.temperature /
        options.num_ctx，顶层同名字段会被静默忽略（输出失去上限、temperature 不生效）。
        """
        def _do_call():
            response = requests.post(
                f"{self.config.api_url}/api/generate",
                json={
                    "model": self.config.model_name,
                    "prompt": prompt,
                    "format": expected_format,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                        "num_ctx": self.config.context_length
                    }
                },
                timeout=self.config.timeout
            )
            if response.status_code == 200:
                payload = response.json()
                text = payload.get('response', '')
                if text:
                    logger.info(f"本地模型响应成功，响应长度: {len(text)}")
                    return LlmReply(
                        text=text,
                        truncated=payload.get("done_reason") == "length",
                        generated_tokens=int(payload.get("eval_count") or 0),
                    )
                raise ValueError("响应内容为空")
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")

        return self._with_retry(_do_call, "local/generate") or LlmReply()
    
    def _post_cloud(self, request_params: Dict[str, Any]) -> Dict[str, Any]:
        """云端唯一的 HTTP 出口：鉴权头、状态判定、取 payload 只在这一处

        200 但 body 不是对话响应（网关把错误吞成 200、返回空体或 HTML）时抛带响应
        片段的 RuntimeError。让调用方 `json()["choices"]` 抛裸 KeyError 的话，
        日志里只剩一个键名，看不出是哪一个请求、服务端到底回了什么。
        """
        response = requests.post(
            f"{self.config.api_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json"
            },
            json=request_params,
            timeout=self.config.timeout
        )
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("choices"):
            raise RuntimeError(f"HTTP 200 但响应没有 choices: {response.text[:200]}")
        return payload

    def _call_cloud_model(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float = 0,
        max_tokens: int = 8192
    ) -> LlmReply:
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
            payload = self._post_cloud(request_params)
            choice = payload["choices"][0]
            text = choice.get('message', {}).get('content', '')
            if not text:
                raise ValueError("响应内容为空")
            logger.info(f"云端模型响应成功，响应长度: {len(text)}")
            usage = payload.get("usage") or {}
            return LlmReply(
                text=text,
                truncated=choice.get("finish_reason") == "length",
                generated_tokens=int(usage.get("completion_tokens") or 0),
            )

        return self._with_retry(_do_call, "cloud/chat") or LlmReply()
    
    def test_connection(self) -> bool:
        """测试模型连接是否正常

        直接走底层 API：连通性探测只要极短输出，被 max_tokens 掐断属预期，
        截断告警挂在公开方法上，这里不该产生。底层失败已由 _with_retry 收敛为
        空 LlmReply，无需在此再包一层异常。
        """
        if self.config.type == "local":
            reply = self._call_local_model("Hello", "text", 0, 10)
        else:
            # 使用较高的 max_tokens (100) 以支持带 reasoning 的模型（如 DeepSeek V4）
            reply = self._call_cloud_model("Hello", "你是一个AI助手。", 0, 100)
        return bool(reply.text)

    def embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        """批量计算文本向量（embedding 模型）。失败返回 None，调用方需优雅降级。"""
        if not texts:
            return []
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
            msg = self._post_cloud(request_params)["choices"][0].get("message", {})
            return {"content": msg.get("content", ""), "tool_calls": msg.get("tool_calls", [])}

        return self._with_retry(_do_call, "cloud/chat")


# ModelClient 全局工厂：版本化缓存单例 —— 配置（类型/模型名/地址/密钥/上下文窗口）变化即重建，
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
        # context_length 必须在签名里：探测/手填改完窗口后，旧实例还带着上一个 num_ctx
        # 与输入预算继续跑，摘要会按过小的窗口切块，且没有任何报错迹象。
        sig = (config.get('type'), config.get('model_name'), tuple(config.get('models') or []),
               config.get('api_url'), config.get('api_key'), config.get('context_length'))
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
