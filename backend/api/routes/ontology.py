"""
本体治理 API — 词表查询、治理报告、本体包导入导出

社区提交领域本体包的完整链路：POST /packs 校验并注册 → 抽取/标注立即用上新词表 →
GET /report 观察新词表是否真的被使用（未被使用的 LinkType 会列出）。
"""
from typing import Optional
from fastapi import APIRouter, Body, HTTPException, Query

from ontology import governance
from ontology.registry import ontology_registry
from ontology.types import OntologyError
from system.logger import logger

router = APIRouter()


@router.get("/domains")
def list_domains():
    """全部域包及其规模（域包名即 domain 参数取值）"""
    try:
        items = []
        for name in ontology_registry.domains():
            pack = ontology_registry.pack(name)
            items.append({"name": name, "description": pack.description,
                          "object_type_count": len(pack.object_types),
                          "link_type_count": len(pack.link_types)})
        return {"status": "success", "domains": items}
    except Exception as e:
        logger.error(f"获取本体域列表失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/packs/{domain}")
def export_pack(domain: str):
    """导出域包 YAML（general 返回基底包本身）"""
    try:
        return {"domain": domain, "yaml": ontology_registry.export_pack(domain)}
    except OntologyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"导出本体包失败 {domain}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/packs")
def import_pack(data: dict = Body(...)):
    """导入领域本体包：校验不过直接 400；persist=true 时落盘，重启后仍在"""
    text = data.get("yaml") or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="yaml is required")
    try:
        pack = ontology_registry.import_pack(text, persist=bool(data.get("persist", False)))
        logger.info(f"[ontology] 导入本体包: {pack.name}, "
                    f"{len(pack.object_types)} ObjectType / {len(pack.link_types)} LinkType")
        return {"status": "success", "name": pack.name,
                "object_type_count": len(pack.object_types),
                "link_type_count": len(pack.link_types)}
    except OntologyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"导入本体包失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/reload")
def reload_packs():
    """从磁盘重新加载本体包（改完 packs/ 或 data/ontology_packs/ 后调用）"""
    try:
        ontology_registry.reload()
        return {"status": "success", "domains": ontology_registry.domains()}
    except OntologyError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/report")
def governance_report(domain: Optional[str] = Query(None),
                      limit: int = Query(50, ge=1, le=500),
                      with_pack: bool = Query(False)):
    """治理报告：词表使用统计 + 非法类型/谓词/定义域值域检测 + 结构问题"""
    try:
        return {"status": "success",
                **governance.report(domain=domain if with_pack else None, limit=limit)}
    except OntologyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"生成治理报告失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
