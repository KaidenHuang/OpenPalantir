import os
import json
import time
from typing import List, Dict, Any, Optional
import redis
from config.neo4j_config import neo4j_conn
from system.logger import logger

class GraphPerformanceOptimizer:
    def __init__(self):
        """初始化图谱性能优化器"""
        # 初始化Redis连接（用于缓存）
        try:
            self.redis_client = redis.Redis(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', '6379')),
                db=int(os.getenv('REDIS_DB', '0'))
            )
            # 测试连接
            self.redis_client.ping()
            self.use_redis = True
        except Exception:
            # 如果Redis不可用，不使用缓存
            self.use_redis = False

        # 缓存配置
        self.cache_ttl = int(os.getenv('CACHE_TTL', '3600'))  # 缓存过期时间（秒）

        # 批量操作配置
        self.batch_size = int(os.getenv('BATCH_SIZE', '100'))  # 批量操作大小

    def create_indexes(self):
        """创建Neo4j索引"""
        try:
            logger.info("[create_indexes] 开始创建Neo4j索引")

            # 实体 ID 唯一约束（MATCH {id} 的核心索引，必须存在！）
            try:
                neo4j_conn.execute_query(
                    "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS "
                    "FOR (e:Entity) REQUIRE e.id IS UNIQUE"
                )
                logger.info("[create_indexes] 实体 ID 唯一约束已就绪")
            except Exception as e:
                logger.warning(f"创建实体 ID 约束失败（可能已存在重复 ID）: {e}")

            # 实体属性索引
            indexes = [
                "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.name)",
                "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.type)",
            ]
            for index in indexes:
                neo4j_conn.execute_query(index)

            # 实体全文搜索索引（含 datasource 字段，支持按数据源名搜索）
            try:
                neo4j_conn.execute_query("DROP INDEX entities_fts IF EXISTS")
            except Exception:
                pass
            try:
                neo4j_conn.execute_query(
                    "CREATE FULLTEXT INDEX entities_fts IF NOT EXISTS "
                    "FOR (n:Entity) ON EACH [n.name, n.description, n.byname, n.datasource]"
                )
            except Exception as e:
                logger.warning(f"创建全文索引失败: {e}")

            # 关系属性索引（加速 MERGE 中 relationship_id 的存在性检查）
            try:
                neo4j_conn.execute_query(
                    "CREATE INDEX rel_relationship_id IF NOT EXISTS "
                    "FOR ()-[r:RELATED_TO]-() ON (r.relationship_id)"
                )
                logger.info("[create_indexes] 关系属性索引创建成功")
            except Exception as e:
                logger.warning(f"创建关系属性索引失败: {e}")

            logger.info("[create_indexes] 索引创建成功")
            return {"status": "success", "message": "索引创建成功"}
        except Exception as e:
            logger.error(f"[create_indexes] 创建索引失败: {str(e)}")
            return {"status": "error", "message": f"创建索引失败: {str(e)}"}

    def clear_cache(self, pattern: str = "graph:*"):
        """清除缓存"""
        logger.info(f"[clear_cache] 开始清除缓存: pattern={pattern}")
        if self.use_redis:
            try:
                keys = self.redis_client.keys(pattern)
                if keys:
                    self.redis_client.delete(*keys)
                logger.info(f"[clear_cache] 清除缓存成功: 清除了 {len(keys)} 个缓存项")
                return {"status": "success", "message": f"清除了 {len(keys)} 个缓存项"}
            except Exception as e:
                logger.error(f"[clear_cache] 清除缓存失败: {str(e)}")
                return {"status": "error", "message": f"清除缓存失败: {str(e)}"}
        logger.info("[clear_cache] Redis不可用，跳过缓存清除")
        return {"status": "warning", "message": "Redis不可用，跳过缓存清除"}

    def cache_graph_data(self, key: str, data: Any):
        """缓存图谱数据"""
        if self.use_redis:
            try:
                # 将数据序列化为JSON
                serialized_data = json.dumps(data)
                # 设置缓存，带过期时间
                self.redis_client.setex(
                    f"graph:{key}",
                    self.cache_ttl,
                    serialized_data
                )
                return True
            except Exception:
                # 缓存失败不影响主流程
                return False
        return False

    def get_cached_graph_data(self, key: str) -> Optional[Any]:
        """获取缓存的图谱数据"""
        if self.use_redis:
            try:
                # 从缓存获取数据
                serialized_data = self.redis_client.get(f"graph:{key}")
                if serialized_data:
                    # 反序列化数据
                    return json.loads(serialized_data)
            except Exception:
                # 缓存读取失败不影响主流程
                pass
        return None

    def optimize_query(self, query: str) -> str:
        """优化Cypher查询"""
        # 简单的查询优化规则
        optimized_query = query

        # 移除多余的空格
        import re
        optimized_query = re.sub(r'\s+', ' ', optimized_query)

        # 添加LIMIT子句（如果没有）
        if 'LIMIT' not in optimized_query.upper() and ('MATCH' in optimized_query.upper() or 'RETURN' in optimized_query.upper()):
            # 找到RETURN子句的位置
            return_pos = optimized_query.upper().find('RETURN')
            if return_pos != -1:
                # 在RETURN之后添加LIMIT
                return_end = optimized_query.find(';', return_pos)
                if return_end == -1:
                    return_end = len(optimized_query)
                optimized_query = optimized_query[:return_end] + ' LIMIT 1000' + optimized_query[return_end:]

        return optimized_query

    def get_query_performance(self, query: str) -> Dict[str, Any]:
        """获取查询性能信息"""
        try:
            # 记录开始时间
            start_time = time.time()

            # 执行查询
            result = neo4j_conn.execute_query(query)

            # 记录结束时间
            end_time = time.time()
            execution_time = end_time - start_time

            # 计算结果大小
            result_size = len(result)

            return {
                "status": "success",
                "query": query,
                "execution_time": execution_time,
                "result_size": result_size
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"获取查询性能失败: {str(e)}"
            }

# 创建全局图谱性能优化器实例
graph_performance = GraphPerformanceOptimizer()