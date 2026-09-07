"""
Skill 加载器

扫描 skills/ 目录，解析 SKILL.md（YAML frontmatter + Markdown）并加载 executor.py，
组装为 Skill 实例供 SkillRegistry 注册。
"""

import importlib.util
import os
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from system.logger import logger


@dataclass
class SkillParam:
    """Skill 参数定义"""
    name: str
    type: str  # "string" | "number" | "integer" | "boolean" | "array" | "object"
    description: str
    required: bool = True


@dataclass
class SkillDefinition:
    """Skill 元数据定义（从 SKILL.md frontmatter 解析）"""
    name: str
    description: str
    parameters: List[SkillParam] = field(default_factory=list)
    category: str = "general"
    skill_dir: str = ""  # Skill 目录名

    def to_openai_tool(self) -> dict:
        """生成 OpenAI 兼容的 tool definition"""
        properties = {}
        required_list = []
        for p in self.parameters:
            properties[p.name] = {
                "type": p.type,
                "description": p.description,
            }
            if p.required:
                required_list.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required_list,
                } if properties else {"type": "object", "properties": {}},
            }
        }


@dataclass
class SkillResult:
    """Skill 执行结果"""
    skill_name: str
    success: bool
    data: Any = None
    error: str = ""
    execution_time_ms: float = 0.0

    def summarize(self) -> str:
        """将执行结果压缩为简短摘要（≤500 字符）

        通用启发式逻辑：按常见 key 模式提取关键信息。
        各 Skill 的 executor 返回约定结构即可自动获得有意义的摘要。
        """
        import json as _json

        if not self.success:
            return f"执行失败: {self.error}" if self.error else "执行失败"

        data = self.data
        if not data:
            return "（无结果）"

        if isinstance(data, dict):
            # 按常见 key 模式提取摘要
            if "entities" in data and isinstance(data["entities"], list):
                entities = data["entities"]
                names = [e.get("name", str(e))[:30] for e in entities[:5]]
                extra = f"等{len(entities)}个" if len(entities) > 5 else ""
                return f"找到实体: {', '.join(names)}{extra}"

            if "documents" in data and isinstance(data["documents"], list):
                docs = data["documents"]
                return f"找到 {len(docs)} 个相关文档"

            if "relations" in data and isinstance(data["relations"], list):
                rels = data["relations"]
                total = data.get("total_relations", len(rels))
                return f"找到 {total} 条关系（展示 {len(rels)} 条）"

            if "communities" in data and isinstance(data["communities"], list):
                total = data.get("total_communities", len(data["communities"]))
                return f"检测到 {total} 个社区"

            if "top_nodes" in data and isinstance(data["top_nodes"], list):
                total = data.get("total_nodes", len(data["top_nodes"]))
                names = [n.get("name", str(n))[:20] for n in data["top_nodes"][:3]]
                return f"中心性分析: {total} 个节点，Top: {', '.join(names)}"

            if "tables" in data and isinstance(data["tables"], list):
                tables = data["tables"]
                names = [t.get("table", "?") for t in tables[:3]]
                return f"匹配 {len(tables)} 个表: {', '.join(names)}"

            if "paths" in data and isinstance(data["paths"], list):
                return f"找到 {len(data['paths'])} 条路径"

            if "found" in data:
                if data["found"]:
                    entity = data.get("entity", {})
                    name = entity.get("name", "未知") if isinstance(entity, dict) else str(entity)
                    return f"找到实体: {name}"
                return f"未找到: {data.get('message', '')}"

            # 通用 dict：序列化前几个 key 的预览
            text = _json.dumps(data, ensure_ascii=False, default=str)
            return text[:497] + "..." if len(text) > 500 else text

        if isinstance(data, list):
            return f"返回 {len(data)} 条记录"

        text = str(data)
        return text[:497] + "..." if len(text) > 500 else text


class Skill:
    """Skill 实例：定义 + 执行函数"""

    def __init__(self, definition: SkillDefinition, executor: Callable[[Dict[str, Any]], Any]):
        self.definition = definition
        self.executor = executor

    def __call__(self, params: Dict[str, Any]) -> SkillResult:
        """执行 Skill，统一计时和异常保护"""
        start = time.time()
        try:
            data = self.executor(params)
            elapsed = (time.time() - start) * 1000
            return SkillResult(
                skill_name=self.definition.name,
                success=True,
                data=data,
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            logger.warning(f"[skill] {self.definition.name} 执行失败: {e}\n{traceback.format_exc()}")
            return SkillResult(
                skill_name=self.definition.name,
                success=False,
                error=str(e),
                execution_time_ms=elapsed,
            )

    def summarize(self, result: SkillResult) -> str:
        """生成执行结果的摘要，委托给 SkillResult.summarize()"""
        return result.summarize()


class SkillLoader:
    """扫描 skills/ 目录，从 SKILL.md 加载 Skill"""

    @staticmethod
    def parse_skill_md(file_path: str) -> Optional[SkillDefinition]:
        """解析 SKILL.md 的 YAML frontmatter + Markdown 正文"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"[skill_loader] 无法读取 {file_path}: {e}")
            return None

        # 解析 YAML frontmatter（--- 分隔）
        if not content.startswith("---"):
            logger.warning(f"[skill_loader] {file_path} 缺少 YAML frontmatter")
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            logger.warning(f"[skill_loader] {file_path} frontmatter 格式不完整")
            return None

        frontmatter_text = parts[1].strip()

        try:
            import yaml
            data = yaml.safe_load(frontmatter_text)
        except Exception:
            # 简易解析器（不依赖 yaml 库时使用）
            data = SkillLoader._simple_parse_frontmatter(frontmatter_text)

        if not data or not isinstance(data, dict):
            logger.warning(f"[skill_loader] {file_path} frontmatter 解析结果为空")
            return None

        name = data.get("name", "")
        if not name:
            logger.warning(f"[skill_loader] {file_path} 缺少 name 字段")
            return None

        parameters = []
        for p in data.get("parameters", []) or []:
            if isinstance(p, dict):
                parameters.append(SkillParam(
                    name=p.get("name", ""),
                    type=p.get("type", "string"),
                    description=p.get("description", ""),
                    required=p.get("required", True),
                ))

        return SkillDefinition(
            name=name,
            description=data.get("description", ""),
            parameters=parameters,
            category=data.get("category", "general"),
            skill_dir=os.path.basename(os.path.dirname(file_path)),
        )

    @staticmethod
    def _simple_parse_frontmatter(text: str) -> Dict[str, Any]:
        """简易 YAML 解析器，仅支持嵌套列表（parameters）"""
        # 最小化实现，建议安装 pyyaml
        import re
        result: Dict[str, Any] = {}
        current_key = ""
        for line in text.strip().split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" in stripped and not stripped.startswith("-"):
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                result[key] = value
                current_key = key
        return result

    @staticmethod
    def load_executor(skill_dir: str) -> Optional[Callable[[Dict[str, Any]], Any]]:
        """从 executor.py 中加载 execute 函数"""
        executor_path = os.path.join(skill_dir, "executor.py")
        if not os.path.isfile(executor_path):
            logger.warning(f"[skill_loader] {executor_path} 不存在")
            return None

        try:
            spec = importlib.util.spec_from_file_location(
                f"skill_executor_{os.path.basename(skill_dir)}", executor_path
            )
            if spec is None or spec.loader is None:
                logger.warning(f"[skill_loader] 无法加载 {executor_path}")
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "execute"):
                return module.execute
            logger.warning(f"[skill_loader] {executor_path} 缺少 execute 函数")
            return None
        except Exception as e:
            logger.warning(f"[skill_loader] 加载 {executor_path} 失败: {e}")
            return None

    @staticmethod
    def load_from_directory(skills_root: str) -> List[Skill]:
        """扫描 skills/ 目录下所有子目录，找到含 SKILL.md 的，加载为 Skill"""
        skills: List[Skill] = []
        if not os.path.isdir(skills_root):
            logger.warning(f"[skill_loader] 目录不存在: {skills_root}")
            return skills

        for entry in sorted(os.listdir(skills_root)):
            skill_dir = os.path.join(skills_root, entry)
            if not os.path.isdir(skill_dir):
                continue
            skill_md_path = os.path.join(skill_dir, "SKILL.md")
            if not os.path.isfile(skill_md_path):
                continue

            definition = SkillLoader.parse_skill_md(skill_md_path)
            if definition is None:
                continue

            executor = SkillLoader.load_executor(skill_dir)
            if executor is None:
                logger.warning(f"[skill_loader] Skill '{definition.name}' 缺少 executor，跳过")
                continue

            skill = Skill(definition, executor)
            skills.append(skill)
            logger.info(f"[skill_loader] 加载 Skill: {definition.name} ({definition.category})")

        return skills