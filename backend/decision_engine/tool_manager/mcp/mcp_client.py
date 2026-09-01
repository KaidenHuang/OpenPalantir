"""
MCP 客户端 — 连接外部 MCP Server，发现和调用工具

支持 stdio（子进程）和 Streamable HTTP 两种传输方式。
"""

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from system.logger import logger


@dataclass
class MCPServerConfig:
    """外部 MCP Server 配置"""
    name: str                       # 逻辑名称，如 "github"
    transport: str = "stdio"        # "stdio" | "http"
    url: str = ""                   # HTTP 传输时的 URL
    command: str = ""               # stdio 传输时的启动命令
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)


class MCPClient:
    """MCP 客户端，连接单个外部 MCP Server"""

    def __init__(self, config: MCPServerConfig):
        self._config = config
        self._process: Optional[subprocess.Popen] = None
        self._session: Optional[requests.Session] = None
        self._id_counter = 0
        self._lock = threading.Lock()
        self._connected = False

    def connect(self) -> bool:
        """建立连接"""
        try:
            if self._config.transport == "stdio":
                return self._connect_stdio()
            elif self._config.transport == "http":
                return self._connect_http()
            else:
                logger.error(f"[mcp_client] 不支持的传输方式: {self._config.transport}")
                return False
        except Exception as e:
            logger.error(f"[mcp_client] 连接失败 ({self._config.name}): {e}")
            return False

    def disconnect(self):
        """关闭连接"""
        self._connected = False
        if self._process:
            try:
                self._process.stdin.close()
                self._process.stdout.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        if self._session:
            self._session.close()
            self._session = None

    def list_tools(self) -> List[dict]:
        """获取工具列表（原始 MCP 格式）"""
        response = self._send_request("tools/list")
        if response and "result" in response:
            return response["result"].get("tools", [])
        return []

    def call_tool(self, name: str, arguments: dict) -> dict:
        """调用工具，返回原始 MCP 响应"""
        response = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if response and "result" in response:
            return response["result"]
        if response and "error" in response:
            return {"error": str(response["error"])}
        return {"error": "no response"}

    # ─── 内部方法 ────────────────────────────────────────

    def _connect_stdio(self) -> bool:
        """通过 stdio 连接（启动子进程）"""
        env = os.environ.copy()
        env.update(self._config.env)

        try:
            self._process = subprocess.Popen(
                [self._config.command] + self._config.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,
            )
            self._connected = True
            logger.info(
                f"[mcp_client] stdio 连接成功: {self._config.name} "
                f"({self._config.command} {' '.join(self._config.args)})"
            )
            return True
        except FileNotFoundError as e:
            logger.error(f"[mcp_client] stdio 命令未找到 ({self._config.name}): {e}")
            return False
        except Exception as e:
            logger.error(f"[mcp_client] stdio 连接失败 ({self._config.name}): {e}")
            return False

    def _connect_http(self) -> bool:
        """通过 HTTP 连接"""
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        # 发送 ping 测试连通性
        try:
            response = self._send_request("ping")
            self._connected = True
            logger.info(f"[mcp_client] HTTP 连接成功: {self._config.name} ({self._config.url})")
            return True
        except Exception as e:
            logger.error(f"[mcp_client] HTTP 连接失败 ({self._config.name}): {e}")
            self._session = None
            return False

    def _send_request(self, method: str, params: dict = None) -> Optional[dict]:
        """发送 JSON-RPC 请求并返回解析后的响应"""
        request_id = self._next_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }

        if self._config.transport == "stdio":
            return self._send_request_stdio(request)
        elif self._config.transport == "http":
            return self._send_request_http(request)
        return None

    def _send_request_stdio(self, request: dict) -> Optional[dict]:
        """通过 stdio 发送请求"""
        if not self._process or self._process.poll() is not None:
            logger.error(f"[mcp_client] stdio 进程已退出 ({self._config.name})")
            self._connected = False
            return None

        try:
            with self._lock:
                request_line = json.dumps(request, ensure_ascii=False)
                self._process.stdin.write(request_line + "\n")
                self._process.stdin.flush()

                response_line = self._process.stdout.readline()
                if not response_line:
                    logger.error(f"[mcp_client] stdio 无响应 ({self._config.name})")
                    return None

                return json.loads(response_line.strip())
        except (BrokenPipeError, OSError) as e:
            logger.error(f"[mcp_client] stdio 通信失败 ({self._config.name}): {e}")
            self._connected = False
            return None
        except json.JSONDecodeError as e:
            logger.error(f"[mcp_client] stdio 响应解析失败 ({self._config.name}): {e}")
            return None

    def _send_request_http(self, request: dict) -> Optional[dict]:
        """通过 HTTP 发送请求"""
        if not self._session:
            return None

        try:
            response = self._session.post(
                self._config.url,
                json=request,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"[mcp_client] HTTP 请求失败 ({self._config.name}): {e}")
            self._connected = False
            return None
        except json.JSONDecodeError as e:
            logger.error(f"[mcp_client] HTTP 响应解析失败 ({self._config.name}): {e}")
            return None

    def _next_id(self) -> str:
        self._id_counter += 1
        return str(self._id_counter)

    @property
    def is_connected(self) -> bool:
        return self._connected