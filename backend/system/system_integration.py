"""系统集成 — 纯编排入口，委托各子模块完成具体工作"""

from system.logger import logger
from system.middleware import register_middleware
from system.metrics import register_metrics_router
from system.error_handlers import register_error_handlers
from system.routes import register_system_routes


def init_system_integration(app):
    """初始化系统集成：依次注册中间件、指标、异常处理、系统路由。"""
    register_middleware(app)
    register_metrics_router(app)
    register_error_handlers(app)
    register_system_routes(app)

    logger.info("System integration initialized successfully")
    return {"status": "success", "message": "System integration initialized"}
