"""
SkillRegistry 注册中心

全局单例，管理所有可用 Skill。按 domain 分发 Skill，
提供 OpenAI 兼容的 tool definitions 生成。
"""

import os
from typing import Dict, List, Optional

from system.logger import logger
from decision_engine.tool_manager.skill.skill_loader import Skill, SkillDefinition, SkillLoader, SkillResult


class SkillRegistry:
    """Skill 注册中心，管理所有可用 Skill"""

    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        # domain -> list of skill names
        self._domain_mapping: Dict[str, List[str]] = {}

    def register(self, skill: Skill, domains: Optional[List[str]] = None) -> None:
        """注册一个 Skill，可指定适用的 domain 列表"""
        name = skill.definition.name
        if name in self._skills:
            logger.warning(f"[skill_registry] Skill '{name}' 已注册，覆盖")
        self._skills[name] = skill
        for domain in (domains or ["general"]):
            self._domain_mapping.setdefault(domain, []).append(name)
        logger.info(f"[skill_registry] 注册 Skill: '{name}' -> domains: {domains or ['general']}")

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def get_for_domain(self, domain: str) -> List[Skill]:
        """获取某 domain 可用的 Skill 列表（general + domain 特定）"""
        names = self._domain_mapping.get(domain, []) + self._domain_mapping.get("general", [])
        seen: set = set()
        result: List[Skill] = []
        for n in names:
            if n not in seen and n in self._skills:
                seen.add(n)
                result.append(self._skills[n])
        return result

    def get_tool_definitions(self, domain: str) -> List[dict]:
        """获取 OpenAI 兼容的 tools 列表"""
        return [s.definition.to_openai_tool() for s in self.get_for_domain(domain)]

    def get_skill_definitions(self, domain: str) -> List[SkillDefinition]:
        """获取 Skill 定义列表（用于生成 system prompt）"""
        return [s.definition for s in self.get_for_domain(domain)]

    def execute(self, name: str, params: Dict) -> SkillResult:
        """执行指定 Skill"""
        skill = self._skills.get(name)
        if not skill:
            return SkillResult(skill_name=name, success=False, error=f"Skill '{name}' 不存在")
        return skill(params)

    def list_all(self) -> List[str]:
        return list(self._skills.keys())

    def load_all(self, skills_root: str, domains: Optional[List[str]] = None) -> int:
        """从指定目录加载所有 Skill 并注册"""
        skills = SkillLoader.load_from_directory(skills_root)
        for skill in skills:
            self.register(skill, domains)
        return len(skills)


# 全局单例
skill_registry = SkillRegistry()