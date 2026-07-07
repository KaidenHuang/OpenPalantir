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

## 2. 一键配置 CDC（推荐）

在前端「数据库管理」选中已添加的 MySQL 数据源（需已选定目标库，且连接账号具 GRANT 权限，如 root），点击 **「配置 CDC」** 按钮，后端自动完成：

1. 用连接账号登录源 MySQL，创建 `cdc_user`（密码 `cdc_password`）并授予 REPLICATION SLAVE/CLIENT 等权限
2. 前置检测 binlog 是否开启（未开则报错并提示开启步骤）
3. 把该连接的 host/port/database 写入 `application.properties`（随机生成 `server.id` 避免冲突）
4. 清理旧库残留的 `offsets.dat` 与 Redis schema history，确保新库干净起步
5. 重启 Debezium 让新配置立即生效

> 对应接口：`POST /api/cdc/{connection_id}/configure`。
> 配置完成后仍需按 §4 顺序执行全量导入，再启动增量同步。

下方手动三步作为该按钮不可用（如连接账号无 GRANT 权限、或需连非 MySQL 源）时的回退方案。

---

## 3. 手动三步准备（回退方案）

### 3.1 创建 cdc 用户并赋权

在源 MySQL 用 root 执行 `scripts/install/setup-cdc-user.sql`:

- 创建 `cdc_user`,默认密码 `cdc_password`
- 赋予 REPLICATION SLAVE / CLIENT 等权限

### 3.2 修改 Debezium 配置文件

按实际源库改 `dependencies/debezium/extracted/config/application.properties` 的:

- `host` / `user` / `password`
- `database`
- `table.include.list`

(默认值为 demo 值,必须按实际环境替换)

### 3.3 重启 Debezium 服务

**Linux**:
```bash
bash scripts/service/stop-services.sh
bash scripts/service/start-services.sh
```

**Windows (PowerShell)**:
```powershell
scripts/service/stop-services.ps1
scripts/service/start-services.ps1
```

让新配置生效。

---

## 4. 完整启动顺序

> 多实例模型：基础设施（start-services）与 CDC 实例（「配置 CDC」）分离。Debezium 用 `snapshot.mode=no_data`，首次启动做 schema 快照建 history + 记位点（不读数据、不重放历史），无需 Python 写 `offsets.dat`。

```
1. start-services.sh（启动 Neo4j + Redis 基础设施；Debezium 不在此启动）
2. 数据库管理页面「配置 CDC」（建 cdc_user + 写实例配置 + 启动该连接的 Debezium 实例到 instances/{conn}/）
3. 「分析 Schema」+「导入图谱」（全量导入，捕获 binlog 位点 → CdcSyncState）
4. 「增量同步」（启动 CDCConsumer 消费 Redis Stream → Neo4j）
```

> 手动启停某连接的 Debezium 实例：`start-debezium.sh <conn_id>` / `stop-debezium.sh <conn_id>`（Linux）或 `start-debezium.ps1 -InstanceId <conn_id>` / `stop-debezium.ps1 -InstanceId <conn_id>`（Windows）。

---

## 5. 关键设计

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

## 6. 注意事项

- **运行时重做全量导入**:若 Debezium 已在运行时重做全量导入,`offsets.dat` 会被 Debezium 周期性 flush 覆盖,**需重启 Debezium 才能让新位点生效**。
- **配置依赖**:Redis 连接通过 `.env` 的 `REDIS_HOST` / `REDIS_PORT`;Debezium Server 配置由安装脚本（`scripts/install/install-debezium.sh`（Linux）或 `scripts/install/install-debezium.ps1`（Windows））自动生成。

---

## 7. 排错

CDC 不生效时按顺序排查:

1. Debezium Server 是否启动（`bash scripts/service/start-services.sh`（Linux）或 `scripts/service/start-services.ps1`（Windows））
2. Redis 是否可达
3. 源库是否开启 binlog(MySQL)或逻辑复制(PostgreSQL)
4. 全量导入是否已完成(CDC 依赖其捕获的 binlog/WAL 位点)
5. 查看后端日志 `logs/backend.log` 中的 CDC 相关错误
