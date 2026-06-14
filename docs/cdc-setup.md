# CDC 增量同步配置 | CDC Incremental Sync Setup

CDC(变更数据捕获)用于在全量导入后,持续将源数据库的增量变更同步到 Neo4j 图谱。基于 **Debezium Server**(Quarkus 独立 Java 进程,v3.5.2.Final)+ **Redis Streams** 实现。

> 全量导入与增量同步的**数据流转细节**(CDCConsumer 消费、EventProcessor 事件映射、外键差量同步等)见 [`data-flow.md`](./data-flow.md#2-数据库导入流程两阶段)。本文聚焦**新环境的配置与启动顺序**。

---

## 1. 前置条件

| 依赖 | 说明 |
|------|------|
| Debezium Server | 独立 Java 进程,从 binlog/WAL 捕获变更写入 Redis Streams |
| 源库 binlog/WAL 权限 | MySQL 需 REPLICATION SLAVE/CLIENT;PostgreSQL 需逻辑复制 |
| Redis | 接收 Debezium 事件流(`openpalantir.{db}.{table}`) |
| 已完成全量导入 | CDC 依赖全量导入捕获的 binlog/WAL 位点作为起点 |

**支持连接器**:MySQL(binlog)、PostgreSQL(WAL)、Oracle、SQL Server。

---

## 2. 用户三步准备(新环境首次启用)

### 2.1 创建 cdc 用户并赋权

在源 MySQL 用 root 执行 `scripts/install/setup-cdc-user.sql`:

- 创建 `cdc_user`,默认密码 `cdc_password`
- 赋予 REPLICATION SLAVE / CLIENT 等权限

### 2.2 修改 Debezium 配置文件

按实际源库改 `dependencies/debezium/extracted/config/application.properties` 的:

- `host` / `user` / `password`
- `database`
- `table.include.list`

(默认值为 demo 值,必须按实际环境替换)

### 2.3 重启 Debezium 服务

```powershell
scripts/service/stop-services.ps1
scripts/service/start-services.ps1
```

让新配置生效。

---

## 3. 完整启动顺序

> **关键**:必须按此顺序启动,否则 Debezium 会从 binlog 头重放整个历史,撑爆 Redis。

```
1. 上述三步准备(用户 + 配置 + 重启)
2. 全量导入(捕获 binlog 位点 → CdcSyncState + 自动写 offsets.dat)
3. start-services.ps1(启动 Neo4j + Redis + Debezium;Debezium 读 offsets.dat 从全量位点开始)
4. 前端「增量同步」按钮(启动 CDCConsumer 消费 Redis Stream → Neo4j)
```

---

## 4. 关键设计

| 要点 | 说明 |
|------|------|
| `snapshot.mode=never` | Debezium 跳过初始快照,仅消费全量导入后的增量变更 |
| 实体 ID 一致性 | CDC 使用与全量导入相同的 `{表名}:{主键值}` → MD5 方案,确保更新命中同一 Neo4j 节点 |
| 事件映射 | `c`/`r` → MERGE 实体(upsert);`u` → MERGE 更新;`d` → DELETE 实体 |
| 外键关系差量同步 | 删旧建新;FK 目标未见时创建占位节点,后续 INSERT 会 MERGE 命中 |
| 断流检测 | 启动前 `check_stream_continuity()` 比对 Redis Stream 最旧消息与上次消费位点,发现间隙则建议重新全量导入 |
| `auto_start_cdc` | 数据库导入接口参数,全量导入完成后自动启动增量同步 |
| offset 自动初始化 | 见下节 |
| 断点续传 | 每条消息处理后 ACK,定期持久化 `last_message_id` 到 SQLite |

### offset 自动初始化(避免 binlog 全量重放)

全量导入完成时(`save_binlog_checkpoint`)用捕获的 binlog 位点生成 Debezium `offsets.dat`。`cdc/offset_store.py` **复刻了 Java 序列化格式**,确保 Debezium 启动时从全量位点开始,而非从 binlog 头重放整个历史。

### 同步状态追踪

`CdcSyncState` ORM 模型(`cdc_sync_states` 表)追踪每个连接的同步状态:binlog 位点、WAL LSN、Redis Stream 消息 ID、事件计数、状态。

---

## 5. 注意事项

- **运行时重做全量导入**:若 Debezium 已在运行时重做全量导入,`offsets.dat` 会被 Debezium 周期性 flush 覆盖,**需重启 Debezium 才能让新位点生效**。
- **配置依赖**:Redis 连接通过 `.env` 的 `REDIS_HOST` / `REDIS_PORT`;Debezium Server 配置由安装脚本(`scripts/install/install-debezium.ps1`)自动生成。

---

## 6. 排错

CDC 不生效时按顺序排查:

1. Debezium Server 是否启动(`scripts/service/start-services.ps1`)
2. Redis 是否可达
3. 源库是否开启 binlog(MySQL)或逻辑复制(PostgreSQL)
4. 全量导入是否已完成(CDC 依赖其捕获的 binlog/WAL 位点)
5. 查看后端日志 `logs/backend.log` 中的 CDC 相关错误
