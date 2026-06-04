import os
import json
import time
from typing import Dict, Any, Optional
from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import prometheus_client
from prometheus_client import Counter, Histogram, Gauge
from system.logger import logger

# 配置Prometheus指标
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP Requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP Request Latency', ['method', 'endpoint'])
ACTIVE_REQUESTS = Gauge('http_active_requests', 'Active HTTP Requests')
ERROR_COUNT = Counter('http_errors_total', 'Total HTTP Errors', ['method', 'endpoint', 'status'])

class SystemIntegration:
    def __init__(self, app):
        """初始化系统集成"""
        self.app = app
        self.setup_middleware()
        self.setup_metrics()

    def setup_middleware(self):
        """设置中间件"""
        # 配置CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=os.getenv('CORS_ORIGINS', '*').split(','),
            allow_credentials=True,
            allow_methods=['*'],
            allow_headers=['*'],
        )

        # 添加请求日志中间件
        @self.app.middleware("http")
        async def log_requests(request: Request, call_next):
            start_time = time.time()
            ACTIVE_REQUESTS.inc()

            # 记录请求信息
            #logger.info(f"Request: {request.method} {request.url}")

            try:
                response = await call_next(request)

                # 计算请求处理时间
                process_time = time.time() - start_time

                # 记录响应信息
                #logger.info(f"Response: {request.method} {request.url} {response.status_code} {process_time:.4f}s")

                # 更新Prometheus指标
                REQUEST_COUNT.labels(method=request.method, endpoint=str(request.url.path), status=response.status_code).inc()
                REQUEST_LATENCY.labels(method=request.method, endpoint=str(request.url.path)).observe(process_time)

                if response.status_code >= 400:
                    ERROR_COUNT.labels(method=request.method, endpoint=str(request.url.path), status=response.status_code).inc()

                return response
            except Exception as e:
                # 记录错误信息
                logger.error(f"Error processing request: {request.method} {request.url} - {str(e)}")

                # 更新错误指标
                ERROR_COUNT.labels(method=request.method, endpoint=str(request.url.path), status=500).inc()

                # 返回错误响应
                return JSONResponse(
                    status_code=500,
                    content={"detail": "Internal server error"}
                )
            finally:
                ACTIVE_REQUESTS.dec()

    def setup_metrics(self):
        """设置指标端点"""
        from fastapi import APIRouter

        metrics_router = APIRouter()

        @metrics_router.get("/metrics")
        async def get_metrics():
            """获取Prometheus指标"""
            from prometheus_client import generate_latest
            return Response(content=generate_latest(), media_type="text/plain")

        # 注册指标路由
        self.app.include_router(metrics_router, prefix="/api/system")

    def setup_health_check(self):
        """设置健康检查端点"""
        from fastapi import APIRouter

        health_router = APIRouter()

        @health_router.get("/health")
        async def health_check():
            """健康检查"""
            return {
                "status": "healthy",
                "timestamp": time.time(),
                "service": "OpenPalantir",
                "version": os.getenv('APP_VERSION', '1.0.0')
            }

        # 注册健康检查路由
        self.app.include_router(health_router, prefix="/api/system")

    def setup_api_docs(self):
        """设置API文档"""
        # FastAPI默认已经提供了Swagger UI和ReDoc
        # 这里可以添加自定义配置
        pass

    def setup_error_handling(self):
        """设置错误处理"""
        from fastapi import HTTPException

        @self.app.exception_handler(HTTPException)
        async def http_exception_handler(request: Request, exc: HTTPException):
            """处理HTTP异常"""
            logger.error(f"HTTP Exception: {exc.status_code} - {exc.detail}")
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail}
            )

        @self.app.exception_handler(Exception)
        async def general_exception_handler(request: Request, exc: Exception):
            """处理通用异常"""
            logger.error(f"General Exception: {str(exc)}")
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"}
            )

    def setup_system_routes(self):
        """设置系统路由"""
        from fastapi import APIRouter

        system_router = APIRouter()

        @system_router.get("/info")
        async def system_info():
            """获取系统信息"""
            return {
                "service": "OpenPalantir",
                "version": os.getenv('APP_VERSION', '1.0.0'),
                "environment": os.getenv('APP_ENV', 'development'),
                "timestamp": time.time()
            }

        @system_router.get("/config")
        async def system_config():
            """获取系统配置"""
            return {
                "cors_origins": os.getenv('CORS_ORIGINS', '*'),
                "neo4j_uri": os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
                "redis_host": os.getenv('REDIS_HOST', 'localhost'),
                "batch_size": int(os.getenv('BATCH_SIZE', '100')),
                "cache_ttl": int(os.getenv('CACHE_TTL', '3600'))
            }

        # 注册系统路由
        self.app.include_router(system_router, prefix="/api/system")

    def initialize(self):
        """初始化系统集成"""
        self.setup_health_check()
        self.setup_api_docs()
        self.setup_error_handling()
        self.setup_system_routes()

        logger.info("System integration initialized successfully")

        return {
            "status": "success",
            "message": "System integration initialized"
        }

# 全局系统集成实例
system_integration = None

def init_system_integration(app):
    """初始化系统集成"""
    global system_integration
    system_integration = SystemIntegration(app)
    return system_integration.initialize()