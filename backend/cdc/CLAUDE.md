***
description: CDC 增量同步模块指南 — 中文
alwaysApply: true
-----------------

# CDC 增量同步模块（backend/cdc/）

## 概述

基于 **Debezium Server + Redis Streams**，在全量导入后持续把源数据库（MySQL / PostgreSQL）的增量变更同步到 Neo4j 图谱。**多实例**：每个数据库连接一个独立 Debezium 进程，互不干扰；多类型：MySQL 与 PostgreSQL 共用一套机制。

## 架构与数据流

```
源库（MySQL binlog / PG WAL）
   ↓ Debezium Server（instances/{connection_id}/ 独立进程，snapshot.mode=no_data）
Redis Stream    key = {topic_prefix}.{db|schema}.{table}
   ↓ CDCConsumer（每 {conn,db} 一个后台线程，XREADGROUP，consumer group = openpalantir-{conn}）
EventProcessor（c/r → MERGE，u → MERGE，d → DELETE）
   ↓
Neo4j（实体名 {table}:{pk}，entity_id = MD5(name_type)，与全量导入一致）
```

## 文件职责

| 文件 | 职责 |
|---|---|
| `debezium_config.py` | 渲染 `application.properties`（mysql/pg 两套模板）+ `ensure_cdc_user`（建号 + 前置检测）+ 实例目录管理（`create_instance_layout`：junction 共享 + 复制 runner/run.bat）+ 路径辅助 + `clear_debezium_state` |
| `cdc_manager.py` | `CDCManager` 单例：consumer 生命周期（start/stop/pause）+ `configure_connection`（配置编排）+ `save_binlog_checkpoint` + `_resolve_topic_prefix`/`_resolve_server_id`/`_resolve_connector_type` + 调 PowerShell 启停 Debezium |
| `cdc_consumer.py` | `CDCConsumer`：后台线程消费 Redis Stream（`XREADGROUP`）+ 断点续传（last_message_id）+ `_parse_event` 解析 Debezium 消息 + 指数退避重试 |
| `event_processor.py` | Debezium 事件 → Neo4j 操作（c/r/u/d 映射 + 外键关系差量同步 + 占位节点） |
| `schema_cache.py` | 从 SQLite 加载表/列/PK/FK/entity_type + 按 `connector_type` 生成 stream key |
| `offset_store.py` | 生成 `offsets.dat`（MySQL Java 序列化字节级复刻）。**当前 `no_data` 模式不使用**（Python 不写 offset），保留代码供后续场景 |

## 关键设计

- **`topic_prefix` 按连接隔离**：`openpalantir.{connection_id前8位}`（确定性生成 + `CdcSyncState` 持久化）。Redis stream key / schema history key / offset partition key 全用它隔离，多连接同名库/表不再串台。
- **`server_id`**（MySQL 独有）：随机 10000–99999 并持久化（重启稳定，避免 MySQL slave id 冲突）。PG 用 replication slot，无 server.id。
- **多实例**：每连接一个 Debezium 进程，目录 `dependencies/debezium/instances/{connection_id}/`（`lib`/`connectors`/`config/lib` 用 `mklink /J` 联接共享 `extracted/`；`runner.jar`/`run.bat` 复制；独立 config/offset）。进程 PID 写 `debezium.pid`，按 instance_id 精确启停。
- **`snapshot.mode=no_data`**：Debezium 首次启动只做 schema 快照（建 schema history + 记位点，不读数据、不重放历史，避免 OOM）。**Python 不写 `offsets.dat`**（避免与 Debezium 周期 flush 互相覆盖）；全量导入捕获的 binlog/wal 位点只存 `CdcSyncState` 作参考与业务约束。
- **stream key 差异**（MySQL vs PG）：MySQL topic = `{prefix}.{db}.{table}`，PG topic = `{prefix}.{schema}.{table}`（当前只支持 public schema）。`SchemaCache.get_stream_keys` 按 `connector_type` 分支。
- **`configure_connection` 流程顺序**（重要）：建实例目录 → `ensure_cdc_user` → 渲染配置 → **stop Debezium → clear 旧位点 → start**。clear 必须夹在 stop/start 之间，否则运行中的 Debezium 会周期 flush 把旧 `offsets.dat` 写回。
- **CDCConsumer 幂等消费**：`xgroup_create id="$"`（只消费 group 创建后的新消息，旧残留不重放）；每条消息处理后立即 `xack`，**即使 `process_event` 失败也 xack**（靠 Neo4j MERGE 幂等兜底）。
- **`_parse_event` 消息格式**：Debezium Server Redis sink 的消息 = hash field，**field 名是 record key JSON、field 值是 record value JSON**。取 field 的值解析（不是按 `"payload"`/`"value"` 字段名查找）。
- **`quarkus.http.port=0`**：每实例随机 HTTP 端口，避免多 Quarkus 进程冲突 8080。

## 多类型支持（MySQL / PostgreSQL）

| | MySQL | PostgreSQL |
|---|---|---|
| connector | `MySqlConnector` | `PostgresConnector` |
| 库范围 | `database.include.list`（单库） | `database.dbname`（单库，逻辑复制库级） |
| 复制标识 | `server.id`（slave） | replication slot |
| cdc 账号 | `REPLICATION SLAVE/CLIENT` | `REPLICATION 角色 + SELECT + CREATE on database`（建 logical slot 需 CREATE on database） |
| publication | — | `dbz_publication FOR ALL TABLES` 由**连接账号（SUPERUSER）预建**（`FOR ALL TABLES` 需超管，cdc_user 非超管不能建；`ensure_cdc_user` 用连接账号建，cdc_user 直接用） |
| 前置检测 | `SHOW MASTER STATUS`（binlog） | `SHOW wal_level`（需 = `logical`） |
| stream key 中段 | database_name | `public`（schema） |

## 环境依赖

- **Redis**：Windows 版 5.0.14 偶发 RDB `bgsave` → `MISCONF` 禁写（干扰 CDCConsumer `xack`）。CDC 场景 Redis 只中转 stream、不需持久化，建议 `config set save ""` 关 RDB 根除。所有 Redis 客户端用 `protocol=2`（RESP2）兼容。
- **Debezium Server**：主安装 `dependencies/debezium/extracted/`；实例目录 `instances/{conn}/` 共享其 lib。run.bat 原样（`cd /d %~dp0` + 相对路径在实例目录自适应）。
- **源库**：MySQL 需 `log_bin=ON` + 连接账号具 GRANT 权限；PG 需 `wal_level=logical`（postgresql.conf，需重启）+ 账号具 SUPERUSER/CREATEROLE（建 REPLICATION 角色）。
- **进程管理**：`scripts/service/start-debezium.ps1 -InstanceId <conn_id>` 启（写 `debezium.pid`），`stop-debezium.ps1 -InstanceId` 停（按 PID）。**重配时不要用 `start-services.ps1`**——它会重复启动 Debezium 造成 server.id 冲突；用 `stop/start-debezium.ps1 -InstanceId`。

## 修改注意

- **改 `CdcSyncState` schema**（加字段等）：早期开发不做迁移，删 `backend/data/sqlite/database.db` 重启重建。
- **查 java 进程**：用 `Get-CimInstance Win32_Process`（`Get-Process | Where CommandLine` 在 PowerShell 5.1 拿不到命令行，会误判无进程）。
- **CDCConsumer 是后端进程内的线程**：`uvicorn --reload` 会杀它（需重新「增量同步」启动）；但 Debezium 实例是独立 java 进程，不受后端 reload 影响。
- **前端「配置 CDC」按钮**：仅 `mysql`/`postgresql` 类型显示（`frontend/src/components/DatabaseManagement.tsx`）。对应接口 `POST /api/cdc/{connection_id}/configure`。
- **`offset_store.py` 当前未启用**：`no_data` 模式下 Debezium 自管 offset。若未来要精确控制位点（如从全量位点开始），再启用 `write_debezium_offset`。

## 三阶段演进背景（已全部落地）

1. **阶段 1**：`topic_prefix`/`server_id` 按连接隔离——消除多连接共享 `openpalantir` 的 stream 串台。
2. **阶段 2**：多实例——每连接独立 Debezium 进程 + 实例目录 + PID 启停。
3. **阶段 3**：多类型——PostgreSQL 支持 + stream key schema 适配（`public`）。

## 参考

- 完整业务流程与事件映射：`docs/data-flow.md` §2.3
- 新环境配置与启动顺序：`docs/cdc-setup.md`
- CDC 用户建号 SQL：`scripts/install/setup-cdc-user.sql`
