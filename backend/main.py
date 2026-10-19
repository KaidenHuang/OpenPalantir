from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import sys
import os

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入日志系统
from system.logger import logger

from config.database import Base, engine

# 导入所有模型
from models import model, task, database, source, cdc, memory, embedding, wiki

# 创建数据库表
Base.metadata.create_all(bind=engine)

# 初始化 Neo4j Schema（约束 + 索引）
from config.neo4j_config import neo4j_conn
try:
    neo4j_conn.initialize_schema()
except Exception as e:
    logger.warning(f"Neo4j schema 初始化失败（降级运行）: {e}")

# 初始化默认模型记录
from models.model import init_models
init_models()

# 初始化默认实体类型
from models.database import init_entity_types
init_entity_types()

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

# 启动时回填 byname（非阻塞，后台线程执行）
def _backfill_byname():
    try:
        from knowledge_graph.entity_repository import entity_repo
        count = entity_repo.backfill_byname()
        if count > 0:
            logger.info(f"[startup] byname 回填完成: {count} 个实体")
    except Exception as e:
        logger.warning(f"[startup] byname 回填失败（不影响服务）: {e}")

import threading
threading.Thread(target=_backfill_byname, daemon=True).start()

@app.get("/")
async def root():
    return {"message": "分析决策系统API服务运行中"}

# 导入路由
from api.routes import graph, analysis, model, database, decision, filesystem, source, cdc as cdc_routes, entity_types, wiki as wiki_routes, ontology as ontology_routes
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
app.include_router(entity_types.router, prefix="/api/entity-types", tags=["entity-types"])
app.include_router(wiki_routes.router, prefix="/api/wiki", tags=["wiki"])
app.include_router(ontology_routes.router, prefix="/api/ontology", tags=["ontology"])

# WebSocket 任务实时推送
from websocket.task_ws import task_ws_manager

@app.on_event("startup")
async def startup_ws_loop():
    task_ws_manager.set_main_loop(asyncio.get_running_loop())
    if os.getenv("DOC_WATCH_ENABLED") == "1":
        from file_sources.watcher import document_watcher
        document_watcher.start()

@app.websocket("/ws/tasks")
async def websocket_tasks(websocket: WebSocket):
    """任务状态实时推送 WebSocket 端点

    设置 API_AUTH_KEY 后要求握手时以 ?key= 或 X-API-Key 头携带密钥，否则 4401 关闭。
    """
    api_key = os.getenv("API_AUTH_KEY", "")
    if api_key:
        provided = websocket.query_params.get("key", "") or websocket.headers.get("x-api-key", "")
        if provided != api_key:
            await websocket.accept()
            await websocket.close(code=4401, reason="Unauthorized")
            return
    await task_ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        task_ws_manager.disconnect(websocket)


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时优雅停止 CDC Consumer 与文档监听"""
    from cdc.cdc_manager import cdc_manager
    cdc_manager.shutdown_all()
    if os.getenv("DOC_WATCH_ENABLED") == "1":
        from file_sources.watcher import document_watcher
        document_watcher.stop()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)