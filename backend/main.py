from fastapi import FastAPI
import sys
import os

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入日志系统
from system.logger import logger

from config.database import Base, engine

# 导入所有模型
from models import model, task, database, source, cdc

# 创建数据库表
Base.metadata.create_all(bind=engine)

# 初始化 Neo4j Schema（约束 + 索引）
from config.neo4j_config import neo4j_conn
neo4j_conn.initialize_schema()

# 初始化默认模型记录
from models.model import init_models
init_models()

from system.system_integration import init_system_integration

app = FastAPI(
    title="分析决策系统API",
    description="基于海量文档的分析决策系统API",
    version="1.0.0"
)

# 初始化系统集成
init_system_integration(app)

# 记录应用启动日志
logger.info("分析决策系统API服务启动")

@app.get("/")
async def root():
    return {"message": "分析决策系统API服务运行中"}

# 导入路由
from api.routes import graph, analysis, model, database, decision, filesystem, source, cdc as cdc_routes
from api import task

app.include_router(graph.router, prefix="/api/graph", tags=["graph"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(model.router, prefix="/api/model", tags=["model"])
app.include_router(task.router, prefix="/api/task", tags=["task"])
app.include_router(database.router, tags=["database"])
app.include_router(decision.router, prefix="/api/decision", tags=["decision"])
app.include_router(filesystem.router, prefix="/api/filesystem", tags=["filesystem"])
app.include_router(source.router, prefix="/api", tags=["source"])
app.include_router(cdc_routes.router, tags=["cdc"])


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时优雅停止所有 CDC Consumer"""
    from cdc.cdc_manager import cdc_manager
    cdc_manager.shutdown_all()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)