"""
CDC 管理 API — 增量同步的启停、状态查询
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Optional
from pydantic import BaseModel

from cdc.cdc_manager import cdc_manager
from system.logger import logger

router = APIRouter(prefix="/api/cdc", tags=["cdc"])


class CdcStartRequest(BaseModel):
    database_name: str
    topic_prefix: str = "openpalantir"


@router.post("/{connection_id}/start", response_model=Dict)
def start_cdc(connection_id: str, req: CdcStartRequest):
    """启动增量同步"""
    try:
        # 启动前检测断层
        gap_check = cdc_manager.check_stream_continuity(connection_id, req.database_name)
        if gap_check.get("has_gap"):
            return {
                "status": "gap_detected",
                "message": gap_check["message"],
                "suggestion": "请先执行全量导入重建基线，再启动增量同步",
            }

        result = cdc_manager.start(
            connection_id=connection_id,
            database_name=req.database_name,
            topic_prefix=req.topic_prefix,
        )
        return result
    except Exception as e:
        logger.error(f"启动 CDC 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{connection_id}/stop", response_model=Dict)
def stop_cdc(connection_id: str, database_name: str):
    """停止增量同步"""
    try:
        result = cdc_manager.stop(connection_id, database_name)
        return result
    except Exception as e:
        logger.error(f"停止 CDC 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{connection_id}/pause", response_model=Dict)
def pause_cdc(connection_id: str, database_name: str):
    """暂停增量同步"""
    try:
        result = cdc_manager.pause(connection_id, database_name)
        return result
    except Exception as e:
        logger.error(f"暂停 CDC 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{connection_id}/status", response_model=Optional[Dict])
def get_cdc_status(connection_id: str, database_name: str):
    """查询同步状态"""
    try:
        result = cdc_manager.get_status(connection_id, database_name)
        if not result:
            raise HTTPException(status_code=404, detail="未找到同步状态记录")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询 CDC 状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statuses", response_model=list)
def get_all_cdc_statuses():
    """查询所有同步状态"""
    try:
        return cdc_manager.get_all_statuses()
    except Exception as e:
        logger.error(f"查询所有 CDC 状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
