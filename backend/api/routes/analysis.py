from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from analysis_engine.analyzer import analyzer
from system.logger import logger

router = APIRouter()

class PathAnalysisRequest(BaseModel):
    source_entity: str
    target_entity: str
    k: int = 1
    weighted: bool = False

@router.post("/path")
async def analyze_path(request: PathAnalysisRequest = Body(...)):
    """分析路径"""
    try:
        # 记录入参
        logger.info(f"接收分析路径请求: source_entity={request.source_entity}, target_entity={request.target_entity}, k={request.k}, weighted={request.weighted}")
        
        result = analyzer.analyze_path(request.source_entity, request.target_entity, k=request.k, weighted=request.weighted)
        logger.info(f"分析路径成功: source_entity={request.source_entity}, target_entity={request.target_entity}, k={request.k}, weighted={request.weighted}")
        return result
    except Exception as e:
        logger.error(f"分析路径失败: source_entity={request.source_entity}, target_entity={request.target_entity}, k={request.k}, weighted={request.weighted}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/community")
async def analyze_community():
    """分析社区"""
    try:
        # 记录入参
        logger.info("接收分析社区请求")
        
        result = analyzer.analyze_community()
        logger.info("分析社区成功")
        return result
    except Exception as e:
        logger.error(f"分析社区失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

class CentralityAnalysisRequest(BaseModel):
    centrality_types: list = None

class TrendAnalysisRequest(BaseModel):
    time_range: str
    metrics: list = None

class ReportRequest(BaseModel):
    analysis_type: str
    format: str = 'html'

@router.post("/centrality")
async def analyze_centrality(request: CentralityAnalysisRequest = Body(...)):
    """分析中心性"""
    try:
        # 记录入参
        logger.info(f"接收分析中心性请求: centrality_types={request.centrality_types}")
        
        result = analyzer.analyze_centrality(centrality_types=request.centrality_types)
        logger.info("分析中心性成功")
        return result
    except Exception as e:
        logger.error(f"分析中心性失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/trend")
async def analyze_trend(request: TrendAnalysisRequest = Body(...)):
    """分析趋势"""
    try:
        # 记录入参
        logger.info(f"接收分析趋势请求: time_range={request.time_range}, metrics={request.metrics}")
        
        result = analyzer.analyze_trend(request.time_range, metrics=request.metrics)
        logger.info(f"分析趋势成功: time_range={request.time_range}, metrics={request.metrics}")
        return result
    except Exception as e:
        logger.error(f"分析趋势失败: time_range={request.time_range}, metrics={request.metrics}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/report")
async def generate_report(request: ReportRequest = Body(...)):
    """生成分析报告"""
    try:
        # 记录入参
        logger.info(f"接收生成分析报告请求: analysis_type={request.analysis_type}, format={request.format}")
        
        result = analyzer.generate_report(request.analysis_type, format=request.format)
        logger.info(f"生成分析报告成功: analysis_type={request.analysis_type}, format={request.format}")
        return result
    except Exception as e:
        logger.error(f"生成分析报告失败: analysis_type={request.analysis_type}, format={request.format}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))