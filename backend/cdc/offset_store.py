"""
生成 Debezium FileOffsetBackingStore 的 offsets.dat（Java 序列化格式）。

逆向自 Debezium 实际生成的 offsets.dat（已用 od 字节级验证）。采用全量字节生成，
结构 100% 复刻 Debezium 的输出，避免解析/patch Java 序列化的脆弱性。

文件结构（单 entry HashMap）::

    ObjectOutputStream header(ACED0005)
    HashMap{1 entry}:
        key   = byte[] = ASCII JSON '["redis",{"server":"<topic_prefix>"}]'   (Debezium Server 分区键)
        value = byte[] = ASCII JSON '{"ts_sec":..,"file":"..","pos":..,...}'  (MySQL binlog 位点)
    TC_ENDBLOCKDATA

全量导入完成后由 ``cdc_manager.save_binlog_checkpoint()`` 调用，确保 Debezium 启动时
从全量导入位点（而非 binlog 头）开始消费，避免重放整个历史撑爆 Redis。
"""
import os
import struct

from system.logger import logger

# ── Java 序列化常量（从真实 offsets.dat 字节级提取，固定不变）──────────────
# ObjectOutputStream magic(0xACED) + version(5)
_OOS_HEADER = bytes.fromhex("ACED0005")

# HashMap classdesc + 字段(loadFactor=0.75 / threshold=12) + blockdata(capacity=16, size=1)
# 与 HashMap 内容无关——固定为单 entry 结构
_HASHMAP_HEADER = bytes.fromhex(
    "73720011"                              # TC_OBJECT(73) TC_CLASSDESC(72) 类名长度=17
    "6a6176612e7574696c2e486173684d6170"    # "java.util.HashMap"
    "0507dac1c31660d1"                      # serialVersionUID
    "030002"                                # flags=SC_SERIALIZABLE, 2 fields
    "46000a6c6f6164466163746f72"            # F(float) "loadFactor"
    "4900097468726573686f6c64"              # I(int) "threshold"
    "7870"                                  # TC_ENDBLOCKDATA(78) TC_NULL(70)
    "3f400000"                              # loadFactor = 0.75f
    "0000000c"                              # threshold = 12
    "7708"                                  # TC_BLOCKDATA(77) len=8
    "00000010"                              # capacity = 16
    "00000001"                              # size = 1
)

# byte[] 的 classdesc（首次出现，完整描述符）；key 和 value 都是 byte[]，共享此 classdesc
_BYTEARRAY_CLASSDESC = bytes.fromhex(
    "75720002"                              # TC_ARRAY(75) TC_CLASSDESC(72) 类名长度=2
    "5b42"                                  # "[B"
    "acf317f8060854e0"                      # byte[] serialVersionUID
    "020000"                                # flags=SC_SERIALIZABLE, 0 fields
    "7870"                                  # TC_ENDBLOCKDATA TC_NULL
)

# value byte[] 复用 byte[] classdesc：TC_ARRAY + TC_REFERENCE 指向 handle #2（byte[] classdesc）
_BYTEARRAY_REF = bytes.fromhex("7571007e0002")

# TC_ENDBLOCKDATA，闭合 HashMap 的 blockdata
_TC_ENDBLOCKDATA = bytes.fromhex("78")


def _build_partition_key(topic_prefix: str) -> bytes:
    """partition key = ASCII JSON: ["redis",{"server":"<topic_prefix>"}]"""
    return ('["redis",{"server":"%s"}]' % topic_prefix).encode("utf-8")


def _build_offset_value(binlog_file: str, binlog_pos: int, ts_sec: int) -> bytes:
    """offset value = ASCII JSON（MySQL binlog 位点）"""
    return (
        '{"ts_sec":%d,"file":"%s","pos":%d,"row":0,"server_id":0,"event":0}'
        % (ts_sec, binlog_file, binlog_pos)
    ).encode("utf-8")


def _serialize_offsets_dat(key: bytes, value: bytes) -> bytes:
    """组装完整 offsets.dat 字节流。"""
    return b"".join([
        _OOS_HEADER,
        _HASHMAP_HEADER,
        _BYTEARRAY_CLASSDESC,
        struct.pack(">I", len(key)),    # key 数组长度（4 字节大端）
        key,
        _BYTEARRAY_REF,
        struct.pack(">I", len(value)),  # value 数组长度（4 字节大端）
        value,
        _TC_ENDBLOCKDATA,
    ])


def _default_offset_file() -> str:
    """推导默认 offsets.dat 路径。

    优先读环境变量 DEBEZIUM_OFFSET_FILE；否则推导为
    <project_root>/dependencies/debezium/extracted/data/debezium/offsets/offsets.dat
    （与 application.properties 的相对路径 + run.bat 的 cd /d "%~dp0" 一致）。
    """
    env_path = os.getenv("DEBEZIUM_OFFSET_FILE")
    if env_path:
        return env_path
    # backend/cdc/offset_store.py → 项目根目录上溯两级
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(
        project_root, "dependencies", "debezium", "extracted",
        "data", "debezium", "offsets", "offsets.dat",
    )


def write_debezium_offset(binlog_file: str, binlog_pos: int,
                          topic_prefix: str = "openpalantir",
                          offset_file: str = None, ts_sec: int = 0) -> str:
    """用 binlog 位点生成 offsets.dat（原子写入）。

    Args:
        binlog_file: MySQL binlog 文件名（如 ``HUANG-bin.000010``）。
        binlog_pos:  binlog 位点（整数）。
        topic_prefix: Debezium ``topic.prefix``，决定 partition key 的 server 字段。
        offset_file: 目标文件路径；默认推导或读 ``DEBEZIUM_OFFSET_FILE`` 环境变量。
        ts_sec: 事件时间戳（秒），默认 0。

    Returns:
        写入的文件绝对路径。

    Note:
        MySQL 专用。PostgreSQL 的 offset 格式不同（WAL LSN），如需支持需另实现。
        必须在 Debezium Server 启动前调用；Debezium 运行中会周期性 flush 覆盖此文件。
    """
    if not binlog_file or not binlog_pos:
        raise ValueError("binlog_file 和 binlog_pos 不能为空")

    offset_file = offset_file or _default_offset_file()
    key = _build_partition_key(topic_prefix)
    value = _build_offset_value(binlog_file, int(binlog_pos), ts_sec)
    data = _serialize_offsets_dat(key, value)

    offset_dir = os.path.dirname(offset_file)
    if offset_dir:
        os.makedirs(offset_dir, exist_ok=True)
    tmp_file = offset_file + ".tmp"
    with open(tmp_file, "wb") as f:
        f.write(data)
    os.replace(tmp_file, offset_file)

    logger.info(
        "[offset_store] 已写入 Debezium offset: file=%s, binlog=%s:%s, topic_prefix=%s",
        offset_file, binlog_file, binlog_pos, topic_prefix,
    )
    return offset_file
