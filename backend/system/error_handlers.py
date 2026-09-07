"""全局异常处理器"""

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from system.logger import logger


def register_error_handlers(app) -> None:
    """注册 HTTP 异常和通用异常处理器。"""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """处理 HTTP 异常"""
        if exc.status_code < 500:
            logger.warning(f"HTTP {exc.status_code}: {exc.detail} [{request.method} {request.url.path}]")
        else:
            logger.error(f"HTTP {exc.status_code}: {exc.detail} [{request.method} {request.url.path}]")
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """处理通用异常"""
        logger.error(f"General Exception: {str(exc)}")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
