from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# Neo4j数据库配置
NEO4J_URI = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', '')

class Neo4jConnection:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD)
        )
    
    def close(self):
        if self.driver:
            self.driver.close()
    
    def execute_query(self, query, parameters=None):
        with self.driver.session() as session:
            result = session.run(query, parameters)
            return [record for record in result]
    
    def initialize_schema(self):
        """初始化Neo4j schema"""
        # 创建约束（统一使用 :Entity 标签，type 为属性）
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
        ]
        
        with self.driver.session() as session:
            for constraint in constraints:
                session.run(constraint)

# 创建全局Neo4j连接实例
neo4j_conn = Neo4jConnection()