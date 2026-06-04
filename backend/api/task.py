from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from task_management.task_manager import task_manager
from system.logger import logger

router = APIRouter(tags=["task"])

@router.post("/create")
def create_task(task_data: Dict[str, Any]):
    """创建新任务"""
    try:
        # 记录入参
        task_type = task_data.get("task_type")
        payload = task_data.get("payload")
        logger.info(f"接收创建任务请求: task_type={task_type}")
        
        if not task_type or not payload:
            logger.error("创建任务失败: 缺少 task_type 或 payload")
            raise HTTPException(status_code=400, detail="Missing task_type or payload")
        
        task_id = task_manager.create_task(task_type, payload)
        logger.info(f"创建任务成功: task_id={task_id}")
        return {"task_id": task_id, "status": "pending"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/list")
def list_tasks():
    """列出所有任务"""
    try:
        # 记录入参
        logger.info("接收列出所有任务请求")
        
        tasks = task_manager.list_tasks()
        logger.info(f"列出所有任务成功: 共 {len(tasks)} 个任务")
        return {"tasks": tasks}
    except Exception as e:
        logger.error(f"列出所有任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{task_id}")
def get_task_status(task_id: str):
    """获取任务状态"""
    try:
        # 记录入参
        #logger.info(f"接收获取任务状态请求: task_id={task_id}")
        
        task_status = task_manager.get_task_status(task_id)
        if not task_status:
            logger.error(f"获取任务状态失败: 任务不存在 task_id={task_id}")
            raise HTTPException(status_code=404, detail="Task not found")
        
        logger.debug(f"获取任务状态成功: task_id={task_id}, status={task_status.get('status')}")
        return task_status
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务状态失败: task_id={task_id}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{task_id}/result")
def get_task_result(task_id: str):
    """获取任务结果"""
    try:
        # 记录入参
        #logger.info(f"接收获取任务结果请求: task_id={task_id}")
        
        task = task_manager.get_task(task_id)
        if not task:
            logger.error(f"获取任务结果失败: 任务不存在 task_id={task_id}")
            raise HTTPException(status_code=404, detail="Task not found")
        
        if task.status != "completed":
            logger.error(f"获取任务结果失败: 任务未完成 task_id={task_id}, status={task.status}")
            raise HTTPException(status_code=400, detail="Task not completed yet")
        
        logger.info(f"获取任务结果成功: task_id={task_id}")
        return {
            "task_id": task_id,
            "status": task.status,
            "result": task.result,
            "completed_at": task.completed_at
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务结果失败: task_id={task_id}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{task_id}")
def delete_task(task_id: str):
    """删除任务"""
    try:
        # 记录入参
        logger.info(f"接收删除任务请求: task_id={task_id}")
        
        success = task_manager.delete_task(task_id)
        if not success:
            logger.error(f"删除任务失败: 任务不存在 task_id={task_id}")
            raise HTTPException(status_code=404, detail="Task not found")
        
        logger.info(f"删除任务成功: task_id={task_id}")
        return {"status": "success", "message": "Task deleted successfully"}
    except ValueError as e:
        logger.error(f"删除任务失败: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除任务失败: task_id={task_id}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{task_id}/stop")
def stop_task(task_id: str):
    """停止任务"""
    try:
        # 记录入参
        logger.info(f"接收停止任务请求: task_id={task_id}")
        
        success = task_manager.stop_task(task_id)
        if not success:
            logger.error(f"停止任务失败: 任务不存在或状态不允许停止 task_id={task_id}")
            raise HTTPException(status_code=400, detail="Task not found or cannot be stopped")
        
        logger.info(f"停止任务成功: task_id={task_id}")
        return {"status": "success", "message": "Task stopped successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"停止任务失败: task_id={task_id}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))