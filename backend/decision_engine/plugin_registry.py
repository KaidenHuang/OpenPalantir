import os
from typing import Dict, Optional

from system.logger import logger
from decision_engine.plugins.base_decision_plugin import BaseDecisionPlugin
from decision_engine.plugins.workforce_plugin import WorkforcePlugin


class PluginRegistry:
    def __init__(self):
        self._plugins: Dict[str, BaseDecisionPlugin] = {}
        self._register(WorkforcePlugin())
        self._init_skills()

    def _register(self, plugin: BaseDecisionPlugin):
        self._plugins[plugin.domain] = plugin
        logger.info(f"[registry] registered plugin domain={plugin.domain}")

    @staticmethod
    def _init_skills():
        """初始化 Skill 系统：扫描并加载 skills/ 目录下的所有 Skill"""
        from decision_engine.tool_manager.skill.skill_registry import skill_registry
        skills_root = os.path.join(os.path.dirname(__file__), "skills")
        count = skill_registry.load_all(skills_root, domains=["general", "workforce"])
        logger.info(f"[registry] loaded {count} skills from {skills_root}")

    def resolve(self, domain: Optional[str] = None) -> BaseDecisionPlugin:
        domain = domain or "workforce"
        plugin = self._plugins.get(domain)
        if plugin:
            return plugin
        # Fallback
        if self._plugins:
            logger.warning(f"[registry] domain '{domain}' not found, fallback to {list(self._plugins.keys())[0]}")
            return list(self._plugins.values())[0]
        raise RuntimeError("No plugins registered")

    def all_domains(self) -> list:
        return list(self._plugins.keys())


plugin_registry = PluginRegistry()
