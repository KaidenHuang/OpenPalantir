-- ============================================================
-- OpenPalantir CDC 专用数据库账号（MySQL）
-- ============================================================
-- 用途：Debezium Server 读取源 MySQL binlog 进行增量同步（CDC）
--
-- 执行方式：在【源 MySQL】用 root 或高权限账号执行本脚本
--   mysql -u root -p < scripts/install/setup-cdc-user.sql
--   或在 MySQL 客户端 / Navicat 等工具中直接执行
--
-- 默认密码 cdc_password（与 install-debezium.ps1 生成的 application.properties 默认值一致）
-- 如需修改密码：改下方 IDENTIFIED BY 后的值，并同步修改
--   dependencies/debezium/extracted/config/application.properties 的 database.password
--   然后重启 Debezium 服务（stop-services.ps1 + start-services.ps1）
-- ============================================================

-- 1. 创建专用账号（允许从任意主机连接；生产环境建议限定来源 IP）
CREATE USER IF NOT EXISTS 'cdc_user'@'%' IDENTIFIED BY 'cdc_password';

-- 2. 授予 Debezium MySQL connector 所需权限
--    SELECT              —— 读取表数据（初始 schema/快照）
--    RELOAD              —— FLUSH（刷新表锁）
--    SHOW DATABASES      —— 列出数据库
--    REPLICATION SLAVE   —— 读取 binlog（核心）
--    REPLICATION CLIENT  —— SHOW BINARY LOGS / SHOW MASTER STATUS
GRANT SELECT, RELOAD, SHOW DATABASES, REPLICATION SLAVE, REPLICATION CLIENT
    ON *.* TO 'cdc_user'@'%';

FLUSH PRIVILEGES;

-- 3. 验证（执行后应返回当前 binlog 文件与位点，非空即成功）
-- SHOW MASTER STATUS;
