"""
Wiki 服务 — 页面 CRUD、生成编排、答案发布

页面存储于 SQLite（wiki_pages 表），正文为 Markdown，引用以 source_refs 结构化保存，
content 末尾自动附加「参考来源」小节。
"""
import hashlib
import json
import os
import uuid as uuid_lib
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from config.database import SessionLocal
from document_processing import summary_generator
from models.wiki import WikiPage
from system.logger import logger
from wiki import entity_generator, page_generator


def _append_references(content: str, refs: List[dict]) -> str:
    if not refs:
        return content
    lines = ["", "## 参考来源", ""]
    for ref in refs:
        ds = ref.get("datasource", "")
        node = ref.get("node_id", "")
        title = ref.get("title", "") or node
        lines.append(f"- [{ref.get('n')}] {title}（`{ds}`{f' #{node}' if node else ''}）")
    return content.rstrip() + "\n" + "\n".join(lines) + "\n"


class WikiService:

    # ── CRUD ──

    def list_pages(self, kind: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
        db = SessionLocal()
        try:
            q = db.query(WikiPage)
            if kind:
                q = q.filter(WikiPage.kind == kind)
            if status:
                q = q.filter(WikiPage.status == status)
            return [p.to_dict() for p in q.order_by(WikiPage.updated_at.desc()).all()]
        finally:
            db.close()

    def get_page(self, page_id: str) -> Optional[dict]:
        db = SessionLocal()
        try:
            page = db.query(WikiPage).filter_by(page_id=page_id).first()
            return page.to_dict() if page else None
        finally:
            db.close()

    def update_page(self, page_id: str, title: Optional[str] = None,
                    content: Optional[str] = None) -> Optional[dict]:
        db = SessionLocal()
        try:
            page = db.query(WikiPage).filter_by(page_id=page_id).first()
            if not page:
                return None
            if title is not None:
                page.title = title
            if content is not None:
                page.content = content
                page.content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
            db.commit()
            db.refresh(page)
            return page.to_dict()
        finally:
            db.close()

    def delete_page(self, page_id: str) -> bool:
        db = SessionLocal()
        try:
            page = db.query(WikiPage).filter_by(page_id=page_id).first()
            if not page:
                return False
            db.delete(page)
            db.commit()
            return True
        finally:
            db.close()

    def set_status(self, page_id: str, status: str) -> Optional[dict]:
        db = SessionLocal()
        try:
            page = db.query(WikiPage).filter_by(page_id=page_id).first()
            if not page:
                return None
            page.status = status
            db.commit()
            db.refresh(page)
            return page.to_dict()
        finally:
            db.close()

    def _save_page(self, data: Dict[str, Any], page_id: Optional[str] = None) -> dict:
        db = SessionLocal()
        try:
            page = db.query(WikiPage).filter_by(page_id=page_id).first() \
                if page_id else None
            if page is None:
                page = WikiPage(page_id=page_id or uuid_lib.uuid4().hex)
                db.add(page)
            page.title = data["title"][:200]
            page.kind = data["kind"]
            page.status = data.get("status", "draft")
            page.content = _append_references(data["content"], data.get("refs", []))
            page.source_refs = json.dumps(data.get("refs", []), ensure_ascii=False)
            page.datasource = data.get("datasource", "")
            page.source_hash = data.get("source_hash", "")
            page.content_hash = hashlib.md5(page.content.encode("utf-8")).hexdigest()
            page.links = json.dumps(self._extract_links(db, page), ensure_ascii=False)
            db.commit()
            db.refresh(page)
            return page.to_dict()
        finally:
            db.close()

    @staticmethod
    def _extract_links(db: Session, current: WikiPage) -> List[str]:
        """互链候选：正文中出现的其他页面标题"""
        titles = []
        for other in db.query(WikiPage).filter(WikiPage.page_id != current.page_id).all():
            if other.title and other.title in (current.content or ""):
                titles.append(other.title)
        return titles[:20]

    def refresh_links(self) -> int:
        """全量重算互链 —— 批量生成后调用，消除页面创建先后造成的漏链"""
        db = SessionLocal()
        try:
            pages = db.query(WikiPage).all()
            changed = 0
            for page in pages:
                links = [other.title for other in pages
                         if other.page_id != page.page_id and other.title
                         and other.title in (page.content or "")][:20]
                serialized = json.dumps(links, ensure_ascii=False)
                if serialized != (page.links or "[]"):
                    page.links = serialized
                    changed += 1
            db.commit()
            return changed
        finally:
            db.close()

    def remove_pages_by_datasource(self, datasource: str) -> int:
        """删除某来源产出的页面（文档下线时调用）"""
        db = SessionLocal()
        try:
            removed = db.query(WikiPage).filter(WikiPage.datasource == datasource).delete()
            db.commit()
            return removed
        finally:
            db.close()

    def prune_orphans(self) -> int:
        """清理来源已消失的页面 —— 失效传播的最后一环

        文档页：摘要文件已被删除则页面失去依据；
        实体页：图谱中该实体已被回收则页面失去依据。
        """
        from knowledge_graph.entity_repository import entity_repo

        db = SessionLocal()
        try:
            stale: List[WikiPage] = []
            for page in db.query(WikiPage).filter(WikiPage.kind == "document").all():
                source_id, file_path = summary_generator.parse_datasource(page.datasource)
                if not file_path or not os.path.isfile(
                        summary_generator.summary_path(source_id, file_path)):
                    stale.append(page)

            entity_pages = db.query(WikiPage).filter(WikiPage.kind == "entity").all()
            if entity_pages:
                ids = [entity_generator.parse_entity_datasource(p.datasource)
                       for p in entity_pages]
                alive = set(entity_repo.get_entities_batch([i for i in ids if i]))
                stale += [p for p, eid in zip(entity_pages, ids) if eid not in alive]

            for page in stale:
                db.delete(page)
            db.commit()
            if stale:
                logger.info(f"[wiki] 清理失效页面 {len(stale)} 个")
            return len(stale)
        finally:
            db.close()

    # ── 生成 ──

    def generate_document_page(self, datasource: str) -> Optional[dict]:
        result = page_generator.generate_document_page(datasource)
        if not result:
            return None
        db = SessionLocal()
        try:
            existing = db.query(WikiPage).filter_by(
                kind="document", datasource=datasource).first()
            if existing and existing.source_hash == result["source_hash"] \
                    and existing.content_hash == hashlib.md5(
                        _append_references(result["content"], result["refs"]).encode("utf-8")).hexdigest():
                return existing.to_dict()
            return self._save_page(result, page_id=existing.page_id if existing else None)
        finally:
            db.close()

    def generate_all(self) -> List[dict]:
        """全量生成：所有文档页（跳过未变更）+ 跨文档主题页 + 实体页"""
        created: List[dict] = []
        for path in page_generator.iter_summary_files():
            try:
                datasource = summary_generator.datasource_from_summary_path(path)
                if not datasource:
                    continue
                page = self.generate_document_page(datasource)
                if page:
                    created.append(page)
            except Exception as e:
                logger.warning(f"[wiki] 文档页生成失败 {path}: {e}")

        for topic, fragments in page_generator.discover_topics():
            try:
                page = self.generate_topic_page(topic, fragments)
                if page:
                    created.append(page)
            except Exception as e:
                logger.warning(f"[wiki] 主题页生成失败 {topic}: {e}")

        created += self.generate_entity_pages()
        self.refresh_links()
        return created

    def generate_topic_page(self, topic: str, fragments: List[dict]) -> Optional[dict]:
        result = page_generator.generate_topic_page(topic, fragments)
        if not result:
            return None
        db = SessionLocal()
        try:
            existing = db.query(WikiPage).filter_by(kind="topic", title=topic).first()
            if existing and existing.source_hash == result["source_hash"]:
                return existing.to_dict()
            return self._save_page(result, page_id=existing.page_id if existing else None)
        finally:
            db.close()

    def refresh_topics(self) -> List[dict]:
        """仅重跑主题发现与主题页生成"""
        pages = []
        for topic, fragments in page_generator.discover_topics():
            page = self.generate_topic_page(topic, fragments)
            if page:
                pages.append(page)
        self.refresh_links()
        return pages

    # ── 实体页（本体 → Wiki）──

    def _save_entity_page(self, result: Dict[str, Any]) -> dict:
        """实体页素材 → 落库；档案指纹未变则跳过"""
        db = SessionLocal()
        try:
            existing = db.query(WikiPage).filter_by(
                kind="entity", datasource=result["datasource"]).first()
            if existing and existing.source_hash == result["source_hash"]:
                return existing.to_dict()
            return self._save_page(result, page_id=existing.page_id if existing else None)
        finally:
            db.close()

    def generate_entity_page(self, entity_id: str) -> Optional[dict]:
        """指定实体 → 实体页（图谱页面按需建页）"""
        result = entity_generator.generate_entity_page_by_id(entity_id)
        if not result:
            return None
        return self._save_entity_page(result)

    def generate_entity_pages(self, limit: int = entity_generator.MAX_ENTITY_PAGES,
                              min_degree: int = entity_generator.MIN_DEGREE) -> List[dict]:
        """图谱高连接度实体 → 实体页"""
        pages = []
        for result in entity_generator.generate_entity_pages(limit=limit,
                                                            min_degree=min_degree):
            try:
                pages.append(self._save_entity_page(result))
            except Exception as e:
                logger.warning(f"[wiki] 实体页落库失败 {result.get('title')}: {e}")
        self.refresh_links()
        return pages

    # ── 答案发布 ──

    def publish_answer(self, question: str, answer: str,
                       citations: Optional[List[dict]] = None) -> dict:
        refs = []
        for i, c in enumerate(citations or [], 1):
            refs.append({"n": i, "datasource": c.get("datasource", ""),
                         "node_id": c.get("node_id", ""), "title": c.get("title", "")})
        title = (question.strip().splitlines()[0] if question.strip() else "问答沉淀")[:80]
        content = f"> 问题：{question.strip()}\n\n{answer.strip()}"
        return self._save_page({
            "title": title, "kind": "answer", "status": "published",
            "content": content, "refs": refs, "datasource": "", "source_hash": "",
        })


wiki_service = WikiService()
