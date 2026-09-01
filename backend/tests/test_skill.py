"""
Skill 系统单元测试

测试 SkillLoader / SkillRegistry / SkillDefinition 的核心功能。
不依赖外部服务（Neo4j、LLM），只测试 Skill 加载和注册逻辑。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decision_engine.tool_manager.skill.skill_loader import (
    Skill, SkillDefinition, SkillLoader, SkillParam, SkillResult,
)
from decision_engine.tool_manager.skill.skill_registry import SkillRegistry


class TestSkillLoader:
    """SkillLoader 单元测试"""

    def test_parse_skill_md(self):
        """解析 SKILL.md frontmatter"""
        # 创建临时 SKILL.md
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "test_skill")
            os.makedirs(skill_dir)
            skill_md = os.path.join(skill_dir, "SKILL.md")

            content = """---
name: test_echo
description: 测试用 Skill，回显输入
category: test
parameters:
  - name: message
    type: string
    description: 要回显的消息
    required: true
  - name: count
    type: integer
    description: 重复次数
    required: false
---
# test_echo

这是一个测试 Skill。
"""
            with open(skill_md, "w", encoding="utf-8") as f:
                f.write(content)

            definition = SkillLoader.parse_skill_md(skill_md)
            assert definition is not None, "应成功解析"
            assert definition.name == "test_echo", f"name 应为 test_echo，实际 {definition.name}"
            assert definition.description == "测试用 Skill，回显输入"
            assert definition.category == "test"
            assert len(definition.parameters) == 2, f"应有 2 个参数，实际 {len(definition.parameters)}"
            assert definition.parameters[0].name == "message"
            assert definition.parameters[0].required is True
            assert definition.parameters[1].name == "count"
            assert definition.parameters[1].required is False

    def test_parse_skill_md_no_frontmatter(self):
        """缺少 frontmatter 的 SKILL.md 返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "bad_skill")
            os.makedirs(skill_dir)
            skill_md = os.path.join(skill_dir, "SKILL.md")
            with open(skill_md, "w", encoding="utf-8") as f:
                f.write("没有 frontmatter 的文件")

            definition = SkillLoader.parse_skill_md(skill_md)
            assert definition is None, "缺少 frontmatter 应返回 None"

    def test_parse_skill_md_missing_name(self):
        """缺少 name 字段的 SKILL.md 返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "noname_skill")
            os.makedirs(skill_dir)
            skill_md = os.path.join(skill_dir, "SKILL.md")
            content = """---
description: 没有 name 的 Skill
category: test
---"""
            with open(skill_md, "w", encoding="utf-8") as f:
                f.write(content)

            definition = SkillLoader.parse_skill_md(skill_md)
            assert definition is None, "缺少 name 应返回 None"

    def test_skill_definition_to_openai_tool(self):
        """SkillDefinition 转换为 OpenAI tool 格式"""
        definition = SkillDefinition(
            name="search_test",
            description="搜索测试",
            parameters=[
                SkillParam(name="query", type="string", description="搜索关键词", required=True),
                SkillParam(name="limit", type="integer", description="返回数量", required=False),
            ],
            category="test",
        )

        tool = definition.to_openai_tool()
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "search_test"
        assert tool["function"]["description"] == "搜索测试"
        assert "query" in tool["function"]["parameters"]["properties"]
        assert "limit" in tool["function"]["parameters"]["properties"]
        assert tool["function"]["parameters"]["required"] == ["query"]

    def test_skill_definition_to_openai_tool_no_params(self):
        """无参数的 Skill 转换为 OpenAI tool 格式"""
        definition = SkillDefinition(
            name="ping",
            description="测试连通性",
            category="test",
        )
        tool = definition.to_openai_tool()
        assert tool["type"] == "function"
        assert tool["function"]["parameters"]["type"] == "object"
        assert tool["function"]["parameters"]["properties"] == {}
        # 无参数时 required 字段可能不存在，两种形式都合法

    def test_skill_execution_success(self):
        """Skill 执行成功"""
        def my_executor(params):
            return {"echo": params.get("message", ""), "length": len(params.get("message", ""))}

        definition = SkillDefinition(
            name="echo", description="回显", category="test",
            parameters=[SkillParam(name="message", type="string", description="消息", required=True)],
        )
        skill = Skill(definition, my_executor)

        result = skill({"message": "hello"})
        assert result.success, "应执行成功"
        assert result.data["echo"] == "hello"
        assert result.data["length"] == 5
        assert result.execution_time_ms > 0, "应记录执行时间"

    def test_skill_execution_failure(self):
        """Skill 执行失败时返回 SkillResult 而不是抛出异常"""
        def failing_executor(params):
            raise ValueError("模拟执行失败")

        definition = SkillDefinition(name="failer", description="会失败的 Skill", category="test")
        skill = Skill(definition, failing_executor)

        result = skill({"key": "value"})
        assert not result.success, "应标记为失败"
        assert "模拟执行失败" in result.error
        assert result.skill_name == "failer"

    def test_load_from_real_skills_directory(self):
        """从真实的 skills/ 目录加载 Skill"""
        skills_root = os.path.join(
            os.path.dirname(__file__), "..", "decision_engine", "skills"
        )
        skills = SkillLoader.load_from_directory(skills_root)

        assert len(skills) >= 8, f"应至少加载 8 个 Skill，实际 {len(skills)}"
        skill_names = [s.definition.name for s in skills]
        assert "search_entities" in skill_names, "应包含 search_entities"
        assert "analyze_path" in skill_names, "应包含 analyze_path"
        assert "search_documents" in skill_names, "应包含 search_documents"
        assert "query_database" in skill_names, "应包含 query_database"

        # 验证每个 Skill 都有 executor
        for s in skills:
            assert s.executor is not None, f"{s.definition.name} 应有 executor"
            assert s.definition.name, "每个 Skill 应有名称"
            assert s.definition.description, "每个 Skill 应有描述"

    def test_load_nonexistent_directory(self):
        """加载不存在的目录应返回空列表"""
        skills = SkillLoader.load_from_directory("/nonexistent/path/to/skills")
        assert skills == [], "不存在的目录应返回空列表"


class TestSkillRegistry:
    """SkillRegistry 单元测试"""

    def test_register_and_get(self):
        """注册 Skill 后能通过名称获取"""
        registry = SkillRegistry()

        def dummy_executor(params):
            return {"ok": True}

        definition = SkillDefinition(
            name="dummy", description="测试 Skill", category="test",
        )
        skill = Skill(definition, dummy_executor)
        registry.register(skill, domains=["general"])

        assert registry.get("dummy") is not None, "应按名称获取"
        assert registry.get("nonexistent") is None, "不存在的应返回 None"

    def test_domain_filtering(self):
        """按 domain 过滤 Skill"""
        registry = SkillRegistry()

        def dummy_executor(params):
            return {"ok": True}

        general_skill = Skill(
            SkillDefinition(name="general_tool", description="", category="general"),
            dummy_executor,
        )
        workforce_skill = Skill(
            SkillDefinition(name="workforce_tool", description="", category="workforce"),
            dummy_executor,
        )

        registry.register(general_skill, domains=["general"])
        registry.register(workforce_skill, domains=["workforce"])

        # workforce 域应包含 general + workforce
        wf_skills = registry.get_for_domain("workforce")
        wf_names = [s.definition.name for s in wf_skills]
        assert "general_tool" in wf_names, "workforce 域应包含 general Skill"
        assert "workforce_tool" in wf_names, "workforce 域应包含自己的 Skill"

        # general 域只包含 general
        g_skills = registry.get_for_domain("general")
        g_names = [s.definition.name for s in g_skills]
        assert "general_tool" in g_names
        assert "workforce_tool" not in g_names, "general 域不应包含 workforce Skill"

    def test_tool_definitions_format(self):
        """生成的 tool definitions 符合 OpenAI 格式"""
        registry = SkillRegistry()

        def dummy_executor(params):
            return {"result": params}

        definition = SkillDefinition(
            name="test_tool",
            description="测试工具",
            parameters=[
                SkillParam(name="input", type="string", description="输入参数", required=True),
            ],
            category="test",
        )
        skill = Skill(definition, dummy_executor)
        registry.register(skill, domains=["general"])

        tools = registry.get_tool_definitions("general")
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "test_tool"
        assert "input" in tools[0]["function"]["parameters"]["properties"]

    def test_execute(self):
        """执行已注册的 Skill"""
        registry = SkillRegistry()

        def add_executor(params):
            return {"sum": params["a"] + params["b"]}

        definition = SkillDefinition(
            name="add",
            description="加法",
            parameters=[
                SkillParam(name="a", type="number", description="加数", required=True),
                SkillParam(name="b", type="number", description="被加数", required=True),
            ],
        )
        skill = Skill(definition, add_executor)
        registry.register(skill, domains=["general"])

        result = registry.execute("add", {"a": 3, "b": 7})
        assert result.success, "应执行成功"
        assert result.data["sum"] == 10

    def test_execute_nonexistent(self):
        """执行不存在的 Skill 返回失败"""
        registry = SkillRegistry()
        result = registry.execute("nonexistent", {})
        assert not result.success, "不存在的 Skill 应返回失败"
        assert "不存在" in result.error

    def test_list_all(self):
        """列出所有已注册 Skill"""
        registry = SkillRegistry()

        def dummy_executor(params):
            return {}

        registry.register(
            Skill(SkillDefinition(name="a", description=""), dummy_executor),
            domains=["general"],
        )
        registry.register(
            Skill(SkillDefinition(name="b", description=""), dummy_executor),
            domains=["general"],
        )

        names = registry.list_all()
        assert len(names) == 2, f"应有 2 个 Skill，实际 {len(names)}"
        assert "a" in names and "b" in names

    def test_load_all_from_real_directory(self):
        """从真实 skills/ 目录加载所有 Skill 并注册"""
        registry = SkillRegistry()
        skills_root = os.path.join(
            os.path.dirname(__file__), "..", "decision_engine", "skills"
        )

        count = registry.load_all(skills_root, domains=["general", "workforce"])
        assert count >= 8, f"应加载至少 8 个 Skill，实际 {count}"

        # 验证可以获取工具定义
        tools = registry.get_tool_definitions("workforce")
        assert len(tools) >= 8
        for tool in tools:
            assert tool["type"] == "function"
            assert tool["function"]["name"], "每个工具应有名称"


def run_tests():
    loader = TestSkillLoader()
    registry = TestSkillRegistry()

    passed = 0
    failed = 0

    print("=== SkillLoader 测试 ===")
    for name in dir(loader):
        if name.startswith("test_"):
            method = getattr(loader, name)
            try:
                method()
                print(f"  [OK] {name}")
                passed += 1
            except Exception as e:
                print(f"  [FAIL] {name}: {e}")
                failed += 1

    print("\n=== SkillRegistry 测试 ===")
    for name in dir(registry):
        if name.startswith("test_"):
            method = getattr(registry, name)
            try:
                method()
                print(f"  [OK] {name}")
                passed += 1
            except Exception as e:
                print(f"  [FAIL] {name}: {e}")
                failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)