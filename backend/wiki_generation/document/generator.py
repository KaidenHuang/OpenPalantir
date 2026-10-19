"""
Wiki 页面生成 — 文档页（单文档摘要树 → 页面）与跨文档主题页（共享关键词聚类 → 合并改写）

LLM 不可用时降级为确定性拼装（摘要直排），保证页面仍可浏览、可再编辑。
"""
import hashlib
import json
import os
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from summary_generation.document import store as summary_generator
from system.logger import logger

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")

MAX_SECTIONS = 40
MAX_FRAGMENTS = 20
FRAGMENT_SUMMARY_CHARS = 300


def _load_prompt(name: str, **kwargs) -> str:
    with open(os.path.join(PROMPTS_DIR, name), "r", encoding="utf-8") as f:
        text = f.read()
    for key, value in kwargs.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def summary_file_path(datasource: str) -> Optional[str]:
    """DOC://{source_id}/{文件相对路径} → 摘要 JSON 路径；摘要不存在时返回 None"""
    source_id, file_path = summary_generator.parse_datasource(datasource)
    if not source_id or not file_path:
        return None
    path = summary_generator.summary_path(source_id, file_path)
    return path if os.path.isfile(path) else None


def iter_summary_files() -> List[str]:
    """全部文档摘要文件（含源内子目录）"""
    return summary_generator.iter_doc_summaries()


def load_summary(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"[wiki] 摘要文件读取失败 {path}: {e}")
        return None


def file_md5(path: str) -> str:
    try:
        return summary_generator.file_content_hash(path)
    except OSError:
        return ""


def flatten_nodes(structure: List[dict]) -> List[dict]:
    """摘要树拍平（DFS），保留有 summary 的节点"""
    out: List[dict] = []

    def walk(nodes, depth=0):
        for node in nodes or []:
            if node.get("summary") or node.get("text"):
                out.append(node)
            walk(node.get("nodes", []), depth + 1)

    walk(structure)
    return out


def _clean_llm_markdown(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:markdown)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _fallback_document_content(data: dict, sections: List[str]) -> str:
    lines = [f"# {data.get('doc_name', '未命名文档')}", ""]
    desc = data.get("doc_description", "")
    if desc:
        lines += [desc, ""]
    for i, sec in enumerate(sections, 1):
        lines.append(f"{sec} [{i}]")
    return "\n".join(lines)


def generate_document_page(datasource: str) -> Optional[Dict]:
    """单文档 → Wiki 页。返回 {title, content, refs}；摘要不存在返回 None。"""
    path = summary_file_path(datasource)
    if not path:
        logger.warning(f"[wiki] 未找到摘要文件: {datasource}")
        return None
    data = load_summary(path)
    if not data:
        return None

    nodes = flatten_nodes(data.get("structure", []))[:MAX_SECTIONS]
    if not nodes:
        return None

    sections = [f"[{i}] {n.get('title', '')}: {n.get('summary', '')}"
                for i, n in enumerate(nodes, 1)]
    refs = [{"n": i, "datasource": datasource,
             "node_id": n.get("node_id", ""), "title": n.get("title", "")}
            for i, n in enumerate(nodes, 1)]

    prompt = _load_prompt("prompt_document_page.md",
                          doc_name=data.get("doc_name", ""),
                          doc_description=data.get("doc_description", ""),
                          sections="\n".join(sections))
    content = ""
    try:
        from model_management.model_client import get_model_client
        client = get_model_client()
        if client:
            content = _clean_llm_markdown(client.call_text(prompt, max_tokens=16384))
    except Exception as e:
        logger.warning(f"[wiki] 文档页 LLM 生成失败，降级拼装: {e}")

    if not content:
        content = _fallback_document_content(data, sections)

    title = content.splitlines()[0].lstrip("# ").strip() if content else data.get("doc_name", "")
    return {
        "title": title or data.get("doc_name", "未命名页面"),
        "kind": "document",
        "content": content,
        "refs": refs,
        "datasource": datasource,
        "source_hash": file_md5(path),
    }


def _node_search_text(node: dict) -> str:
    return f"{node.get('title', '')} {node.get('summary', '')}"


def discover_topics(min_docs: int = 2, top_n: int = 3) -> List[Tuple[str, List[dict]]]:
    """
    跨文档主题发现：统计各文档出现的分词，取出现在 >= min_docs 篇文档的高频词。

    返回 [(topic, fragments)]，fragments = [{datasource, node_id, title, summary}]
    """
    from decision_engine.agentic.seed_retriever import _tokenize_question

    files = iter_summary_files()
    if len(files) < min_docs:
        return []

    doc_tokens: Dict[str, set] = {}
    doc_nodes: Dict[str, List[dict]] = {}
    for path in files:
        data = load_summary(path)
        if not data:
            continue
        uuid = path.replace("\\", "/").split("/")[-2]
        ds = f"DOC://{uuid}/{data.get('doc_name', '')}"
        nodes = flatten_nodes(data.get("structure", []))
        doc_nodes[ds] = nodes
        tokens = set()
        base_text = f"{data.get('doc_name', '')} {data.get('doc_description', '')}"
        tokens.update(t for t in _tokenize_question(base_text))
        for node in nodes:
            tokens.update(_tokenize_question(_node_search_text(node)))
        doc_tokens[ds] = tokens

    doc_count: Dict[str, int] = defaultdict(int)
    for tokens in doc_tokens.values():
        for t in tokens:
            doc_count[t] += 1

    total_docs = len(doc_tokens)
    candidates = [t for t, c in doc_count.items()
                  if min_docs <= c <= max(1, int(total_docs * 0.8))]
    ranked = sorted(candidates, key=lambda t: doc_count[t], reverse=True)

    results: List[Tuple[str, List[dict]]] = []
    taken_topics: set = set()
    for topic in ranked:
        if len(results) >= top_n:
            break
        if any(topic in other or other in topic for other in taken_topics):
            continue
        fragments = []
        seen_ds: set = set()
        for ds, nodes in doc_nodes.items():
            if topic not in doc_tokens[ds]:
                continue
            hit = [n for n in nodes if topic in _node_search_text(n)][:3]
            for n in hit:
                if n.get("node_id") and len(fragments) < MAX_FRAGMENTS:
                    fragments.append({
                        "datasource": ds, "node_id": n.get("node_id", ""),
                        "title": n.get("title", ""), "summary": n.get("summary", ""),
                    })
            if hit:
                seen_ds.add(ds)
        if len(seen_ds) < min_docs or not fragments:
            continue
        taken_topics.add(topic)
        results.append((topic, fragments))
    return results


def generate_topic_page(topic: str, fragments: List[dict]) -> Optional[Dict]:
    """跨文档主题 → Wiki 页。返回 {title, content, refs, datasource, source_hash}。"""
    if not fragments:
        return None

    lines = []
    refs = []
    for i, frag in enumerate(fragments, 1):
        summary = (frag.get("summary", "") or "")[:FRAGMENT_SUMMARY_CHARS]
        lines.append(f"[{i}]（{frag.get('datasource', '')} / {frag.get('title', '')}）{summary}")
        refs.append({"n": i, "datasource": frag.get("datasource", ""),
                     "node_id": frag.get("node_id", ""), "title": frag.get("title", "")})

    prompt = _load_prompt("prompt_topic_page.md", topic=topic, fragments="\n".join(lines))
    content = ""
    try:
        from model_management.model_client import get_model_client
        client = get_model_client()
        if client:
            content = _clean_llm_markdown(client.call_text(prompt, max_tokens=16384))
    except Exception as e:
        logger.warning(f"[wiki] 主题页 LLM 生成失败，降级拼装: {e}")

    if not content:
        content = f"# {topic}\n\n" + "\n".join(lines)

    source_hash = hashlib.md5(
        "\n".join(f"{r['datasource']}#{r['node_id']}" for r in refs).encode("utf-8")
    ).hexdigest()
    return {
        "title": topic,
        "kind": "topic",
        "content": content,
        "refs": refs,
        "datasource": "",
        "source_hash": source_hash,
    }
