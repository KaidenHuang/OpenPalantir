#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""remote-bash runner — 经 SSH 在远端 Linux DB 服务器执行 bash 命令、上传/下载文件。

独立多服务器配置（servers.json），基于 paramiko。
高危命令的确认由调用方（Claude，依 SKILL.md 规则）在调用前完成；本脚本不做拦截。

子命令:
  servers                         列出已配置的服务器
  test    [<server>]              连通性测试（uname / whoami / pwd）
  run     [<server>] "<cmd>"      执行 bash 命令（默认经登录 shell，源入 profile）
  put     [<server>] L R          上传文件/目录（递归）
  get     [<server>] R L          下载文件/目录（递归）

退出码 = 远端命令退出码。stdout/stderr 原样回传。
"""
import argparse
import json
import os
import posixpath
import shlex
import stat
import sys

# 强制 UTF-8 输出，避免 Windows 控制台（GBK/cp936）写非 ASCII 时乱码或报错。
# Python 3.7+ 支持 reconfigure。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DEFAULT = os.path.join(HERE, "servers.json")
EXAMPLE = os.path.join(HERE, "servers.example.json")

try:
    import paramiko
except ImportError:
    sys.stderr.write("ERROR: 未安装 paramiko。请运行: pip install paramiko\n")
    sys.exit(2)


# ----------------------------- 配置与连接 -----------------------------

def load_config(path):
    if not os.path.exists(path):
        sys.stderr.write(
            "ERROR: 配置文件不存在: %s\n"
            "首次使用请执行: cp %s %s  然后填写凭据。\n"
            % (path, EXAMPLE, CONFIG_DEFAULT)
        )
        sys.exit(2)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_server(cfg, name):
    servers = cfg.get("servers") or {}
    if not name:
        name = cfg.get("default_server")
    if not name:
        sys.stderr.write("ERROR: 未指定 SERVER 且配置中无 default_server。\n")
        sys.exit(2)
    if name not in servers:
        sys.stderr.write("ERROR: 服务器 '%s' 未配置。可选: %s\n"
                         % (name, ", ".join(sorted(servers)) or "(空)"))
        sys.exit(2)
    return name, servers[name]


def connect(srv):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = {
        "hostname": srv["host"],
        "port": int(srv.get("port", 22)),
        "username": srv["user"],
        "timeout": float(srv.get("connect_timeout", 20)),
    }
    key_path = srv.get("key_path")
    if key_path:
        key_path = os.path.expanduser(key_path)
        passphrase = srv.get("key_passphrase") or None
        pkey = None
        key_classes = []
        for attr in ("Ed25519Key", "ECDSAKey", "RSAKey", "DSSKey"):
            cls = getattr(paramiko, attr, None)
            if cls is not None:
                key_classes.append(cls)
        for cls in key_classes:
            try:
                pkey = cls.from_private_key_file(key_path, password=passphrase)
                break
            except paramiko.SSHException:
                continue
        if pkey is None:
            sys.stderr.write("ERROR: 无法加载私钥 %s（格式或口令不对？）\n" % key_path)
            sys.exit(2)
        kwargs["pkey"] = pkey
    elif srv.get("password"):
        kwargs["password"] = srv["password"]
    else:
        sys.stderr.write("ERROR: 服务器 %s@%s 缺少 password 或 key_path。\n"
                         % (srv.get("user"), srv.get("host")))
        sys.exit(2)
    client.connect(**kwargs)
    return client


# ----------------------------- 命令执行 -----------------------------

def exec_command(client, command, login_shell, pty, timeout):
    """执行远端命令，返回 (rc, stdout, stderr)。get_pty 时 stderr 并入 stdout。"""
    if login_shell:
        command = "bash -lc " + shlex.quote(command)
    _stdin, stdout, stderr = client.exec_command(
        command, timeout=timeout, get_pty=pty)
    out = stdout.read().decode("utf-8", "replace")
    err = "" if pty else stderr.read().decode("utf-8", "replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


# ----------------------------- SFTP 递归 -----------------------------

def _remote_makedirs(sftp, remote_dir):
    remote_dir = remote_dir.rstrip("/") or "/"
    if remote_dir in ("/", ".", ""):
        return
    try:
        sftp.stat(remote_dir)
        return
    except IOError:
        parent = posixpath.dirname(remote_dir)
        if parent:
            _remote_makedirs(sftp, parent)
        try:
            sftp.mkdir(remote_dir)
        except IOError:
            pass


def _put_recursive(sftp, local, remote):
    local = local.rstrip(os.sep)
    if os.path.isdir(local):
        _remote_makedirs(sftp, remote)
        for entry in os.listdir(local):
            _put_recursive(sftp,
                           os.path.join(local, entry),
                           posixpath.join(remote, entry))
    else:
        _remote_makedirs(sftp, posixpath.dirname(remote))
        sftp.put(local, remote)
        sys.stdout.write("put %s -> %s\n" % (local, remote))


def _get_recursive(sftp, remote, local):
    try:
        st = sftp.stat(remote)
    except IOError as e:
        sys.stderr.write("ERROR: 远端路径不存在 %s: %s\n" % (remote, e))
        sys.exit(1)
    if stat.S_ISDIR(st.st_mode):
        os.makedirs(local, exist_ok=True)
        for entry in sftp.listdir(remote):
            _get_recursive(sftp,
                           posixpath.join(remote, entry),
                           os.path.join(local, entry))
    else:
        parent = os.path.dirname(local)
        if parent:
            os.makedirs(parent, exist_ok=True)
        sftp.get(remote, local)
        sys.stdout.write("get %s -> %s\n" % (remote, local))


# ----------------------------- 子命令 -----------------------------

def cmd_servers(args):
    cfg = load_config(args.config)
    servers = cfg.get("servers") or {}
    default = cfg.get("default_server")
    if not servers:
        print("(无已配置服务器，请编辑 %s)" % args.config)
        return
    for name, s in servers.items():
        auth = ("key:%s" % s.get("key_path")) if s.get("key_path") else (
            "password" if s.get("password") else "?缺少凭据")
        mark = "  (默认)" if name == default else ""
        print("%-16s %s@%s:%s  [%s]%s"
              % (name, s.get("user"), s.get("host"),
                 s.get("port", 22), auth, mark))


def cmd_test(args):
    cfg = load_config(args.config)
    name, srv = resolve_server(cfg, args.server)
    client = connect(srv)
    try:
        rc, out, err = exec_command(
            client,
            "uname -a; echo '---'; whoami; echo '---'; pwd",
            True, False, args.timeout)
        sys.stdout.write("[server=%s]\n%s" % (name, out))
        if err:
            sys.stderr.write(err)
        sys.exit(rc)
    finally:
        client.close()


def cmd_run(args):
    cfg = load_config(args.config)
    name, srv = resolve_server(cfg, args.server)
    client = connect(srv)
    try:
        rc, out, err = exec_command(
            client, args.command,
            not args.no_login_shell, args.pty, args.timeout)
        sys.stdout.write(out)
        if err:
            sys.stderr.write(err)
        sys.exit(rc)
    finally:
        client.close()


def cmd_put(args):
    cfg = load_config(args.config)
    _name, srv = resolve_server(cfg, args.server)
    client = connect(srv)
    try:
        sftp = client.open_sftp()
        try:
            _put_recursive(sftp, args.local, args.remote)
        finally:
            sftp.close()
    finally:
        client.close()


def cmd_get(args):
    cfg = load_config(args.config)
    _name, srv = resolve_server(cfg, args.server)
    client = connect(srv)
    try:
        sftp = client.open_sftp()
        try:
            _get_recursive(sftp, args.remote, args.local)
        finally:
            sftp.close()
    finally:
        client.close()


# ----------------------------- 入口 -----------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="run_remote.py",
        description="remote-bash: SSH 执行远端 Linux 命令 / 传文件（paramiko）")
    p.add_argument("--config", default=CONFIG_DEFAULT,
                   help="servers.json 路径（默认 %(default)s）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("servers", help="列出已配置服务器").set_defaults(func=cmd_servers)

    pt = sub.add_parser("test", help="连通性测试")
    pt.add_argument("server", nargs="?", help="服务器名（省略用 default_server）")
    pt.add_argument("--timeout", type=float, default=30)
    pt.set_defaults(func=cmd_test)

    pr = sub.add_parser("run", help="执行 bash 命令")
    pr.add_argument("server", nargs="?", help="服务器名（省略用 default_server）")
    pr.add_argument("command", help="要执行的 bash 命令")
    pr.add_argument("--no-login-shell", action="store_true",
                    help="不源入 ~/.bash_profile 等")
    pr.add_argument("--pty", action="store_true", help="分配伪终端（sudo 等交互）")
    pr.add_argument("--timeout", type=float, default=None, help="执行超时（秒）")
    pr.set_defaults(func=cmd_run)

    pp = sub.add_parser("put", help="上传文件/目录")
    pp.add_argument("server", nargs="?")
    pp.add_argument("local", help="本地路径")
    pp.add_argument("remote", help="远端路径")
    pp.set_defaults(func=cmd_put)

    pg = sub.add_parser("get", help="下载文件/目录")
    pg.add_argument("server", nargs="?")
    pg.add_argument("remote", help="远端路径")
    pg.add_argument("local", help="本地路径")
    pg.set_defaults(func=cmd_get)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
