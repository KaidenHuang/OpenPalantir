"""
内容提取的数据契约

ExtractedDocument 是所有格式转换器的统一输出：
页面索引/摘要生成等下游模块只依赖这一层抽象，不感知具体格式。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 章节形态：prose = 普通文字章节，table = 表格文件的一个工作表
KIND_PROSE = "prose"
KIND_TABLE = "table"


@dataclass
class Section:
    """文档内的一个章节：标题 + 本节自身正文 + 子章节

    text 只含本节正文（不含子节），子树正文可由 children 递归取得；
    页码锚点仅 PDF/图片版 PDF 等分页文档才有（其他格式为 None）。
    kind 让下游显式判断"这一节是表格"，不靠标题正则猜。
    """
    title: str
    level: int                       # 标题层级，1..6
    text: str = ""                   # 本节自身正文（不含子节）
    page_start: Optional[int] = None # 本节起始页码（1-based）
    page_end: Optional[int] = None   # 本节正文结束页码
    children: List["Section"] = field(default_factory=list)
    kind: str = KIND_PROSE


@dataclass
class ExtractedDocument:
    """统一提取结果：文档级元信息 + 章节 forest

    meta 放格式相关的少量留痕（如表格文件被跳过的 sheet），
    下游按需读取，缺失即视为没有。
    """
    doc_name: str                    # 文件名（不含扩展名）
    format: str                      # pdf | docx | pptx | md | txt | xlsx | xlsm | csv | tsv
    page_count: Optional[int] = None # 分页文档的页数，其他格式为 None
    sections: List[Section] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
