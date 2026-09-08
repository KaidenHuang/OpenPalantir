"""
别名缓存 — 跨文档实体去重

Redis Hash 存储 name/byname → entity_id 映射。
写入时查找别名缓存，命中则将新实体的关系重定向到已有节点。

仅文档提取路径使用，数据库导入和 CDC 跳过（行实体用 table:pk 命名，无别名问题）。
"""
import os
import redis
from typing import Dict, List, Optional
from config.neo4j_config import neo4j_conn
from system.logger import logger

_HASH_KEY = "entity_aliases"


class AliasCache:
    """基于 Redis Hash 的实体别名缓存"""

    def __init__(self):
        try:
            self._redis = redis.Redis(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', '6379')),
                db=int(os.getenv('REDIS_CACHE_DB', '0')),
                decode_responses=True,
                protocol=2,
            )
            self._redis.ping()
        except Exception:
            self._redis = None

    @property
    def available(self) -> bool:
        return self._redis is not None

    # ── 查询 ──

    def lookup(self, name: str) -> Optional[str]:
        """查找 name 对应的 entity_id，未命中返回 None"""
        if not self._redis:
            return None
        try:
            return self._redis.hget(_HASH_KEY, name)
        except Exception:
            return None

    def lookup_many(self, names: List[str]) -> Dict[str, str]:
        """批量查找，返回 {name: entity_id}（仅含命中的）"""
        if not self._redis or not names:
            return {}
        try:
            vals = self._redis.hmget(_HASH_KEY, names)
            return {n: v for n, v in zip(names, vals) if v}
        except Exception:
            return {}

    # ── 构建 ──

    def build_from_entities(self, entities: List[Dict]) -> int:
        """从实体列表构建别名缓存，返回写入条数。

        entities: 包含 name、byname、entity_id 的字典列表
        """
        if not self._redis or not entities:
            return 0

        mapping: Dict[str, str] = {}
        for e in entities:
            eid = e.get("entity_id", "")
            if not eid:
                continue
            name = e.get("name", "").strip()
            if name:
                mapping[name] = eid
            byname = e.get("byname")
            if byname and isinstance(byname, str) and byname.strip():
                mapping[byname.strip()] = eid

        if mapping:
            try:
                self._redis.hset(_HASH_KEY, mapping=mapping)
                logger.info(f"[AliasCache] 构建别名缓存: {len(mapping)} 条")
            except Exception as e:
                logger.warning(f"[AliasCache] 构建缓存失败: {e}")
                return 0
        return len(mapping)

    # ── 解析 ──

    def resolve_entities(self, prepared_entities: List[Dict]) -> tuple:
        """解析实体列表中的别名，返回 (resolved_entities, redirected_ids)。

        - resolved_entities: 需要新建的实体（未在缓存中命中）
        - redirected_ids: {旧entity_id: 已有entity_id} — 用于关系重定向
        """
        if not self._redis or not prepared_entities:
            return prepared_entities, {}

        names = [e.get("name", "") for e in prepared_entities]
        cache_hits = self.lookup_many(names)

        redirected_ids: Dict[str, str] = {}
        resolved: List[Dict] = []

        for entity in prepared_entities:
            name = entity.get("name", "")
            eid = entity.get("entity_id", "")
            cached_id = cache_hits.get(name)

            if cached_id and cached_id != eid:
                redirected_ids[eid] = cached_id
                logger.info(f"[AliasCache] 别名命中: '{name}' → 已有实体 {cached_id}")
            else:
                resolved.append(entity)

        return resolved, redirected_ids

    def resolve_relationships(
        self, prepared_relationships: List[Dict],
        redirected_ids: Dict[str, str],
    ) -> List[Dict]:
        """根据别名重定向结果，修正关系的 subject_id/object_id"""
        if not redirected_ids:
            return prepared_relationships

        result = []
        for rel in prepared_relationships:
            rel = dict(rel)
            sid = rel.get("subject_id", "")
            oid = rel.get("object_id", "")
            if sid in redirected_ids:
                rel["subject_id"] = redirected_ids[sid]
            if oid in redirected_ids:
                rel["object_id"] = redirected_ids[oid]
            result.append(rel)
        return result
