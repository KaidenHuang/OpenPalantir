"""④ 表格导入的落库用例（需 Neo4j）：受控类型与边类型、代际佐证、来源回收

单元测试（test_table_import.py）只验交给落库缝的语义行；这里验语义行经
`EntityDataStore.save_all` 之后在图里长什么样——类型归一、节点 ID = MD5(名)、
边类型取自本体词表、`URI@content_hash` 佐证，以及 `recycle_datasource` 能否把
本来源产出摘干净。Neo4j 不可用时整体 skip（`-m unit` 不碰这一层）。

用例自带取值并按名清别名缓存：别名层是跨来源的 Redis Hash，撞上开发图里已有的
同名业务对象会把待写实体整批重定向掉，测的就不是本来源的产出了。

不测重跑幂等：落库缝在第二次导入时把已存在的实体剔出待写列表，连带跳过它们的
全部关系，`entity_count` 归 0。图谱状态没坏（首轮已写入），但计数与补写语义
有问题，属另一任务的改动范围。
"""
import hashlib
import uuid

import pytest

from entity_extraction.document import table_service
from test_table_import import column, digest, leaf, make_summary, write_csv

HEADER = ["部门", "省份", "销售额"]
ROWS = [["表格落库部A", "表格落库省X", "120"], ["表格落库部B", "表格落库市Y", "98"]]
NAMES = ["表格落库部A", "表格落库部B", "表格落库省X", "表格落库市Y"]
RELS = [{"s": "部门", "p": "属于", "o": "省份"}]

NODES = ("MATCH (e:Entity) WHERE $evidence IN e.datasources "
         "RETURN e.name AS name, e.type AS type, e.id AS id")
EDGES = ("MATCH (a:Entity)-[r]->(b:Entity) WHERE $evidence IN r.datasources "
         "RETURN type(r) AS rel_type, r.predicate AS p, a.name AS s, b.name AS o")


def _drop_aliases():
    """按名清掉别名缓存条目（Redis 不可用时无缓存，跳过即等价）"""
    from knowledge_graph.alias_cache import AliasCache

    cache = AliasCache()
    if cache.available:
        cache._redis.hdel("entity_aliases", *NAMES)


@pytest.fixture
def live_neo4j():
    from config.neo4j_config import neo4j_conn

    try:
        neo4j_conn.initialize_schema()
        neo4j_conn.execute_query("RETURN 1 AS ok", {})
    except Exception as exc:
        pytest.skip(f"Neo4j 不可用，跳过落库用例: {exc}")
    return neo4j_conn


@pytest.mark.integration
def test_table_import_writes_and_recycles_real_graph(tmp_path, monkeypatch, live_neo4j):
    from knowledge_graph.recycle import recycle_datasource

    path = write_csv(tmp_path, HEADER, ROWS)
    monkeypatch.setattr(table_service, "resolve_source_file", lambda datasource: str(path))
    datasource = f"DOC://table-it-{uuid.uuid4().hex[:8]}/表格落库样例.csv"
    evidence_hash = digest(path)
    evidence = f"{datasource}@{evidence_hash}"
    columns = [column("部门", "entity", "organization", primary=True),
               column("省份", "entity", "location"),
               column("销售额", "attribute")]
    summary = make_summary(path, [leaf("月度汇总", columns, RELS)])
    params = {"evidence": evidence}

    _drop_aliases()
    recycle_datasource(datasource)
    try:
        result = table_service.import_tables(summary, datasource,
                                             evidence_hash=evidence_hash)
        assert result["entity_count"] == 4
        assert result["relationship_count"] == 2

        nodes = {row["name"]: row for row in live_neo4j.execute_query(NODES, params)}
        assert set(nodes) == set(NAMES)
        assert {row["type"] for row in nodes.values()} == {"organization", "location"}
        assert all(row["id"] == hashlib.md5(name.encode("utf-8")).hexdigest()
                   for name, row in nodes.items())

        edges = live_neo4j.execute_query(EDGES, params)
        assert {(row["s"], row["p"], row["o"]) for row in edges} == {
            ("表格落库部A", "属于", "表格落库省X"),
            ("表格落库部B", "属于", "表格落库市Y")}
        # 边类型取自本体词表：中文 key 原样落库，不留 raw_predicate
        assert {row["rel_type"] for row in edges} == {"属于"}

        attributes = live_neo4j.execute_query(
            "MATCH (e:Entity) WHERE $evidence IN e.datasources AND e.name = $name "
            "RETURN e.attributes AS attributes", {"evidence": evidence, "name": "表格落库部A"})
        assert '"销售额": "120"' in attributes[0]["attributes"]
    finally:
        recycle_datasource(datasource)
        _drop_aliases()

    assert live_neo4j.execute_query(NODES, params) == []
    assert live_neo4j.execute_query(EDGES, params) == []
