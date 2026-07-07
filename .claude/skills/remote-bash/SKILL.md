---
name: remote-bash
description: 经 SSH 连接远端 Linux DB 服务器执行 bash 命令并上传/下载文件（独立多服务器配置，基于 paramiko）。当用户想在远端 Linux DB 服务器上跑命令/脚本、远程构建或部署、查看远程状态、上传代码或产物到服务器、从服务器下载日志或文件，或提到 SSH 远程执行、连 DB 服务器跑命令、把文件传到服务器、在服务器上编译 mariadb/mariabackup、查看远程进程/磁盘/日志时，务必使用本 skill。高危命令（rm、sudo、DROP、TRUNCATE、shutdown 等）会先征得用户同意再执行。
---

# remote-bash — SSH 连远端 Linux DB 服务器执行命令与传文件

从本机经 SSH 登录远端 Linux DB 服务器，**执行 bash 命令**、**上传/下载文件**。与 `run-remote-tests` 解耦：自带独立的 `servers.json`，可登记**多台服务器**按名选择；凭据只在本机、不外泄。

> 命令执行默认经**登录 shell**（`bash -lc`），因此 `~/.bash_profile`/`~/.bashrc`（含 `ORACLE_HOME`、`PATH` 等）会被源入，oracle/mysql 客户端环境直接可用。

## 何时使用

- 「在 DB 服务器上跑一下 xxx」「连上服务器看看 / 执行这条命令」
- 「把这个目录传到服务器 / 上传源码去编译」「把服务器的日志拉下来」
- 「在服务器上编译 mariabackup / mariadb」「查看远程磁盘、进程、端口」
- 任何"我要 SSH 到那台 Linux 机器上做点事"的意图

## 前置条件

1. **本机 Python 3 + paramiko**：`pip install paramiko`（缺失时脚本会明确提示）。
2. **`servers.json`（唯一需人工填的文件）**：首次使用从 [`servers.example.json`](servers.example.json) 拷贝：
   ```
   cp .claude/skills/remote-bash/servers.example.json .claude/skills/remote-bash/servers.json
   ```
   然后填写各服务器的 `host`/`user` 与（`password` 或 `key_path`）。`servers.json` 已被 `.gitignore` 忽略，勿提交。

## 配置文件 servers.json

```jsonc
{
  "default_server": "ora-dev",          // run/put/get 不带 --server 时用它
  "servers": {
    "ora-dev": {
      "host": "10.4.240.126", "port": 22, "user": "oracle",
      "password": "口令填这里",          // 与 key_path 二选一
      "connect_timeout": 20
    },
    "mysql-key": {
      "host": "10.4.240.200", "port": 22, "user": "mysql",
      "key_path": "~/.ssh/id_rsa",      // 私钥免密（优先于 password）
      "key_passphrase": ""              // 私钥有口令才填
    }
  }
}
```

- 每个 server 至少要有 `host` + `user`，再加 `password` **或** `key_path` 之一。
- `port` 默认 22；`connect_timeout` 默认 20 秒。
- 私钥自动尝试 Ed25519 / ECDSA / RSA / DSS。

## 命令速查

```
RB=.claude/skills/remote-bash/run_remote.py
python $RB servers                                      # 列出已配置服务器
python $RB test    [<server>]                            # 连通性测试（uname/whoami/pwd）
python $RB run     [<server>] "<bash 命令>"              # 执行命令（默认源入 profile）
python $RB run     [<server>] "<cmd>" --no-login-shell   # 不源入 profile
python $RB run     [<server>] "<cmd>" --pty              # 分配伪终端（sudo 等）
python $RB put     [<server>] <本地路径> <远端路径>        # 上传文件/目录（递归）
python $RB get     [<server>] <远端路径> <本地路径>        # 下载文件/目录（递归）
```

`<server>` 省略时用 `default_server`。脚本退出码 = 远端命令退出码，stdout/stderr 原样回传。

## 工作流（核心：先判定是否高危）

1. **确定目标服务器**：从用户意图或上下文确定 `<server>`；拿不准就 `servers` 列一下。
2. **判定命令是否高危**（见下方规则）。
   - **只读/查询/在自己目录内构建部署**（`ls`/`cat`/`df`/`ps`/`grep`/`select`/`show`/`cmake`/`make`/`git`/写自己工作目录等）→ **直接执行**。
   - **高危** → 先用 `AskUserQuestion` 把**完整命令 + 目标服务器**展示给用户，征得同意后再执行。
3. **执行**：调用 `python $RB run <server> "<cmd>"`，把输出原样呈现给用户。
4. **传文件**同理：`put`/`get`，路径要写全；上传到/下载自系统目录属高危，同样先确认。

## 高危命令确认规则

命中以下任一即为高危，**必须先用 `AskUserQuestion` 征得用户同意再执行**（展示完整命令与目标 server）：

- **删除/破坏文件系统**：`rm`、`rm -rf`、`rmdir`、`unlink`、`dd if=`、`mkfs`、`shred`、`> /dev/sd*`、覆盖系统文件或目录（`/etc`、`/boot`、`/usr`、`/var`、`/lib`、`/root`、`/home/<他人>`）。
- **权限提升/批量改权**：`sudo`、`su `、`chmod -R`、`chown -R`、`chmod 777`。
- **进程/系统控制**：`shutdown`、`reboot`、`halt`、`poweroff`、`init`、`telinit`、`kill -9`、`killall`、`pkill`、`systemctl stop/restart`。
- **数据库破坏**：`DROP DATABASE/TABLE/SCHEMA/USER`、`TRUNCATE`、`DELETE FROM`（尤其无 `WHERE`）、`SHUTDOWN`、清空表空间/数据文件。
- **危险组合**：`curl ... | sh`/`bash`、`wget ... | sh`、fork 炸弹、改 `crontab`、改 `/etc/fstab`、`iptables -F`、`passwd`。
- **通配删除**：含 `*` 且配合 `rm`/覆盖重定向。

判定原则：宁可多问，不可误删。拿不准某命令是否高危时，**按高危处理**（先问）。

## 长任务（耗时命令）：后台执行 + 轮询

远端命令若**可能耗时较长**（编译/构建、大数据导入导出、长脚本、`yum update`、大规模 `rsync`/`find` 等——总之任何可能超过 SSH 单次同步等待窗口的命令），**不要**直接 `python $RB run "<cmd>"` 同步干等：本机到远端的通道会一直挂着，既容易超时/中断，也看不到中间进度。正确做法是 **`nohup` 后台化 + 输出重定向到日志 + 回显 PID + 周期轮询**：

```
RB=.claude/skills/remote-bash/run_remote.py
# 1) 后台启动：nohup 免挂断、> 落日志、& 放后台、echo $! 立即回显 PID
python $RB run "cd /work && nohup bash -c '<长命令>' > /work/run.log 2>&1 & echo PID=\$!"

# 2) 周期轮询（隔几分钟一次，直到进程消失）：存活 + 日志尾部 + 错误
python $RB run "pgrep -af '<命令关键字>' | head; echo '--- 尾部 ---'; tail -15 /work/run.log; echo '--- 错误 ---'; grep -iE 'error|fatal' /work/run.log | tail"
```

要点：
- **`nohup ... &`** 让任务脱离 SSH 会话独立存活；**`> run.log 2>&1`** 把 stdout/stderr 都落盘，便于事后排查；**`echo $!`** 回显 PID，后续用 `ps -p <PID>` 或 `pgrep` 定位。
- **轮询判活**：`pgrep -af '<关键字>'` 有输出=还在跑，空=已结束；配 `tail` 看最新进度、`grep -iE 'error|fatal'` 抓致命错误。
- **不要在本机 `sleep` 干等整个任务时长**——会撞到本机命令超时上限。要等就短 sleep（几十秒）查一次，或干脆隔几分钟回来查。
- **结束判定**：进程消失后，看日志尾部是否出现完成标志、`grep` 是否无新增致命错误、预期产物是否就位，三者满足即成功。

## 文件传输说明

> **⚠️ Windows + Git-Bash 路径转换坑（put/get 必看）**
> 在 Windows 本机用 Git-Bash 调 `put`/`get` 时，**独立的 `/abs/远端路径` 参数会被 MSYS2 自动转成 `C:/Program Files/Git/abs/...`**，于是文件被传到远端一个错误的 `C:` 垃圾目录、**真正的目标文件根本没更新**（而且 `put` 会 `mkdir -p`，还会在远端留下垃圾目录）。任选一种修法：
> - 命令前加 `export MSYS_NO_PATHCONV=1`（推荐），或 `MSYS2_ARG_CONV_EXCL='*'`；
> - 或把远端路径写成 `//abs/path`（双斜杠，MSYS2 不转）。
>
> 注意：`run "<整条命令串>"` 里**嵌套**的路径（如 `cd /work && ...`）**不受影响**——只有作为**独立参数**传入的绝对路径才被转。所以执行命令时无需此开关，仅 `put`/`get` 的远端路径参数需要。
>
> **上传后务必校验**：`md5sum` 比对本地与远端文件，一致才说明真传对了。

- `put`/`get` 基于 SFTP，递归处理目录，自动 `mkdir -p`。
- 超大树（如上万文件的源码树）SFTP 偏慢；此时改用命令管道更高效：
  `python $RB run <server> "tar -C <远端父目录> -xf -"` 配合本机 `tar -cf - -C <本地目录> . | ssh ...`（仅当本机有 tar 时）。
- 上传到系统目录（`/etc`、`/usr` 等）或下载覆盖本机重要文件 → 属高危，先确认。

## 排错

| 现象 | 处理 |
|:-----|:-----|
| `paramiko 未安装` | `pip install paramiko` |
| `配置文件不存在` | 按「前置条件」从 example 拷贝 `servers.json` 并填写 |
| `服务器 'xxx' 未配置` | `servers` 查可用名；拼错或漏填 `default_server` |
| 连接超时/拒绝 | 检查 `host`/`port`、网络、防火墙；oracle 服务器常见 22 被限 |
| 私钥加载失败 | 确认 `key_path`、`key_passphrase`；Ed25519 需较新 paramiko |
| 命令找不到（ORACLE_HOME 等） | 默认已 `bash -lc` 源入 profile；若仍缺，让命令自带 `source ~/.bash_profile && ...` |
| `sudo` 卡住 | 远端 sudo 多需密码/pty；用 `--pty` 或改用 NOPASSWD 账号 |
| 远端退出码非 0 | 脚本原样返回该码；看 stderr 排查，非脚本自身错误 |
| 长命令跑到一半超时/连接断开 | 别同步干等——改用 nohup 后台化 + 日志 + 轮询（见「长任务」节） |
| `put`/`get` 后远端文件没变（Git-Bash） | 远端绝对路径被 MSYS2 转成了 `C:/Program Files/Git/...`；加 `MSYS_NO_PATHCONV=1` 重传，并 `md5sum` 比对 |

凭据只在本地 `servers.json`（已 `.gitignore`）。本 skill 不修改远端任何东西——除非用户命令本身要求。
