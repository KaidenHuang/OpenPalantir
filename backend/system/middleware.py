"""HTTP 中间件：CORS + 请求日志 + Prometheus 指标采集"""

import os
import time
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from system.logger import logger
from system.metrics import REQUEST_COUNT, REQUEST_LATENCY, ACTIVE_REQUESTS, ERROR_COUNT


def register_middleware(app) -> None:
    """注册鉴权、CORS 和 HTTP 请求日志中间件。"""
    # 鉴权：设置 API_AUTH_KEY 后所有 /api 路由要求 X-API-Key 头（本地开发不设置则跳过）
    api_auth_key = os.getenv("API_AUTH_KEY", "")

    async def require_api_key(request: Request, call_next):
        if api_auth_key and request.url.path.startswith("/api"):
            provided = request.headers.get("x-api-key", "")
            if provided != api_auth_key:
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        return await call_next(request)

    app.middleware("http")(require_api_key)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in os.getenv('CORS_ORIGINS', '*').split(',')],
        allow_credentials=False,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    # 请求日志 + Prometheus 指标
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.time()
        ACTIVE_REQUESTS.inc()

        try:
            response = await call_next(request)
            process_time = time.time() - start_time

            REQUEST_COUNT.labels(
                method=request.method, endpoint=str(request.url.path),
                status=response.status_code
            ).inc()
            REQUEST_LATENCY.labels(
                method=request.method, endpoint=str(request.url.path)
            ).observe(process_time)

            if response.status_code >= 400:
                ERROR_COUNT.labels(
                    method=request.method, endpoint=str(request.url.path),
                    status=response.status_code
                ).inc()

            return response
        except Exception as e:
            logger.error(f"Error processing request: {request.method} {request.url} - {str(e)}")
            ERROR_COUNT.labels(
                method=request.method, endpoint=str(request.url.path), status=500
            ).inc()
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})
        finally:
            ACTIVE_REQUESTS.dec()
