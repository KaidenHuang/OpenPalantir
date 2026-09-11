"""决策引擎配置加载器 — 从 YAML 文件加载，带硬编码兜底默认值"""
import os

import yaml

from system.logger import logger

_DEFAULTS = {
    "agentic": {
        "max_turns": 15,
        "max_result_chars": 5000,
        "confidence_threshold": 0.7,
    },
    "context": {
        "max_observations": 10,
        "compress_batch": 5,
        "keep_groups": 3,
    },
    "conversation": {
        "max_history_turns": 5,
    },
    "forced_synthesis": {
        "max_items": 12,
        "preview_chars": 1200,
        "raw_fallback_chars": 1000,
    },
    "multi_agent": {
        "critic_threshold": 0.6,
        "critic_evidence": 8,
        "critic_max_issues": 3,
        "hallucination_penalty": -0.3,
        "planner_max_subtasks": 6,
    },
    "memory": {
        "short_term_ttl_days": 7,
        "promotion_check_days": 6,
        "long_term_max_items": 20,
        "long_term_max_chars": 500,
        "retrieve_limit": 5,
    },
    "tools": {
        "search_max_limit": 50,
        "search_default_limit": 10,
        "neighbors_max_limit": 100,
        "neighbors_default_limit": 20,
        "summaries_max_limit": 10,
        "summaries_default_limit": 5,
        "subgraph_max_hops": 5,
        "subgraph_max_limit": 200,
    },
}


def load_decision_engine_config() -> dict:
    """从 YAML 配置文件加载，与硬编码默认值深度合并"""
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "decision_engine.yaml",
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        merged = {}
        for section, defaults in _DEFAULTS.items():
            merged[section] = {**defaults, **(user_config.get(section) or {})}
        logger.info(f"[config] 决策引擎配置加载成功: {config_path}")
        return merged
    except FileNotFoundError:
        logger.warning(f"[config] 配置文件不存在: {config_path}，使用默认值")
        return {k: dict(v) for k, v in _DEFAULTS.items()}
    except Exception as e:
        logger.warning(f"[config] 决策引擎配置加载失败，使用默认值: {e}")
        return {k: dict(v) for k, v in _DEFAULTS.items()}


# 模块级单例
_config = None


def get_config() -> dict:
    """获取决策引擎配置（首次调用加载，后续返回缓存）"""
    global _config
    if _config is None:
        _config = load_decision_engine_config()
    return _config
