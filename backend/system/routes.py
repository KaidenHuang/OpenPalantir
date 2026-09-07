"""系统路由：/health、/info、/config"""

import os
import time
from fastapi import APIRouter


def register_system_routes(app) -> None:
    """注册系统管理端点。"""
    router = APIRouter()

    @router.get("/health")
    async def health_check():
        """健康检查"""
        return {
            "status": "healthy",
            "timestamp": time.time(),
            "service": "OpenPalantir",
            "version": os.getenv('APP_VERSION', '1.0.0')
        }

    @router.get("/info")
    async def system_info():
        """获取系统信息"""
        return {
            "service": "OpenPalantir",
            "version": os.getenv('APP_VERSION', '1.0.0'),
            "environment": os.getenv('APP_ENV', 'development'),
            "timestamp": time.time()
        }

    @router.get("/config")
    async def system_config():
        """获取系统配置"""
        return {
            "cors_origins": os.getenv('CORS_ORIGINS', '*'),
            "neo4j_uri": os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
            "redis_host": os.getenv('REDIS_HOST', 'localhost'),
            "batch_size": int(os.getenv('BATCH_SIZE', '100')),
            "cache_ttl": int(os.getenv('CACHE_TTL', '3600'))
        }

    app.include_router(router, prefix="/api/system")
