"""
MCP 配置加载 — 从 JSON 配置文件加载外部 MCP Server 配置
"""

import json
import os
import re
from typing import List

from decision_engine.tool_manager.mcp.mcp_client import MCPServerConfig
from system.logger import logger

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "config", "mcp_servers.json"
)


def load_mcp_server_configs(config_path: str = None) -> List[MCPServerConfig]:
    """从 JSON 配置文件加载 MCP Server 配置

    支持 ${ENV_VAR} 环境变量替换。

    配置格式:
    {
      "servers": [
        {
          "name": "filesystem",
          "transport": "stdio",
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
        },
        {
          "name": "web_search",
          "transport": "http",
          "url": "http://search-service:9000/mcp"
        }
      ]
    }
    """
    path = config_path or _DEFAULT_CONFIG_PATH

    if not os.path.isfile(path):
        logger.info(f"[mcp_config] 配置文件不存在: {path}，跳过 MCP 工具加载")
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        servers = data.get("servers", [])
        configs = []

        for s in servers:
            name = s.get("name", "")
            if not name:
                logger.warning("[mcp_config] 跳过缺少 name 的配置项")
                continue

            transport = s.get("transport", "stdio")
            url = _resolve_env(s.get("url", ""))
            command = s.get("command", "")
            args = [_resolve_env(a) for a in s.get("args", [])]
            env = {k: _resolve_env(v) for k, v in s.get("env", {}).items()}

            configs.append(MCPServerConfig(
                name=name,
                transport=transport,
                url=url,
                command=command,
                args=args,
                env=env,
            ))

        logger.info(f"[mcp_config] 加载了 {len(configs)} 个 MCP Server 配置")
        return configs

    except json.JSONDecodeError as e:
        logger.error(f"[mcp_config] 配置文件解析失败: {e}")
        return []
    except Exception as e:
        logger.error(f"[mcp_config] 配置加载失败: {e}")
        return []


def _resolve_env(value: str) -> str:
    """替换字符串中的 ${VAR_NAME} 为环境变量值"""
    pattern = re.compile(r'\$\{([^}]+)\}')

    def _replace(match):
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))

    return pattern.sub(_replace, value)