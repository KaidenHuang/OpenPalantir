import json
from sqlalchemy import Column, Index, String, Text, DateTime, text
from sqlalchemy.sql import func
from config.database import Base


class WikiPage(Base):
    """Wiki 页面 — LLM 生成、人工可编辑的知识内容资产"""
    __tablename__ = "wiki_pages"

    page_id = Column(String, primary_key=True)            # uuid4.hex
    title = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False)                 # document / topic / entity / answer
    status = Column(String, default="draft")              # draft / published
    content = Column(Text, default="")                    # Markdown 正文
    source_refs = Column(Text, default="[]")              # JSON: [{n, datasource, node_id, title}]
    datasource = Column(String, default="", index=True)   # 文档页对应的 DOC:// URI
    links = Column(Text, default="[]")                    # JSON: 页面互链标题
    content_hash = Column(String(32), default="")         # MD5(content)
    source_hash = Column(String(32), default="")          # 生成时源摘要文件 MD5（失效检测）
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        # 并发生成防重：同一 (kind, datasource) 只允许一页。
        # 部分索引——topic/answer 页 datasource 为空串可多行，不入约束。
        Index(
            "uq_wiki_pages_kind_datasource", kind, datasource,
            unique=True,
            sqlite_where=text("datasource != ''"),
        ),
    )

    def to_dict(self) -> dict:
        return {
            "page_id": self.page_id,
            "title": self.title,
            "kind": self.kind,
            "status": self.status,
            "content": self.content or "",
            "source_refs": json.loads(self.source_refs or "[]"),
            "datasource": self.datasource or "",
            "links": json.loads(self.links or "[]"),
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }
