"""
本体数据类型 — ObjectType / LinkType / PropertyType / OntologyPack
"""
from dataclasses import dataclass, field
from typing import List, Optional


class OntologyError(ValueError):
    """本体定义非法（包校验失败等）"""


@dataclass(frozen=True)
class PropertyType:
    """属性类型定义"""
    key: str
    data_type: str = "string"          # string / number / date / boolean
    description: str = ""


@dataclass(frozen=True)
class ObjectType:
    """实体类型（支持单继承层级，parent 为另一 ObjectType.key 或 None）"""
    key: str
    display_name: str
    description: str = ""
    parent: Optional[str] = None
    color: str = "#95A5A6"
    sort_order: int = 0
    properties: List[PropertyType] = field(default_factory=list)


@dataclass(frozen=True)
class LinkType:
    """受控关系类型（谓词）

    domain/range 为主语/宾语的合法 ObjectType key 列表，空列表表示不限。
    inverse 为反向谓词 key（如 包含↔属于）；symmetric 表示谓词无方向。
    aliases 为归一化映射用的同义谓词。
    """
    key: str
    display_name: str = ""
    description: str = ""
    domain: List[str] = field(default_factory=list)
    range: List[str] = field(default_factory=list)
    symmetric: bool = False
    inverse: Optional[str] = None
    aliases: List[str] = field(default_factory=list)

    def allows_subject(self, type_key: str) -> bool:
        return not self.domain or type_key in self.domain

    def allows_object(self, type_key: str) -> bool:
        return not self.range or type_key in self.range


@dataclass(frozen=True)
class OntologyPack:
    """一个领域的本体包

    general 为基底；其余包的域视图 = 基底 ⊕ 自己的增量。
    extends 指定挂在哪个域包之上（缺省挂基底），社区包据此复用内置域词表，
    只声明增量，不必整包 fork。
    """
    name: str
    description: str = ""
    object_types: List[ObjectType] = field(default_factory=list)
    link_types: List[LinkType] = field(default_factory=list)
    extends: Optional[str] = None
