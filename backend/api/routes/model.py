"""
模型管理API路由

提供模型配置的CRUD操作和连接测试功能。
"""

from fastapi import APIRouter, HTTPException, Body
from config.database import SessionLocal
from typing import Optional
from system.logger import logger
from model_management import ModelService, ModelClient

router = APIRouter()


@router.get("/models")
def get_all_models():
    """
    获取所有模型列表
    
    Returns:
        dict: 包含所有模型信息的响应
            - status: 响应状态，success 或 error
            - models: 模型列表
    """
    try:
        logger.info("接收获取所有模型列表请求")
        
        db = SessionLocal()
        try:
            models = ModelService.get_all_models(db)
            logger.info(f"获取所有模型列表成功: 共 {len(models)} 个模型")
            return {
                "status": "success",
                "models": [model.to_dict() for model in models]
            }
        finally:
            db.close()
    except Exception as e:
        logger.error(f"获取所有模型列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {str(e)}")


@router.get("/models/{model_id}")
def get_model(model_id: int):
    """
    获取单个模型详情
    
    Args:
        model_id: 模型ID
    
    Returns:
        dict: 包含模型详细信息的响应
    """
    try:
        logger.info(f"接收获取模型详情请求: model_id={model_id}")
        
        db = SessionLocal()
        try:
            model = ModelService.get_model(db, model_id)
            if not model:
                logger.error(f"获取模型详情失败: 模型不存在 model_id={model_id}")
                raise HTTPException(status_code=404, detail="模型不存在")
            
            logger.info(f"获取模型详情成功: model_id={model_id}")
            return {
                "status": "success",
                "model": model.to_dict()
            }
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取模型详情失败: model_id={model_id}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取模型详情失败: {str(e)}")


@router.post("/models")
def create_model(
    name: str = Body(...),
    type: str = Body(...),
    status: str = Body("unknown"),
    models: list = Body([]),
    enabled: bool = Body(False),
    api_url: str = Body(None),
    api_key: str = Body("")
):
    """
    创建新模型
    
    Args:
        name: 模型名称
        type: 模型类型，local 或 cloud
        status: 模型状态，默认为 unknown
        models: 模型列表
        priority: 模型优先级
        api_url: API地址
        api_key: API密钥
    
    Returns:
        dict: 创建结果响应
    """
    try:
        logger.info(f"接收创建模型请求: name={name}, type={type}")
        
        # 验证类型值
        if type not in ['local', 'cloud']:
            logger.error(f"创建模型失败: 无效的模型类型 type={type}")
            raise HTTPException(status_code=400, detail="无效的模型类型，必须是 'local' 或 'cloud'")
        
        # 设置默认值
        if api_url is None:
            api_url = "http://localhost:11434" if type == "local" else "https://api.openai.com/v1"

        model_data = {
            "name": name,
            "type": type,
            "status": status,
            "models": models,
            "enabled": enabled,
            "api_url": api_url,
            "api_key": api_key
        }
        
        db = SessionLocal()
        try:
            new_model = ModelService.create_model(db, model_data)
            logger.info(f"创建模型成功: model_id={new_model.id}, name={name}")
            return {
                "status": "success",
                "message": "模型创建成功",
                "model": new_model.to_dict()
            }
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建模型失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建模型失败: {str(e)}")


@router.put("/models/{model_id}")
def update_model(
    model_id: int,
    name: str = Body(None),
    type: str = Body(None),
    status: str = Body(None),
    models: list = Body(None),
    enabled: bool = Body(None),
    api_url: str = Body(None),
    api_key: str = Body(None)
):
    """
    更新模型
    
    Args:
        model_id: 模型ID
        name: 模型名称（可选）
        type: 模型类型（可选）
        status: 模型状态（可选）
        models: 模型列表（可选）
        priority: 模型优先级（可选）
        api_url: API地址（可选）
        api_key: API密钥（可选）
    
    Returns:
        dict: 更新结果响应
    """
    try:
        logger.info(f"接收更新模型请求: model_id={model_id}")
        
        # 验证类型值
        if type is not None and type not in ['local', 'cloud']:
            logger.error(f"更新模型失败: 无效的模型类型 type={type}")
            raise HTTPException(status_code=400, detail="无效的模型类型，必须是 'local' 或 'cloud'")
        
        model_data = {}
        if name is not None:
            model_data["name"] = name
        if type is not None:
            model_data["type"] = type
        if status is not None:
            model_data["status"] = status
        if models is not None:
            model_data["models"] = models
        if enabled is not None:
            model_data["enabled"] = enabled
        if api_url is not None:
            model_data["api_url"] = api_url
        if api_key is not None:
            model_data["api_key"] = api_key
        
        db = SessionLocal()
        try:
            updated_model = ModelService.update_model(db, model_id, model_data)
            if not updated_model:
                logger.error(f"更新模型失败: 模型不存在 model_id={model_id}")
                raise HTTPException(status_code=404, detail="模型不存在")
            
            logger.info(f"更新模型成功: model_id={model_id}")
            return {
                "status": "success",
                "message": "模型更新成功",
                "model": updated_model.to_dict()
            }
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新模型失败: model_id={model_id}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新模型失败: {str(e)}")


@router.delete("/models/{model_id}")
def delete_model(model_id: int):
    """
    删除模型
    
    Args:
        model_id: 模型ID
    
    Returns:
        dict: 删除结果响应
    """
    try:
        logger.info(f"接收删除模型请求: model_id={model_id}")
        
        db = SessionLocal()
        try:
            success = ModelService.delete_model(db, model_id)
            if not success:
                logger.error(f"删除模型失败: 模型不存在 model_id={model_id}")
                raise HTTPException(status_code=404, detail="模型不存在")
            
            logger.info(f"删除模型成功: model_id={model_id}")
            return {
                "status": "success",
                "message": "模型删除成功"
            }
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除模型失败: model_id={model_id}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除模型失败: {str(e)}")


@router.post("/models/{model_id}/test-connection")
def test_model_connection(
    model_id: int,
    api_url: str = Body(...),
    api_key: str = Body(""),
    model: str = Body(None)
):
    """测试模型连接"""
    try:
        from config.database import get_session

        with get_session() as db:
            result = ModelService.test_and_update_connection(
                db, model_id, api_url, api_key, model
            )
            status = "success" if result["connection_status"] == "available" else "error"
            return {"status": status, **result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
        raise
    except Exception as e:
        logger.error(f"测试模型连接失败: model_id={model_id}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"测试连接失败: {str(e)}")


@router.post("/models/{model_id}/enable")
def enable_model(model_id: int):
    """
    启用指定模型，同时禁用其他所有模型

    Args:
        model_id: 要启用的模型ID

    Returns:
        dict: 启用结果响应
    """
    try:
        logger.info(f"接收启用模型请求: model_id={model_id}")

        db = SessionLocal()
        try:
            model = ModelService.enable_model(db, model_id)
            if not model:
                logger.error(f"启用模型失败: 模型不存在 model_id={model_id}")
                raise HTTPException(status_code=404, detail="模型不存在")

            logger.info(f"启用模型成功: model_id={model_id}, name={model.name}")
            return {
                "status": "success",
                "message": f"模型 {model.name} 已启用",
            }
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启用模型失败: model_id={model_id}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启用模型失败: {str(e)}")
