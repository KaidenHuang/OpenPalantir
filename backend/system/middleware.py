"""HTTP 中间件：CORS + 请求日志 + Prometheus 指标采集"""

import os
import time
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from system.logger import logger
from system.metrics import REQUEST_COUNT, REQUEST_LATENCY, ACTIVE_REQUESTS, ERROR_COUNT


def register_middleware(app) -> None:
    """注册 CORS 和 HTTP 请求日志中间件。"""
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv('CORS_ORIGINS', '*').split(','),
        allow_credentials=True,
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
