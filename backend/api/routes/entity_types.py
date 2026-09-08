"""
实体类型管理 API — CRUD

GET    /api/entity-types           — 列出所有类型（按 sort_order 排序）
POST   /api/entity-types           — 创建自定义类型
PUT    /api/entity-types/{key}     — 更新类型（显示名/颜色/排序）
DELETE /api/entity-types/{key}     — 删除自定义类型（内置类型不可删）
"""
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from config.database import get_db
from models.database import EntityType

router = APIRouter()


class EntityTypeCreate(BaseModel):
    type_key: str
    display_name: str
    color: str = "#95A5A6"
    sort_order: int = 0


class EntityTypeUpdate(BaseModel):
    display_name: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


@router.get("")
def list_entity_types(db: Session = Depends(get_db)):
    """列出所有实体类型"""
    types = db.query(EntityType).order_by(EntityType.sort_order, EntityType.type_key).all()
    return {"status": "success", "data": [t.to_dict() for t in types]}


@router.post("")
def create_entity_type(body: EntityTypeCreate, db: Session = Depends(get_db)):
    """创建自定义实体类型"""
    existing = db.query(EntityType).filter(EntityType.type_key == body.type_key).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"类型 '{body.type_key}' 已存在")

    entity_type = EntityType(
        type_key=body.type_key,
        display_name=body.display_name,
        color=body.color,
        sort_order=body.sort_order,
        is_builtin=False,
    )
    db.add(entity_type)
    db.commit()
    db.refresh(entity_type)
    return {"status": "success", "data": entity_type.to_dict()}


@router.put("/{type_key}")
def update_entity_type(type_key: str, body: EntityTypeUpdate, db: Session = Depends(get_db)):
    """更新实体类型"""
    entity_type = db.query(EntityType).filter(EntityType.type_key == type_key).first()
    if not entity_type:
        raise HTTPException(status_code=404, detail=f"类型 '{type_key}' 不存在")

    if body.display_name is not None:
        entity_type.display_name = body.display_name
    if body.color is not None:
        entity_type.color = body.color
    if body.sort_order is not None:
        entity_type.sort_order = body.sort_order

    db.commit()
    db.refresh(entity_type)
    return {"status": "success", "data": entity_type.to_dict()}


@router.delete("/{type_key}")
def delete_entity_type(type_key: str, db: Session = Depends(get_db)):
    """删除自定义实体类型（内置类型不可删除）"""
    entity_type = db.query(EntityType).filter(EntityType.type_key == type_key).first()
    if not entity_type:
        raise HTTPException(status_code=404, detail=f"类型 '{type_key}' 不存在")
    if entity_type.is_builtin:
        raise HTTPException(status_code=400, detail=f"内置类型 '{type_key}' 不可删除")

    db.delete(entity_type)
    db.commit()
    return {"status": "success", "type_key": type_key}
