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

    def execute_read_query(self, query, parameters=None):
        """以只读会话执行 Cypher；执行前用 EXPLAIN 解析计划树，拒绝任何含写算子（含嵌套 CALL 子查询）的语句。

        说明：直连 bolt 上 `default_access_mode=READ_ACCESS` 不强制写入拦截（写语句照常执行），
        因此服务端语义由计划检查兜底；写算子出现在计划中即拒（ValueError，调用方映射 400）。
        """
        from neo4j import READ_ACCESS
        self._assert_read_only(query, parameters or {})
        with self.driver.session(default_access_mode=READ_ACCESS) as session:
            result = session.run(query, parameters)
            return [record for record in result]

    _WRITE_OPERATOR_WORDS = ("Create", "Merge", "Delete", "Set", "Remove", "Load")

    def _assert_read_only(self, query: str, parameters: dict = None) -> None:
        """EXPLAIN 不执行任何写操作，其计划树是判断只读语义的唯一可靠出口。"""
        with self.driver.session() as session:
            summary = session.run("EXPLAIN " + query, parameters).consume()
        plan = getattr(summary, "plan", None)
        stack = [plan]
        write_ops = []
        while stack:
            node = stack.pop()
            if node is None:
                continue
            op = getattr(node, "operator_type", "") or ""
            if any(word in op for word in self._WRITE_OPERATOR_WORDS):
                write_ops.append(op)
            stack.extend(getattr(node, "children", []) or [])
        if write_ops:
            raise ValueError(f"只读接口拒绝包含写操作的查询: {', '.join(sorted(set(write_ops)))}")
    
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