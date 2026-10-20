"""
模型配置服务

提供模型配置的CRUD操作，管理本地和云端模型的配置信息。
"""

from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from model_management.context_probe import probe_context_length
from model_management.model_client import ModelClient
from models.model import API_KEY_MASK, ModelInfo
from system.logger import logger
from datetime import datetime


# 创建模型时未填 api_url 的按类型默认值
DEFAULT_API_URLS = {
    'local': 'http://localhost:11434',
    'cloud': 'https://api.openai.com/v1',
}


class ModelService:
    """模型配置 CRUD 服务，支持本地模型（Ollama）和云端模型（OpenAI 兼容 API）。"""

    @staticmethod
    def create_model(db: Session, model_data: Dict[str, Any]) -> ModelInfo:
        """
        创建新的模型配置
        
        Args:
            db: 数据库会话
            model_data: 模型配置数据，包含以下字段：
                - name: 模型名称（必需）
                - type: 模型类型，'local' 或 'cloud'（必需）
                - models: 支持的模型列表（可选）
                - api_url: API地址（可选，缺省按类型取默认值）
                - api_key: API密钥（可选）
                - enabled: 是否启用（可选，默认False）
                - status: 状态（可选）
                - context_length: 上下文窗口 token 数（可选，缺省待探测）
                
        Returns:
            ModelInfo: 创建的模型配置对象
            
        Raises:
            ValueError: 当缺少必需字段时
        """
        if not model_data.get('name'):
            raise ValueError("模型名称不能为空")
        if not model_data.get('type'):
            raise ValueError("模型类型不能为空")
            
        try:
            db_model = ModelInfo(
                name=model_data['name'],
                type=model_data['type'],
                status=model_data.get('status', 'unknown'),
                models=model_data.get('models', []),
                enabled=model_data.get('enabled', False),
                api_url=model_data.get('api_url') or DEFAULT_API_URLS.get(model_data['type'], ''),
                api_key=model_data.get('api_key', ''),
                context_length=model_data.get('context_length')
            )
            db.add(db_model)
            db.commit()
            db.refresh(db_model)
            logger.info(f"创建模型配置成功: {db_model.name}")
            return db_model
        except Exception as e:
            db.rollback()
            logger.error(f"创建模型配置失败: {e}")
            raise
    
    @staticmethod
    def get_model(db: Session, model_id: int) -> Optional[ModelInfo]:
        """
        根据ID获取模型配置
        
        Args:
            db: 数据库会话
            model_id: 模型ID
            
        Returns:
            ModelInfo: 模型配置对象，不存在则返回None（DB 故障直接上抛，不冒充「不存在」）
        """
        return db.query(ModelInfo).filter(ModelInfo.id == model_id).first()
    
    @staticmethod
    def get_all_models(db: Session) -> List[ModelInfo]:
        """
        获取所有模型配置
        
        Args:
            db: 数据库会话
            
        Returns:
            List[ModelInfo]: 模型配置列表
        """
        return db.query(ModelInfo).all()
    
    @staticmethod
    def update_model(db: Session, model_id: int, model_data: Dict[str, Any]) -> Optional[ModelInfo]:
        """
        更新模型配置
        
        Args:
            db: 数据库会话
            model_id: 模型ID
            model_data: 要更新的字段数据
            
        Returns:
            ModelInfo: 更新后的模型配置对象，不存在则返回None
        """
        try:
            db_model = db.query(ModelInfo).filter(ModelInfo.id == model_id).first()
            if not db_model:
                logger.warning(f"模型配置不存在: {model_id}")
                return None
            
            # 更新允许修改的字段
            updatable_fields = ['name', 'type', 'status', 'models', 'enabled', 'api_url', 'api_key',
                                'context_length']
            for key, value in model_data.items():
                if key in updatable_fields:
                    if key == 'api_key' and isinstance(value, str) and API_KEY_MASK in value:
                        # 前端原样回传的掩码值不落库：保留既有密钥
                        value = db_model.api_key or ''
                    setattr(db_model, key, value)
            
            db_model.update_time = datetime.now()
            db.commit()
            db.refresh(db_model)
            logger.info(f"更新模型配置成功: {db_model.name}")
            return db_model
        except Exception as e:
            db.rollback()
            logger.error(f"更新模型配置失败: {e}")
            raise
    
    @staticmethod
    def delete_model(db: Session, model_id: int) -> bool:
        """
        删除模型配置
        
        Args:
            db: 数据库会话
            model_id: 模型ID
            
        Returns:
            bool: 删除成功返回True，不存在返回False
        """
        try:
            db_model = db.query(ModelInfo).filter(ModelInfo.id == model_id).first()
            if not db_model:
                logger.warning(f"模型配置不存在: {model_id}")
                return False
            
            db.delete(db_model)
            db.commit()
            logger.info(f"删除模型配置成功: {model_id}")
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"删除模型配置失败: {e}")
            raise
    
    @staticmethod
    def enable_model(db: Session, model_id: int) -> Optional[ModelInfo]:
        """
        启用指定模型，同时禁用其他所有模型（单active约束）

        Args:
            db: 数据库会话
            model_id: 要启用的模型ID

        Returns:
            ModelInfo: 启用后的模型对象，不存在则返回None
        """
        try:
            model = db.query(ModelInfo).filter(ModelInfo.id == model_id).first()
            if not model:
                logger.warning(f"模型配置不存在: {model_id}")
                return None

            # 禁用所有模型
            db.query(ModelInfo).update({"enabled": False})
            # 启用指定模型
            model.enabled = True
            db.commit()
            db.refresh(model)
            logger.info(f"启用模型成功: {model.name} (id={model_id})，其他模型已禁用")
            return model
        except Exception as e:
            db.rollback()
            logger.error(f"启用模型失败: {e}")
            raise

    @staticmethod
    def get_available_model(db: Session) -> Optional[Dict[str, Any]]:
        """
        获取已启用的可用模型配置

        查询已启用（enabled=True）且状态为"available"的模型，返回其配置字典。

        Args:
            db: 数据库会话

        Returns:
            Dict: 已启用可用模型的配置字典（api_key 为真实密钥）；
                  没有启用中的可用模型时返回 None（DB 故障直接上抛，不冒充「无模型」）
        """
        available_models = db.query(ModelInfo).filter(
            ModelInfo.enabled == True,
            ModelInfo.status == "available"
        ).all()

        if not available_models:
            logger.error("没有可用的已启用模型，请先在模型管理中启用一个可用模型")
            return None

        # 单启用约束（enable_model 保证），取第一个
        selected_model = available_models[0]
        logger.info(f"发现可用模型: {selected_model.name}")

        # 内部消费方需要真实密钥，to_dict 的掩码值仅用于界面展示
        config = selected_model.to_dict()
        # REST/界面契约用 model_type，内部配置统一用 type —— 映射只在这条出口做一次
        config["type"] = config.pop("model_type")
        config["api_key"] = selected_model.api_key
        return config

    @staticmethod
    def test_and_update_connection(
        db: Session, model_id: int, api_url: str, api_key: str,
        model_name: str = None
    ) -> Dict[str, Any]:
        """测试模型连接并更新状态。

        封装：获取模型 → 构建 test_config → 实例化 ModelClient → 测试 → 更新状态

        连接可用时顺带向服务端探测上下文窗口并落库；探测不到则保留库中记录值。
        """
        model_info = ModelService.get_model(db, model_id)
        if not model_info:
            raise ValueError("模型不存在")

        if not api_key or API_KEY_MASK in api_key:
            # 掩码回显 / 空密钥 → 用库里的真实密钥测试
            api_key = model_info.api_key or ''

        test_config = {
            "type": model_info.type,
            "models": model_info.models,
            "api_url": api_url,
            "api_key": api_key,
            "model_name": model_name or (model_info.models[0] if model_info.models else None),
            "context_length": model_info.context_length,
        }

        client = ModelClient(test_config)
        connection_status = "available" if client.test_connection() else "unavailable"
        message = "连接测试成功" if connection_status == "available" else "连接测试失败"

        updates = {"status": connection_status}
        probed = None
        if connection_status == "available":
            probed = probe_context_length(test_config)
            if probed:
                updates["context_length"] = probed
                logger.info(f"探测到模型 {test_config['model_name']} 上下文窗口: {probed}")
            else:
                logger.warning(
                    f"未能探测到模型 {test_config['model_name']} 的上下文窗口，"
                    f"沿用库中记录值 {model_info.context_length}"
                )

        ModelService.update_model(db, model_id, updates)
        logger.info(f"测试模型连接完成: model_id={model_id}, status={connection_status}")

        return {
            "connection_status": connection_status,
            "message": message,
            "context_length": probed or model_info.context_length,
        }
