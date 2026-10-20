"""
模型管理模块

本模块提供统一的模型配置管理和模型调用接口，支持本地模型（Ollama）和云端模型（OpenAI兼容API）。

主要组件：
- ModelService: 模型配置的CRUD服务
- ModelClient: 统一的模型调用客户端
- ModelConfig: 模型配置数据类
- probe_context_length: 向服务端探测模型上下文窗口

使用示例：
    from model_management import ModelService, ModelClient

    model_config = ModelService.get_available_model(db)
    client = ModelClient(model_config)
    result = client.call_json("请分析这段文本...")
"""

from model_management.model_service import ModelService
from model_management.model_client import ModelClient, ModelConfig
from model_management.context_probe import probe_context_length

__all__ = ['ModelService', 'ModelClient', 'ModelConfig', 'probe_context_length']
