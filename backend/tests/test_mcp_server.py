"""
测试用 MCP Server（stdio 传输）

实现最简单的 MCP Server，用于验证 MCPClient 的连接和调用。
用法: python test_mcp_server.py
"""

import json
import sys


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = request.get("method", "")
        req_id = request.get("id", "")

        if method == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "回显输入的消息",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "message": {
                                        "type": "string",
                                        "description": "要回显的消息"
                                    }
                                },
                                "required": ["message"]
                            }
                        },
                        {
                            "name": "add",
                            "description": "计算两个数字的和",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "a": {"type": "number", "description": "第一个数字"},
                                    "b": {"type": "number", "description": "第二个数字"}
                                },
                                "required": ["a", "b"]
                            }
                        }
                    ]
                }
            }
        elif method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            if tool_name == "echo":
                msg = arguments.get("message", "")
                text = json.dumps({"echo": msg}, ensure_ascii=False)
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": text}]
                    }
                }
            elif tool_name == "add":
                a = arguments.get("a", 0)
                b = arguments.get("b", 0)
                result = a + b
                text = json.dumps({"sum": result}, ensure_ascii=False)
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": text}]
                    }
                }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"}
                }
        elif method == "ping":
            response = {"jsonrpc": "2.0", "id": req_id, "result": {}}
        else:
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method '{method}' not found"}
            }

        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()