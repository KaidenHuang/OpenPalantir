"""
MCPManager — 管理多个 MCP Server 连接，提供统一的工具列表和执行路由
"""

import json
from typing import Any, Dict, List, Optional

from decision_engine.tool_manager.mcp.mcp_client import MCPClient, MCPServerConfig
from system.logger import logger


class MCPManager:
    """管理多个 MCP Server 连接，合并工具列表，路由执行

    工具命名约定：MCP 工具以 "{server_name}__{tool_name}" 命名，
    本地 Skill 不加前缀，由此区分。
    """

    def __init__(self, server_configs: List[MCPServerConfig] = None):
        self._clients: Dict[str, MCPClient] = {}       # server_name → client
        self._mcp_tool_names: Dict[str, str] = {}       # "server__tool" → server_name
        self._mcp_tool_defs: Dict[str, dict] = {}       # "server__tool" → 原始 MCP tool 定义
        self._configs = server_configs or []

    def connect_all(self) -> int:
        """连接所有配置的 MCP Server，返回成功连接数"""
        success_count = 0
        for cfg in self._configs:
            client = MCPClient(cfg)
            if client.connect():
                self._clients[cfg.name] = client
                # 获取工具列表并注册
                tools = client.list_tools()
                for tool in tools:
                    tool_name = tool.get("name", "")
                    full_name = f"{cfg.name}__{tool_name}"
                    self._mcp_tool_names[full_name] = cfg.name
                    self._mcp_tool_defs[full_name] = tool
                success_count += 1
                logger.info(
                    f"[mcp_manager] {cfg.name}: 已连接，{len(tools)} 个工具"
                )
            else:
                logger.warning(f"[mcp_manager] {cfg.name}: 连接失败，跳过")

        logger.info(
            f"[mcp_manager] 连接完成: {success_count}/{len(self._configs)} 成功, "
            f"共 {len(self._mcp_tool_names)} 个 MCP 工具"
        )
        return success_count

    def disconnect_all(self):
        """断开所有 MCP Server 连接"""
        for name, client in self._clients.items():
            client.disconnect()
            logger.info(f"[mcp_manager] {name}: 已断开")
        self._clients.clear()
        self._mcp_tool_names.clear()
        self._mcp_tool_defs.clear()

    def get_tool_definitions(self) -> List[dict]:
        """返回所有 MCP 工具的 OpenAI 格式定义列表

        每个工具名以 {server_name}__ 为前缀，inputSchema 直接作为 parameters。
        """
        result = []
        for full_name, tool_def in self._mcp_tool_defs.items():
            input_schema = tool_def.get("inputSchema", {
                "type": "object",
                "properties": {},
            })
            # 确保 required 字段存在
            if "required" not in input_schema:
                input_schema["required"] = []

            result.append({
                "type": "function",
                "function": {
                    "name": full_name,
                    "description": tool_def.get("description", ""),
                    "parameters": input_schema,
                },
            })
        return result

    def get_tool_descriptions(self) -> str:
        """生成 MCP 工具描述文本，用于 system prompt"""
        if not self._mcp_tool_defs:
            return ""

        lines = ["\n### 外部 MCP 工具"]
        for full_name, tool_def in self._mcp_tool_defs.items():
            desc = tool_def.get("description", "")
            # 提取参数信息
            input_schema = tool_def.get("inputSchema", {})
            params = input_schema.get("properties", {})
            params_desc = json.dumps(
                {k: v.get("description", v.get("type", "")) for k, v in params.items()},
                ensure_ascii=False,
            )
            lines.append(
                f"- **{full_name}**: {desc}\n"
                f"  参数: {params_desc}"
            )
        return "\n".join(lines)

    def execute(self, tool_name: str, params: dict) -> dict:
        """执行 MCP 工具

        Returns:
            {"success": True/False, "data": ..., "error": ""}
        """
        server_name = self._mcp_tool_names.get(tool_name)
        if not server_name:
            return {"success": False, "data": None, "error": f"工具 '{tool_name}' 不存在"}

        client = self._clients.get(server_name)
        if not client or not client.is_connected:
            return {"success": False, "data": None, "error": f"Server '{server_name}' 未连接"}

        # 从全名中提取原始工具名
        original_name = tool_name[len(server_name) + 2:]  # 去掉 "server__"

        try:
            raw_result = client.call_tool(original_name, params)
            # MCP tools/call 返回 content 数组
            if isinstance(raw_result, dict) and "content" in raw_result:
                content = raw_result["content"]
                # content 是 [{type: "text", text: "..."}] 或 [{type: "resource", ...}]
                if isinstance(content, list) and len(content) > 0:
                    # 提取文本内容
                    texts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            texts.append(item.get("text", ""))
                    if texts:
                        data = "\n".join(texts)
                        # 尝试解析为 JSON
                        try:
                            data = json.loads(data)
                        except (json.JSONDecodeError, TypeError):
                            pass
                        return {"success": True, "data": data, "error": ""}
                    return {"success": True, "data": content, "error": ""}
                return {"success": True, "data": raw_result, "error": ""}
            elif isinstance(raw_result, dict) and "error" in raw_result:
                return {"success": False, "data": None, "error": str(raw_result["error"])}
            return {"success": True, "data": raw_result, "error": ""}
        except Exception as e:
            logger.error(f"[mcp_manager] 工具执行失败 ({tool_name}): {e}")
            return {"success": False, "data": None, "error": str(e)}

    def is_mcp_tool(self, tool_name: str) -> bool:
        """判断是否为 MCP 工具（按名称前缀匹配）"""
        return tool_name in self._mcp_tool_names

    @property
    def tool_count(self) -> int:
        return len(self._mcp_tool_names)