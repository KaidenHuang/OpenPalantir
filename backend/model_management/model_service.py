"""
模型配置服务

提供模型配置的CRUD操作，管理本地和云端模型的配置信息。
"""

from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from models.model import ModelInfo
from system.logger import logger
from datetime import datetime


class ModelService:
    """
    模型配置服务类
    
    提供模型配置的增删改查操作，支持本地模型（Ollama）和云端模型（OpenAI兼容API）。
    
    Attributes:
        None
        
    Methods:
        create_model: 创建新的模型配置
        get_model: 根据ID获取模型配置
        get_model_by_name: 根据名称获取模型配置
        get_all_models: 获取所有模型配置
        update_model: 更新模型配置
        delete_model: 删除模型配置
        get_active_model: 获取当前激活的模型配置
    """
    
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
                - api_url: API地址（可选）
                - api_key: API密钥（可选）
                - enabled: 是否启用（可选，默认False）
                - status: 状态（可选）
                
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
                type=model_data.get('type', 'cloud'),
                status=model_data.get('status', 'unknown'),
                models=model_data.get('models', []),
                enabled=model_data.get('enabled', False),
                api_url=model_data.get('api_url', ''),
                api_key=model_data.get('api_key', '')
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
            ModelInfo: 模型配置对象，不存在则返回None
        """
        try:
            return db.query(ModelInfo).filter(ModelInfo.id == model_id).first()
        except Exception as e:
            logger.error(f"获取模型配置失败: {e}")
            return None
    
    @staticmethod
    def get_model_by_name(db: Session, name: str) -> Optional[ModelInfo]:
        """
        根据名称获取模型配置
        
        Args:
            db: 数据库会话
            name: 模型名称
            
        Returns:
            ModelInfo: 模型配置对象，不存在则返回None
        """
        try:
            return db.query(ModelInfo).filter(ModelInfo.name == name).first()
        except Exception as e:
            logger.error(f"根据名称获取模型配置失败: {e}")
            return None
    
    @staticmethod
    def get_all_models(db: Session) -> List[ModelInfo]:
        """
        获取所有模型配置
        
        Args:
            db: 数据库会话
            
        Returns:
            List[ModelInfo]: 模型配置列表
        """
        try:
            return db.query(ModelInfo).all()
        except Exception as e:
            logger.error(f"获取所有模型配置失败: {e}")
            return []
    
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
            updatable_fields = ['name', 'type', 'status', 'models', 'enabled', 'api_url', 'api_key']
            for key, value in model_data.items():
                if key in updatable_fields:
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
    def get_active_model(db: Session) -> Optional[ModelInfo]:
        """
        获取当前激活的模型配置
        
        优先返回状态为'active'的模型，如果没有则返回第一个本地模型。
        
        Args:
            db: 数据库会话
            
        Returns:
            ModelInfo: 激活的模型配置对象，不存在则返回None
        """
        try:
            # 优先查找状态为active的模型
            active_model = db.query(ModelInfo).filter(ModelInfo.status == 'active').first()
            if active_model:
                return active_model
            
            # 如果没有active模型，返回第一个本地模型
            local_model = db.query(ModelInfo).filter(ModelInfo.type == 'local').first()
            if local_model:
                return local_model
            
            # 如果没有本地模型，返回第一个模型
            return db.query(ModelInfo).first()
        except Exception as e:
            logger.error(f"获取激活模型失败: {e}")
            return None
    
    @staticmethod
    def get_model_config_dict(db: Session, model_id: Optional[int] = None, model_name: Optional[str] = None) -> Dict[str, Any]:
        """
        获取模型配置字典
        
        根据ID或名称获取模型配置，返回字典格式，便于传递给ModelClient。
        
        Args:
            db: 数据库会话
            model_id: 模型ID（可选）
            model_name: 模型名称（可选）
            
        Returns:
            Dict: 模型配置字典，包含以下字段：
                - type: 模型类型
                - models: 支持的模型列表
                - api_url: API地址
                - api_key: API密钥
                - priority: 优先级
        """
        model = None
        if model_id:
            model = ModelService.get_model(db, model_id)
        elif model_name:
            model = ModelService.get_model_by_name(db, model_name)
        else:
            model = ModelService.get_active_model(db)
        
        if model:
            return model.to_dict()
        
        # 返回默认配置
        return {
            'type': 'local',
            'models': ['qwen2.5:7b'],
            'api_url': 'http://localhost:11434',
            'api_key': '',
        }
    
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
    def get_available_model(db: Session) -> Dict[str, Any]:
        """
        获取已启用的可用模型配置

        查询已启用（enabled=True）且状态为"available"的模型，返回其配置字典。

        Args:
            db: 数据库会话

        Returns:
            Dict: 已启用可用模型的配置字典

        Raises:
            ValueError: 没有已启用的可用模型时抛出
        """
        try:
            # 查询已启用的可用模型（enabled=True 且 status="available"）
            available_models = db.query(ModelInfo).filter(
                ModelInfo.enabled == True,
                ModelInfo.status == "available"
            ).all()

            if not available_models:
                logger.error("没有可用的已启用模型")
                raise ValueError("没有可用的已启用模型，请先在模型管理中启用一个可用模型")

            # 返回第一个（也是唯一一个）启用模型
            selected_model = available_models[0]
            logger.info(f"发现可用模型: {selected_model.name}")
            
            # 返回模型配置字典
            return selected_model.to_dict()
            
        except Exception as e:
            logger.error(f"获取可用模型失败: {e}")
            return None
    
    @staticmethod
    def check_model_available(db: Session) -> bool:
        """
        检查是否有可用的模型
        
        Args:
            db: 数据库会话
            
        Returns:
            bool: 有可用模型返回True，否则返回False
        """
        try:
            count = db.query(ModelInfo).filter(
                ModelInfo.status == "available",
                ModelInfo.enabled == True
            ).count()
            return count > 0
        except Exception as e:
            logger.error(f"检查可用模型失败: {e}")
            return False
