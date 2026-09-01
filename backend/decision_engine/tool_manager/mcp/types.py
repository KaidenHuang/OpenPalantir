"""
MCP 协议类型定义 — JSON-RPC 2.0 消息结构
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class JSONRPCRequest:
    """JSON-RPC 2.0 请求"""
    jsonrpc: str = "2.0"
    id: Optional[str] = None  # None 表示 notification（无需响应）
    method: str = ""
    params: dict = field(default_factory=dict)


@dataclass
class JSONRPCResponse:
    """JSON-RPC 2.0 成功响应"""
    jsonrpc: str = "2.0"
    id: str = ""
    result: Any = None


@dataclass
class JSONRPCError:
    """JSON-RPC 2.0 错误响应"""
    jsonrpc: str = "2.0"
    id: str = ""
    error: dict = field(default_factory=dict)  # {code: int, message: str, data?: any}