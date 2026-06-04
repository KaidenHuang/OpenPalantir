"""
模型管理模块

本模块提供统一的模型配置管理和模型调用接口，支持本地模型（Ollama）和云端模型（OpenAI兼容API）。

主要组件：
- ModelService: 模型配置的CRUD服务
- ModelClient: 统一的模型调用客户端
- ModelConfig: 模型配置数据类

使用示例：
    from model_management import ModelService, ModelClient
    
    # 获取模型配置
    model_config = ModelService.get_model_by_name(db, "Ollama")
    
    # 创建模型客户端
    client = ModelClient(model_config.to_dict())
    
    # 调用模型（返回JSON格式）
    result = client.call_json("请分析这段文本...")
"""

from model_management.model_service import ModelService
from model_management.model_client import ModelClient, ModelConfig

__all__ = ['ModelService', 'ModelClient', 'ModelConfig']
