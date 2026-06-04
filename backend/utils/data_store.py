import hashlib
from typing import List, Dict, Any, Tuple
from system.logger import logger
from knowledge_graph.graph_manager import graph_manager

class EntityDataStore:
    """实体和关系数据存储工具类"""

    @staticmethod
    def save_all(
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]] = None,
        datasource: str = None
    ) -> Tuple[int, int]:
        """一次性保存实体和关系到图谱存储"""
        entity_count = 0
        rel_count = 0

        if not entities:
            logger.info("没有需要保存的实体")
            return entity_count, rel_count

        prepared_entities = []
        for entity in entities:
            prepared = {
                'name': entity.get('n', ''),
                'type': entity.get('t', 'Entity'),
                'byname': entity.get('bn', None),
                'count': entity.get('c', 1),
                'datasource': entity.get('datasource', datasource or ''),
                'description': entity.get('d', '')
            }
            prepared_entities.append(prepared)

        try:
            result = graph_manager.add_entities(prepared_entities)
            entity_ids = result.get('ids', [])
            entity_count = len(entity_ids)
            logger.info(f"实体保存成功，数量: {entity_count}")

            for i, entity_id in enumerate(entity_ids):
                if i < len(prepared_entities):
                    prepared_entities[i]['entity_id'] = entity_id
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
                    logger.warning(f"跳过关系（主体实体不存在）: '{subject_name}' -> {relationship.get('p', 'RELATES_TO')} -> '{object_name}'")
                    skipped += 1
                    continue
                if not object_id:
                    logger.warning(f"跳过关系（客体实体不存在）: '{subject_name}' -> {relationship.get('p', 'RELATES_TO')} -> '{object_name}'")
                    skipped += 1
                    continue

                prepared = {
                    'subject': subject_name,
                    'object': object_name,
                    'predicate': relationship.get('p', 'RELATES_TO'),
                    'relationship_id': hashlib.md5(f"{subject_name}_{relationship.get('p', 'RELATES_TO')}_{object_name}".encode()).hexdigest(),
                    'occurrence_time': relationship.get('ot', ''),
                    'description': relationship.get('d', ''),
                    'subject_id': subject_id,
                    'object_id': object_id
                }

                prepared_relationships.append(prepared)

            if skipped:
                logger.warning(f"跳过了 {skipped} 条关系（主体或客体实体不存在）")

            try:
                rel_result = graph_manager.add_relationships(prepared_relationships)
                rel_count = rel_result.get('count', 0)
                logger.info(f"关系保存成功，数量: {rel_count}")
            except Exception as e:
                logger.error(f"批量保存关系时出错: {e}")

        logger.info(f"数据存储完成，实体: {entity_count}, 关系: {rel_count}")
        return entity_count, rel_count

    @staticmethod
    def save_entities_only(
        entities: List[Dict[str, Any]],
        datasource: str = None
    ) -> List[Dict[str, Any]]:
        """仅保存实体（不处理关系），返回已填充 entity_id 的实体列表"""
        if not entities:
            return []

        prepared_entities = []
        for entity in entities:
            prepared = {
                'name': entity.get('n', ''),
                'type': entity.get('t', 'Entity'),
                'byname': entity.get('bn', None),
                'count': entity.get('c', 1),
                'datasource': entity.get('datasource', datasource or ''),
                'description': entity.get('d', '')
            }
            prepared_entities.append(prepared)

        try:
            result = graph_manager.add_entities(prepared_entities)
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
        entity_name_map: Dict[str, Dict[str, Any]]
    ) -> int:
        """仅保存关系，使用提供的 entity_name_map 解析 subject/object ID"""
        if not relationships:
            return 0

        prepared_relationships = []
        for relationship in relationships:
            subject_name = str(relationship.get('s', '')).strip()
            object_name = str(relationship.get('o', '')).strip()

            subject_entity = entity_name_map.get(subject_name) or entity_name_map.get(subject_name.lower())
            object_entity = entity_name_map.get(object_name) or entity_name_map.get(object_name.lower())

            predicate = relationship.get('p', 'RELATES_TO')
            prepared = {
                'subject': subject_name,
                'object': object_name,
                'predicate': predicate,
                'relationship_id': hashlib.md5(f"{subject_name}_{predicate}_{object_name}".encode()).hexdigest(),
                'occurrence_time': relationship.get('ot', ''),
                'description': relationship.get('d', ''),
                'subject_id': subject_entity.get('entity_id', '') if subject_entity else '',
                'object_id': object_entity.get('entity_id', '') if object_entity else ''
            }
            prepared_relationships.append(prepared)

        try:
            result = graph_manager.add_relationships(prepared_relationships)
            return result.get('count', 0)
        except Exception as e:
            logger.error(f"批量保存关系时出错: {e}")
            return 0
