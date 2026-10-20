"""上下文窗口探测 —— 选定模型时向服务端问一次真实窗口，问不到由调用方回落默认值

云端走 OpenAI 兼容的 GET /models（OpenRouter 等在条目里带 context_length），
本地走 Ollama 的 POST /api/show（gguf 元数据里是 {arch}.context_length，
退化情况只有 Modelfile 参数行里的 num_ctx）。
"""
from typing import Any, Dict, Optional

import requests
from system.logger import logger

PROBE_TIMEOUT = 15

# 各家字段名不统一，按优先级取第一个整数
_CLOUD_CONTEXT_KEYS = ("context_length", "max_input_tokens", "max_context_window", "n_ctx")


def _find_int(value: Any) -> Optional[int]:
    """在嵌套 dict/list 里找第一个像窗口大小的正整数键值（键名按 _CLOUD_CONTEXT_KEYS 优先）"""
    if isinstance(value, dict):
        for key in _CLOUD_CONTEXT_KEYS:
            got = value.get(key)
            if isinstance(got, int) and not isinstance(got, bool) and got > 0:
                return got
        for nested in value.values():
            found = _find_int(nested)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_int(item)
            if found:
                return found
    return None


def _probe_cloud(api_url: str, api_key: str, model_name: Optional[str]) -> Optional[int]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = requests.get(f"{api_url}/models", headers=headers, timeout=PROBE_TIMEOUT)
    if response.status_code != 200:
        logger.warning(f"[context_probe] /models 返回 HTTP {response.status_code}")
        return None
    payload = response.json()
    entries = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return None
    if model_name:
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id") == model_name:
                return _find_int(entry)
        return None
    return _find_int(entries)


def _probe_local(api_url: str, model_name: Optional[str]) -> Optional[int]:
    body = {"model": model_name} if model_name else {}
    response = requests.post(f"{api_url}/api/show", json=body, timeout=PROBE_TIMEOUT)
    if response.status_code != 200:
        logger.warning(f"[context_probe] /api/show 返回 HTTP {response.status_code}")
        return None
    payload = response.json()
    model_info = payload.get("model_info") or {}
    # gguf 键形如 "qwen2.context_length"，架构前缀不固定
    sizes = [v for k, v in model_info.items()
             if k.endswith(".context_length") and isinstance(v, int) and v > 0]
    if sizes:
        return max(sizes)
    for line in (payload.get("parameters") or "").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == "num_ctx":
            try:
                value = int(parts[1])
                return value if value > 0 else None
            except ValueError:
                return None
    return None


def probe_context_length(model_config: Dict[str, Any]) -> Optional[int]:
    """问服务端该模型的上下文窗口；探测不到返回 None（由 ModelConfig 兜底默认值）"""
    model_name = model_config.get("model_name") or (model_config.get("models") or [None])[0]
    api_url = (model_config.get("api_url") or "").rstrip("/")
    if not api_url:
        return None
    try:
        if model_config.get("type") == "local":
            return _probe_local(api_url, model_name)
        return _probe_cloud(api_url, model_config.get("api_key") or "", model_name)
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"[context_probe] 探测失败: {e}")
        return None
