#!/usr/bin/env python3
"""模拟客户问答集成测试"""
import json
import time
import urllib.request

API_URL = "http://localhost:8000/api/decision/ask"

CASES = [
    # (编号, 问题, 判定函数)
    # 社交意图
    ("S1", "你好", lambda d: d["response_type"] == "simple" and d["confidence"] == 1.0),
    ("S2", "谢谢", lambda d: d["response_type"] == "simple"),
    ("S3", "再见", lambda d: d["response_type"] == "simple"),
    # 事实查询（禁止误调 analyze_*）
    ("F1", "当前有哪几个部门", lambda d:
        all(t["tool_name"] not in ("analyze_centrality", "analyze_community", "analyze_path")
            for t in d.get("tool_trace", []))),
    ("F2", "员工张三在哪个部门", lambda d:
        all(t["tool_name"] not in ("analyze_centrality", "analyze_community", "analyze_path")
            for t in d.get("tool_trace", []))),
    ("F3", "公司有多少员工", lambda d:
        all(t["tool_name"] not in ("analyze_centrality", "analyze_community", "analyze_path")
            for t in d.get("tool_trace", []))),
    # 图分析（正确使用工具）
    ("G1", "分析组织架构中的核心节点", lambda d:
        any(t["tool_name"] == "analyze_centrality" for t in d.get("tool_trace", []))),
    ("G2", "检测组织中的社区结构", lambda d:
        any(t["tool_name"] == "analyze_community" for t in d.get("tool_trace", []))),
    ("G3", "分析张三和李四之间的关联路径", lambda d:
        any(t["tool_name"] == "analyze_path" for t in d.get("tool_trace", []))),
    # 异常场景
    ("E2", "...", lambda d: d is not None and "response_type" in d),
]


def ask(question: str, timeout: int = 120) -> dict:
    body = json.dumps({"question": question, "domain": "workforce"}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def run():
    passed = 0
    failed = 0
    for case_id, question, check in CASES:
        print(f"\n{'='*60}")
        print(f"[{case_id}] {question}")
        print(f"{'='*60}")

        start = time.time()
        result = ask(question)
        elapsed = time.time() - start

        if "error" in result:
            print(f"  ❌ FAIL — 请求失败: {result['error']}  ({elapsed:.1f}s)")
            failed += 1
            continue

        # 提取关键信息
        resp_type = result.get("response_type", "?")
        confidence = result.get("confidence", 0)
        summary = result.get("answer", {}).get("summary", "")[:80]
        tools = [t["tool_name"] for t in result.get("tool_trace", [])]
        metadata = result.get("metadata", {})

        print(f"  耗时: {elapsed:.1f}s")
        print(f"  response_type: {resp_type}")
        print(f"  confidence: {confidence}")
        print(f"  summary: {summary}")
        print(f"  tools_called: {tools}")
        print(f"  turns: {metadata.get('total_turns', '?')}, tool_calls: {metadata.get('total_tool_calls', '?')}")

        try:
            if check(result):
                print(f"  ✅ PASS")
                passed += 1
            else:
                print(f"  ❌ FAIL — 判定条件未通过")
                failed += 1
        except Exception as e:
            print(f"  ❌ FAIL — 判定异常: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"结果: {passed} 通过, {failed} 失败 (共 {len(CASES)} 个)")
    print(f"{'='*60}")


if __name__ == "__main__":
    run()
