"""
MCP 模块单元测试

验证 MCPClient stdio 连接、tool 列表获取、tool 调用。
"""

import sys
import os

# 添加 backend 目录到 path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

from decision_engine.tool_manager.mcp.mcp_client import MCPClient, MCPServerConfig
from decision_engine.tool_manager.mcp.mcp_manager import MCPManager
from decision_engine.tool_manager.mcp.config import load_mcp_server_configs

_SERVER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_mcp_server.py")


def test_mcp_client_stdio():
    """测试 MCPClient stdio 连接和工具调用"""
    config = MCPServerConfig(
        name="test",
        transport="stdio",
        command=sys.executable,
        args=[_SERVER_PATH],
    )

    client = MCPClient(config)
    assert client.connect(), "连接失败"

    # 测试 list_tools
    tools = client.list_tools()
    assert len(tools) == 2, f"应有 2 个工具，实际 {len(tools)}"
    assert tools[0]["name"] == "echo"
    assert tools[1]["name"] == "add"
    print(f"  [OK] list_tools: {len(tools)} 个工具")

    # 测试 call_tool - echo
    result = client.call_tool("echo", {"message": "hello"})
    assert "content" in result, f"echo 应返回 content, 实际: {result}"
    print(f"  [OK] call_tool(echo): {result}")

    # 测试 call_tool - add
    result = client.call_tool("add", {"a": 3, "b": 5})
    assert "content" in result, f"add 应返回 content, 实际: {result}"
    print(f"  [OK] call_tool(add): {result}")

    client.disconnect()
    print("  [OK] disconnect")


def test_mcp_manager():
    """测试 MCPManager 多 Server 管理"""
    configs = [
        MCPServerConfig(
            name="test_server",
            transport="stdio",
            command=sys.executable,
            args=[_SERVER_PATH],
        ),
    ]

    manager = MCPManager(configs)
    success = manager.connect_all()
    assert success == 1, f"应连接 1 个 server，实际 {success}"
    print(f"  [OK] connect_all: {success} 个 server")

    # 测试工具定义
    tools = manager.get_tool_definitions()
    assert len(tools) == 2, f"应有 2 个工具，实际 {len(tools)}"
    assert tools[0]["function"]["name"] == "test_server__echo"
    assert tools[1]["function"]["name"] == "test_server__add"
    print(f"  [OK] get_tool_definitions: {len(tools)} 个工具（带前缀）")

    # 测试 is_mcp_tool
    assert manager.is_mcp_tool("test_server__echo")
    assert not manager.is_mcp_tool("search_entities")
    print("  [OK] is_mcp_tool 路由正确")

    # 测试 execute
    result = manager.execute("test_server__echo", {"message": "world"})
    assert result["success"], f"execute 应成功: {result}"
    assert result["data"]["echo"] == "world"
    print(f"  [OK] execute(echo): {result}")

    result = manager.execute("test_server__add", {"a": 10, "b": 20})
    assert result["success"]
    assert result["data"]["sum"] == 30
    print(f"  [OK] execute(add): {result}")

    # 测试执行不存在的工具
    result = manager.execute("test_server__nonexistent", {})
    assert not result["success"]
    print(f"  [OK] execute(nonexistent): 正确返回失败")

    # 测试工具描述
    desc = manager.get_tool_descriptions()
    assert "test_server__echo" in desc
    assert "test_server__add" in desc
    print(f"  [OK] get_tool_descriptions: 包含 {manager.tool_count} 个工具描述")

    manager.disconnect_all()
    print("  [OK] disconnect_all")


def test_config_loading():
    """测试配置加载（空配置）"""
    configs = load_mcp_server_configs()
    # 默认配置文件为空列表，应该返回 []
    print(f"  [OK] load_mcp_server_configs: {len(configs)} 个配置")


if __name__ == "__main__":
    print("=== MCP 模块测试 ===")
    print()

    print("[test_mcp_client_stdio]")
    test_mcp_client_stdio()

    print()
    print("[test_mcp_manager]")
    test_mcp_manager()

    print()
    print("[test_config_loading]")
    test_config_loading()

    print()
    print("=== 全部测试通过 ===")