"""
实体和关系的 Pydantic 数据契约

提供层间传递的类型安全模型，替代 raw dict。
- EntityData: 实体数据（含自由 JSON attributes）
- RelationshipData: 关系数据
- 均支持 from_llm_dict() 从 LLM 缩写格式构造
"""
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from models.ids import compute_entity_id, compute_relationship_id
from utils.json_utils import db_json_dumps


class EntityData(BaseModel):
    """实体数据契约"""
    name: str
    type: str = "other"
    count: int = 1
    confidence: float = 1.0
    byname: Optional[str] = None
    datasource: str = ""
    description: str = ""
    attributes: Dict[str, Any] = Field(default_factory=dict)

    @property
    def entity_id(self) -> str:
        return compute_entity_id(self.name)

    @classmethod
    def from_llm_dict(cls, d: dict, datasource: str = "") -> "EntityData":
        """从 LLM 缩写格式 {n,t,c,bn,d,a} 构造"""
        return cls(
            name=d["n"],
            type=d.get("t", "other"),
            count=d.get("c", 1),
            byname=d.get("bn"),
            datasource=datasource,
            description=d.get("d", ""),
            attributes=d.get("a", {}),
        )

    def to_neo4j_dict(self) -> dict:
        """转为 Neo4j 写入格式（与 graph_manager 兼容）"""
        return {
            "name": self.name,
            "type": self.type,
            "count": self.count,
            "confidence": self.confidence,
            "byname": self.byname,
            "datasource": self.datasource,
            "description": self.description,
            "attributes": db_json_dumps(self.attributes) if self.attributes else "{}",
        }


class RelationshipData(BaseModel):
    """关系数据契约"""
    subject: str
    predicate: str
    object: str
    occurrence_time: str = ""
    description: str = ""
    confidence: float = 0.5
    attributes: Dict[str, Any] = Field(default_factory=dict)

    @property
    def relationship_id(self) -> str:
        return compute_relationship_id(self.subject, self.predicate, self.object)

    @classmethod
    def from_llm_dict(cls, d: dict) -> "RelationshipData":
        """从 LLM 缩写格式 {s,p,o,ot,d} 构造"""
        return cls(
            subject=d["s"],
            predicate=d["p"],
            object=d["o"],
            occurrence_time=d.get("ot", "") or "",
            description=d.get("d", "") or "",
        )
