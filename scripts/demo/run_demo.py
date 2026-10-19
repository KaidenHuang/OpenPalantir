#!/usr/bin/env python3
"""
一键演示：示例文档 → 摘要树 → 本体抽取 → Wiki 生成 → 治理报告

只依赖标准库，任何平台都能跑；后端需已在 --base-url 上运行。
用法：
    python scripts/demo/run_demo.py
    python scripts/demo/run_demo.py --domain rd_efficiency --pack examples/ontology/rd_efficiency.yaml
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TERMINAL_OK = ("completed",)
TERMINAL_BAD = ("failed", "stopped")


class DemoError(Exception):
    pass


def http_call(base_url: str, method: str, path: str, payload=None, timeout: int = 60):
    url = f"{base_url}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except (ValueError, AttributeError):
            pass
        raise DemoError(f"{method} {path} → HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise DemoError(f"{method} {path} 请求失败: {e.reason}") from e


def step(index: int, total: int, text: str) -> None:
    print(f"\n[{index}/{total}] {text}")


def check_backend(base_url: str) -> None:
    try:
        info = http_call(base_url, "GET", "/", timeout=10)
    except DemoError as e:
        raise DemoError(
            f"连不上后端 {base_url}：{e}\n"
            "请先启动服务：cd backend && uvicorn main:app --port 8000"
        ) from e
    print(f"    后端在线: {info.get('message', 'OK')}")


def check_model(base_url: str) -> None:
    """抽取环节必须有可用模型，否则 /extract 返回 503"""
    resp = http_call(base_url, "GET", "/api/model/models")
    models = resp.get("models", [])
    usable = [m for m in models if m.get("enabled") and m.get("status") == "available"]
    if not usable:
        enabled = [m["name"] for m in models if m.get("enabled")]
        raise DemoError(
            "没有「已启用且可连接」的模型，抽取与 Wiki 生成无法进行。\n"
            f"    当前模型：{[m.get('name') for m in models] or '（空）'}；已启用：{enabled or '（无）'}\n"
            "    请在「模型管理」页面新增并启用一个模型（Ollama 本地模型或 OpenAI 兼容 API），"
            "或先运行 bash scripts/download_models.sh"
        )
    print(f"    使用模型: {usable[0].get('name')} ({usable[0].get('model_name')})")


def fetch_document_formats(base_url: str) -> tuple:
    """可解析的扩展名以内容提取注册表为准，不在脚本里重复一份清单"""
    resp = http_call(base_url, "GET", "/api/sources/formats")
    formats = tuple(ext.lower() for ext in resp.get("formats", []))
    if not formats:
        raise DemoError("GET /api/sources/formats 未返回可用扩展名")
    print(f"    后端支持的文件类型: {', '.join(formats)}")
    return formats


def import_pack(base_url: str, pack_path: Path, persist: bool) -> None:
    if not pack_path.is_file():
        raise DemoError(f"本体包不存在: {pack_path}")
    text = pack_path.read_text(encoding="utf-8")
    resp = http_call(base_url, "POST", "/api/ontology/packs",
                     {"yaml": text, "persist": persist})
    print(f"    导入 {resp.get('name')}: {resp.get('object_type_count')} ObjectType / "
          f"{resp.get('link_type_count')} LinkType")


def ensure_source(base_url: str, name: str, docs_dir: Path) -> str:
    resp = http_call(base_url, "GET", "/api/sources")
    target = os.path.normcase(str(docs_dir.resolve()))
    for s in resp.get("sources", []):
        if s.get("source_type") == "local" and \
                os.path.normcase(str(Path(s.get("path", "")).resolve())) == target:
            print(f"    复用已有文档源: {s['name']} ({s['id']})")
            return s["id"]
    created = http_call(base_url, "POST", "/api/sources",
                        {"name": name, "path": str(docs_dir.resolve()), "source_type": "local"})
    source = created["source"]
    print(f"    新建文档源: {source['name']} ({source['id']})")
    return source["id"]


def wait_task(base_url: str, task_id: str, label: str, timeout: int) -> None:
    start = time.time()
    last = None
    while time.time() - start < timeout:
        status = http_call(base_url, "GET", f"/api/task/{task_id}")
        state = status.get("status")
        if state != last:
            print(f"    {label}: {state}")
            last = state
        if state in TERMINAL_OK:
            return
        if state in TERMINAL_BAD:
            raise DemoError(f"{label} 任务{state}: {status.get('error')}")
        time.sleep(2)
    raise DemoError(f"{label} 超时（{timeout}s），最后状态 {last}")


def check_domain(base_url: str, domain: str) -> None:
    """域未注册时抽取会静默回落 general，demo 里直接报错更清楚"""
    registered = http_call(base_url, "GET", "/api/ontology/domains").get("domains", [])
    names = [d.get("name") for d in registered]
    if domain not in names:
        raise DemoError(
            f"本体域「{domain}」未注册，已注册：{names}\n"
            "    去掉 --no-pack 让 demo 导入示例包，或改用内置域 workforce/medical/finance/general"
        )
    entry = next(d for d in registered if d.get("name") == domain)
    print(f"    域 {domain}: {entry.get('object_type_count')} ObjectType / "
          f"{entry.get('link_type_count')} LinkType")


def summarize_files(base_url: str, source_id: str, files, timeout: int) -> None:
    for i, file in enumerate(files, 1):
        resp = http_call(base_url, "POST", f"/api/sources/{source_id}/summarize",
                         {"file": file})
        wait_task(base_url, resp["task_id"], f"摘要 {i}/{len(files)} {file}", timeout)


def extract_files(base_url: str, source_id: str, files, domain: str) -> None:
    """同步接口，逐篇抽取；predicate 会按本体词表归一化"""
    total_entities = total_rels = 0
    for i, file in enumerate(files, 1):
        resp = http_call(base_url, "POST", f"/api/sources/{source_id}/extract",
                         {"file": file, "domain": domain}, timeout=1800)
        entities = resp.get("entity_count", len(resp.get("entities", []) or []))
        rels = resp.get("relationship_count", len(resp.get("relationships", []) or []))
        total_entities += entities
        total_rels += rels
        print(f"    抽取 {i}/{len(files)} {file}: 实体 {entities} / 关系 {rels}")
    print(f"    合计: 实体 {total_entities} / 关系 {total_rels}")


def generate_wiki(base_url: str, timeout: int) -> None:
    resp = http_call(base_url, "POST", "/api/wiki/generate", {"scope": "all"})
    wait_task(base_url, resp["task_id"], "Wiki 生成", timeout)
    pages = http_call(base_url, "GET", "/api/wiki/pages").get("pages", [])
    by_kind = {}
    for p in pages:
        by_kind[p.get("kind", "unknown")] = by_kind.get(p.get("kind", "unknown"), 0) + 1
    print(f"    共 {len(pages)} 页: " + ", ".join(f"{k} {v}" for k, v in sorted(by_kind.items())))
    for p in pages[:8]:
        print(f"      - [{p.get('kind')}] {p.get('title')}")


def show_report(base_url: str) -> None:
    report = http_call(base_url, "GET", "/api/ontology/report")
    vocab = report.get("vocabulary", {})
    print(f"    图谱边数: {vocab.get('total_edges')}，兜底「其他」占比: "
          f"{vocab.get('fallback_ratio', 0):.0%}")
    unused = vocab.get("unused_link_types") or []
    if unused:
        print(f"    词表内未出现的谓词: {unused}")
    for finding in report.get("findings", []):
        print(f"    · {finding}")


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenPalantir Wiki + 本体 一键演示")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--domain", default="rd_efficiency",
                        help="抽取使用的本体域包名（内置 workforce/medical/finance/general，"
                             "或示例社区包 rd_efficiency）")
    parser.add_argument("--pack", default=None,
                        help="社区本体包 YAML 路径，默认 examples/ontology/rd_efficiency.yaml")
    parser.add_argument("--no-pack", action="store_true", help="不导入示例本体包")
    parser.add_argument("--no-persist", action="store_true",
                        help="本体包仅本次进程有效，不写入 backend/data/ontology_packs/")
    parser.add_argument("--docs", default=None, help="文档目录，默认 examples/docs")
    parser.add_argument("--timeout", type=int, default=900, help="单个异步任务超时（秒）")
    args = parser.parse_args()

    docs_dir = Path(args.docs) if args.docs else REPO_ROOT / "examples" / "docs"
    docs_dir = docs_dir.resolve()
    if not docs_dir.is_dir():
        raise DemoError(f"文档目录不存在: {docs_dir}")
    pack_path = Path(args.pack).resolve() if args.pack else \
        REPO_ROOT / "examples" / "ontology" / "rd_efficiency.yaml"
    total = 6 + (1 if not args.no_pack else 0)
    index = 0

    index += 1
    step(index, total, "检查后端与模型")
    check_backend(args.base_url)
    check_model(args.base_url)

    formats = fetch_document_formats(args.base_url)
    files = sorted(p.name for p in docs_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in formats)
    if not files:
        raise DemoError(f"{docs_dir} 下没有可解析的文档（后端支持 {'、'.join(formats)}）")

    if not args.no_pack:
        index += 1
        step(index, total, f"导入示例社区本体包 {pack_path.name}")
        import_pack(args.base_url, pack_path, persist=not args.no_persist)

    index += 1
    step(index, total, f"准备文档源（{len(files)} 篇示例文档）")
    source_id = ensure_source(args.base_url, "示例文档（demo）", docs_dir)

    index += 1
    step(index, total, "生成层级摘要树（PageIndex）")
    summarize_files(args.base_url, source_id, files, args.timeout)

    index += 1
    step(index, total, f"按本体域「{args.domain}」抽取实体与关系（写入 Neo4j）")
    check_domain(args.base_url, args.domain)
    extract_files(args.base_url, source_id, files, args.domain)

    index += 1
    step(index, total, "生成 Wiki 页面（文档页 + 跨文档主题页 + 实体页）")
    generate_wiki(args.base_url, args.timeout)

    index += 1
    step(index, total, "读取本体治理报告")
    show_report(args.base_url)

    print("\n完成。前端 http://localhost:5175 的「知识Wiki」与「智能决策」标签页可查看结果；"
          "\n图谱见「图谱可视化」，治理见 GET /api/ontology/report。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DemoError as e:
        print(f"\n演示中断：{e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        sys.exit(130)
