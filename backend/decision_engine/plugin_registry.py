from typing import Dict, Optional

from system.logger import logger
from decision_engine.plugins.base_decision_plugin import BaseDecisionPlugin
from decision_engine.plugins.workforce_plugin import WorkforcePlugin


class PluginRegistry:
    def __init__(self):
        self._plugins: Dict[str, BaseDecisionPlugin] = {}
        self._register(WorkforcePlugin())

    def _register(self, plugin: BaseDecisionPlugin):
        self._plugins[plugin.domain] = plugin
        logger.info(f"[registry] registered plugin domain={plugin.domain}")

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
