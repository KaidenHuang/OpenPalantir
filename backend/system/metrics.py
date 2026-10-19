"""Prometheus 指标定义与 /api/system/metrics 端点"""

from fastapi import APIRouter, Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest

# Prometheus 指标定义
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP Requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP Request Latency', ['method', 'endpoint'])
ACTIVE_REQUESTS = Gauge('http_active_requests', 'Active HTTP Requests')
ERROR_COUNT = Counter('http_errors_total', 'Total HTTP Errors', ['method', 'endpoint', 'status'])

# 业务四件套：决策轮次 / 任务耗时 / 图谱写入 / CDC 事件
DECISION_TURNS = Counter('decision_turns_total', 'AgenticEngine ReAct turns executed', ['domain'])
TASK_DURATION = Histogram('task_duration_seconds', 'Async task execution duration', ['task_type', 'status'])
GRAPH_WRITES = Counter('graph_writes_total', 'Graph write operations via repositories', ['op'])
CDC_EVENTS = Counter('cdc_events_total', 'CDC events processed', ['connection', 'result'])


def register_metrics_router(app) -> None:
    """注册 /api/system/metrics 端点。"""
    router = APIRouter()

    @router.get("/metrics")
    async def get_metrics():
        """获取 Prometheus 指标"""
        return Response(content=generate_latest(), media_type="text/plain")

    app.include_router(router, prefix="/api/system")
