import os
from typing import List, Dict, Any, Tuple
from system.logger import logger
from knowledge_graph.entity_repository import entity_repo
from knowledge_graph.relationship_repository import rel_repo
from knowledge_graph.alias_cache import AliasCache
from models.graph_models import EntityData, RelationshipData

# 关系分批写入大小（可通过环境变量 NEO4J_REL_BATCH_SIZE 配置，默认 5000）
_NEO4J_REL_BATCH_SIZE = int(os.getenv('NEO4J_REL_BATCH_SIZE', '5000'))


class EntityDataStore:
    """实体和关系数据存储工具类

    本类只做「准备语义行」：实体/关系字段装配、别名解析、端点 id 补齐；
    谓词归一化与 relationship_id 计算一律发生在 RelationshipRepository
    （受控写入缝），此处不再复制归一化规则。
    """

    @staticmethod
    def _save_relationships_batched(
        prepared_relationships: List[Dict[str, Any]],
        use_create: bool = False,
        defer_cache: bool = False,
    ) -> int:
        """分批写入关系，避免单次 UNWIND 过大导致 Neo4j 内存压力和锁竞争"""
        if not prepared_relationships:
            return 0

        total = 0
        batch_size = _NEO4J_REL_BATCH_SIZE
        total_batches = (len(prepared_relationships) + batch_size - 1) // batch_size

        for i in range(0, len(prepared_relationships), batch_size):
            batch = prepared_relationships[i:i + batch_size]
            batch_num = i // batch_size + 1
            logger.info(f"[save_relationships] 写入第 {batch_num}/{total_batches} 批 ({len(batch)} 条)")
            try:
                result = rel_repo.add_relationships(batch, use_create=use_create,
                                                    defer_cache=defer_cache)
                total += result.get('count', 0)
            except Exception as e:
                logger.error(f"[save_relationships] 第 {batch_num} 批写入失败: {e}")
                # 继续尝试后续批次，而非全部放弃

        return total

    @staticmethod
    def save_all(
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]] = None,
        datasource: str = None,
        use_create: bool = False
    ) -> Tuple[int, int]:
        """一次性保存实体和关系到图谱存储

        Args:
            entities: 实体列表
            relationships: 关系列表
            datasource: 数据源标识
            use_create: True=关系使用 CREATE（首次导入更快）；False=使用 MERGE（默认，幂等安全）
        """
        entity_count = 0
        rel_count = 0

        if not entities:
            logger.info("没有需要保存的实体")
            return entity_count, rel_count

        # 词表外 'time' 类型防幻觉阀门在进料缝拦截（repo 层不再过滤，保证 ids 与输入对齐）
        entities = [e for e in entities if (e.get('type') or '').strip().lower() != 'time']
        prepared_entities = []
        name_to_eid: Dict[str, str] = {}  # 原始名 → entity_id（别名解析前）
        for entity in entities:
            ed = EntityData.from_llm_dict(entity, datasource=datasource or "")
            prepared_entities.append(ed.to_neo4j_dict())
            name_to_eid[ed.name.strip()] = ed.entity_id
            if ed.byname:
                name_to_eid[ed.byname.strip()] = ed.entity_id

        # 别名解析：检查缓存，命中则重定向到已有实体
        alias_cache = AliasCache()
        prepared_entities, redirected_ids = alias_cache.resolve_entities(prepared_entities)

        try:
            result = entity_repo.add_entities(prepared_entities)
            entity_ids = result.get('ids', [])
            entity_count = len(entity_ids)
            logger.info(f"实体保存成功，数量: {entity_count}")

            for i, entity_id in enumerate(entity_ids):
                if i < len(prepared_entities):
                    prepared_entities[i]['entity_id'] = entity_id

            # 构建别名缓存（写入成功后）
            alias_cache.build_from_entities(prepared_entities)

        except Exception as e:
            logger.error(f"批量保存实体时出错: {e}")
            return entity_count, rel_count

        if relationships:
            entity_name_map = {}
            for e in prepared_entities:
                name = e.get('name', '').strip()
                if name:
                    entity_name_map[name] = e
                    entity_name_map[name.lower()] = e

            # 将重定向的实体也加入映射（别名 → 已有实体 ID）
            for old_id, new_id in redirected_ids.items():
                for name, eid in name_to_eid.items():
                    if eid == old_id:
                        entity_name_map[name] = {'entity_id': new_id, 'name': name}
                        entity_name_map[name.lower()] = {'entity_id': new_id, 'name': name}

            prepared_relationships = []
            skipped = 0
            for relationship in relationships:
                subject_name = str(relationship.get('s', '')).strip()
                object_name = str(relationship.get('o', '')).strip()

                subject_entity = entity_name_map.get(subject_name) or entity_name_map.get(subject_name.lower())
                object_entity = entity_name_map.get(object_name) or entity_name_map.get(object_name.lower())

                subject_id = subject_entity.get('entity_id', '') if subject_entity else ''
                object_id = object_entity.get('entity_id', '') if object_entity else ''

                if not subject_id:
                    logger.warning(f"跳过关系（主体实体不存在）: '{subject_name}' -> {relationship.get('p', '')} -> '{object_name}'")
                    skipped += 1
                    continue
                if not object_id:
                    logger.warning(f"跳过关系（客体实体不存在）: '{subject_name}' -> {relationship.get('p', '')} -> '{object_name}'")
                    skipped += 1
                    continue

                # 语义行：只补端点 id；谓词归一化 / relationship_id 由 RelationshipRepository 计算
                prepared = {
                    'subject': subject_name,
                    'object': object_name,
                    'predicate': relationship.get('p', ''),
                    'datasource': datasource or '',
                    'occurrence_time': relationship.get('ot', ''),
                    'description': relationship.get('d', ''),
                    'subject_id': subject_id,
                    'object_id': object_id
                }

                prepared_relationships.append(prepared)

            if skipped:
                logger.warning(f"跳过了 {skipped} 条关系（主体或客体实体不存在）")

            rel_count = EntityDataStore._save_relationships_batched(prepared_relationships, use_create=use_create)
            logger.info(f"关系保存成功，数量: {rel_count}")

        logger.info(f"数据存储完成，实体: {entity_count}, 关系: {rel_count}")
        return entity_count, rel_count

    @staticmethod
    def save_entities_only(
        entities: List[Dict[str, Any]],
        datasource: str = None,
        defer_cache: bool = False,
    ) -> List[Dict[str, Any]]:
        """仅保存实体（不处理关系），返回已填充 entity_id 的实体列表"""
        if not entities:
            return []

        # 词表外 'time' 类型防幻觉阀门在进料缝拦截（repo 层不再过滤，保证 ids 与输入对齐）
        entities = [e for e in entities if (e.get('type') or '').strip().lower() != 'time']
        prepared_entities = []
        for entity in entities:
            ed = EntityData.from_llm_dict(entity, datasource=datasource or "")
            prepared_entities.append(ed.to_neo4j_dict())

        try:
            result = entity_repo.add_entities(prepared_entities, defer_cache=defer_cache)
            entity_ids = result.get('ids', [])
            for i, entity_id in enumerate(entity_ids):
                if i < len(prepared_entities):
                    prepared_entities[i]['entity_id'] = entity_id
        except Exception as e:
            logger.error(f"批量保存实体时出错: {e}")

        return prepared_entities

    @staticmethod
    def save_relationships_only(
        relationships: List[Dict[str, Any]],
        entity_name_map: Dict[str, Dict[str, Any]],
        datasource: str = "",
        use_create: bool = False,
        defer_cache: bool = False,
    ) -> int:
        """仅保存关系，使用提供的 entity_name_map 解析 subject/object ID

        语义行只补端点 id，谓词归一化 / relationship_id 由 RelationshipRepository 统一处理。

        Args:
            relationships: 关系列表
            entity_name_map: 实体名 → entity 字典映射（含 entity_id）
            datasource: 产出这批关系的来源 URI，写入边用于后续回收
            use_create: True=使用 CREATE（首次导入更快）；False=使用 MERGE（默认，幂等安全）
            defer_cache: 批量导入静默期
        """
        if not relationships:
            return 0

        prepared_relationships = []
        for relationship in relationships:
            subject_name = str(relationship.get('s', '')).strip()
            object_name = str(relationship.get('o', '')).strip()

            subject_entity = entity_name_map.get(subject_name) or entity_name_map.get(subject_name.lower())
            object_entity = entity_name_map.get(object_name) or entity_name_map.get(object_name.lower())

            prepared = {
                'subject': subject_name,
                'object': object_name,
                'predicate': relationship.get('p', ''),
                'datasource': datasource,
                'occurrence_time': relationship.get('ot', ''),
                'description': relationship.get('d', ''),
                'attributes': relationship.get('a', {}),
                'subject_id': subject_entity.get('entity_id', '') if subject_entity else '',
                'object_id': object_entity.get('entity_id', '') if object_entity else ''
            }
            prepared_relationships.append(prepared)

        return EntityDataStore._save_relationships_batched(
            prepared_relationships, use_create=use_create, defer_cache=defer_cache)
