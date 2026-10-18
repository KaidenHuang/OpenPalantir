from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from system.logger import logger
from wiki.wiki_service import wiki_service

router = APIRouter()


class UpdatePageRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


class StatusRequest(BaseModel):
    status: str  # draft / published


class GenerateRequest(BaseModel):
    datasource: Optional[str] = None   # 指定则仅生成该文档页
    entity_id: Optional[str] = None    # 指定则仅生成该实体页
    scope: str = "all"                 # all / topics / entities（前两者为空时生效）


class PublishAnswerRequest(BaseModel):
    question: str
    answer: str
    citations: List[Dict] = []


@router.get("/pages")
def list_pages(kind: Optional[str] = None, status: Optional[str] = None):
    return {"pages": wiki_service.list_pages(kind=kind, status=status)}


@router.get("/pages/{page_id}")
def get_page(page_id: str):
    page = wiki_service.get_page(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    return page


@router.put("/pages/{page_id}")
def update_page(page_id: str, request: UpdatePageRequest):
    page = wiki_service.update_page(page_id, title=request.title, content=request.content)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    return page


@router.delete("/pages/{page_id}")
def delete_page(page_id: str):
    if not wiki_service.delete_page(page_id):
        raise HTTPException(status_code=404, detail="页面不存在")
    return {"deleted": True}


@router.post("/pages/{page_id}/status")
def set_status(page_id: str, request: StatusRequest):
    if request.status not in ("draft", "published"):
        raise HTTPException(status_code=400, detail="status 仅支持 draft/published")
    page = wiki_service.set_status(page_id, request.status)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    return page


@router.post("/publish_answer")
def publish_answer(request: PublishAnswerRequest):
    if not request.answer.strip():
        raise HTTPException(status_code=400, detail="answer 不能为空")
    logger.info(f"[wiki][api] publish_answer question_length={len(request.question)}")
    return wiki_service.publish_answer(
        request.question, request.answer, request.citations)


@router.post("/generate")
def generate(request: GenerateRequest):
    """创建 Wiki 生成异步任务，返回 task_id（进度经 /api/task/{task_id} 查询）"""
    from task_management.task_manager import task_manager

    if request.scope not in ("all", "topics", "entities"):
        raise HTTPException(status_code=400, detail="scope 仅支持 all/topics/entities")

    payload: Dict = {}
    if request.datasource:
        payload["datasource"] = request.datasource
    elif request.entity_id:
        payload["entity_id"] = request.entity_id
    else:
        payload["scope"] = request.scope
    task_id = task_manager.create_task("wiki_generate", payload)
    logger.info(f"[wiki][api] generate task_id={task_id} payload={payload}")
    return {"task_id": task_id}
