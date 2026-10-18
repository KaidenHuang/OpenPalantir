from typing import Any, Callable, Dict

from system.logger import logger

from .base import TaskHandler


class WikiGenerateHandler(TaskHandler):
    """执行 Wiki 页面生成任务（文档页 / 跨文档主题页 / 实体页）"""

    def execute(self, task, progress_callback: Callable[[int], None]) -> Dict:
        from wiki.wiki_service import wiki_service

        datasource = task.payload.get("datasource")
        entity_id = task.payload.get("entity_id")
        scope = task.payload.get("scope", "all")
        logger.info(f"[WikiGenerateHandler] datasource={datasource}, "
                    f"entity_id={entity_id}, scope={scope}")

        if datasource:
            page = wiki_service.generate_document_page(datasource)
            pages = [page] if page else []
        elif entity_id:
            page = wiki_service.generate_entity_page(entity_id)
            pages = [page] if page else []
        elif scope == "topics":
            pages = wiki_service.refresh_topics()
        elif scope == "entities":
            pages = wiki_service.generate_entity_pages()
        else:
            pages = wiki_service.generate_all()

        progress_callback(100)
        logger.info(f"[WikiGenerateHandler] 完成: {len(pages)} 个页面")
        return {
            "status": "success",
            "pages": [{"page_id": p["page_id"], "title": p["title"], "kind": p["kind"]}
                      for p in pages],
        }
