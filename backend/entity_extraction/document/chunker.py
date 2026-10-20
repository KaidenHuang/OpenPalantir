"""④ 实体抽取（文档侧）—— 摘要树 → 分批正文

摘要 JSON 的 structure 是章节树：叶子与父节点都带 summary + 自身正文 text，父节点另带 nodes。
这里把它摊平成「顺序的正文段」，再按 token/字符预算合并成批次：
批次是 LLM 调用的单位，既不能太大（超上下文）也不能太小（浪费调用）。
"""
import re
from typing import Iterator, Tuple

from system.logger import logger


def iter_segments(node, max_chunk: int = 20000) -> Iterator[Tuple[str, str]]:
    """从摘要树节点逐个 yield (title, text) 元组，超长段按句子边界切分"""
    if isinstance(node, dict):
        title = node.get("title", "")
        if "text" in node and node["text"]:
            seg = node["text"].strip()
            if seg:
                if len(seg) <= max_chunk:
                    yield (title, seg)
                else:
                    for i, part in enumerate(split_text(seg, max_chunk)):
                        yield (f"{title}(切{i+1})", part)
        for key, val in node.items():
            if isinstance(val, (dict, list)):
                yield from iter_segments(val, max_chunk)
    elif isinstance(node, list):
        for item in node:
            yield from iter_segments(item, max_chunk)


def split_text(text: str, max_chunk: int) -> Iterator[str]:
    """按句子边界切分长文本，每块不超过 max_chunk 字符"""
    sentences = re.split(r'(?<=[。！？\n])', text)
    current = ""
    for s in sentences:
        if not s.strip():
            continue
        if len(current) + len(s) <= max_chunk:
            current += s
        else:
            if current:
                yield current
            if len(s) > max_chunk:
                for i in range(0, len(s), max_chunk):
                    yield s[i:i + max_chunk]
            else:
                current = s
    if current:
        yield current


def merge_segments_iter(segments, max_chunk: int = 20000, min_size: int = 1000):
    """将不足 min_size 的段合并为大块并逐个 yield，合并后总长度不超过 max_chunk"""
    buffer = ""
    buffer_titles = []
    chunk_index = 0

    for title, seg in segments:
        if len(seg) >= min_size:
            if buffer:
                if len(buffer) + len(seg) <= max_chunk:
                    chunk_index += 1
                    titles = buffer_titles + [title]
                    logger.info(f"合并块 {chunk_index}: {' + '.join(titles)} (总长: {len(buffer + seg)})")
                    yield buffer + seg
                else:
                    chunk_index += 1
                    if buffer_titles:
                        logger.info(f"合并块 {chunk_index}: {' + '.join(buffer_titles)} (总长: {len(buffer)})")
                    else:
                        logger.info(f"合并块 {chunk_index}: (总长: {len(buffer)})")
                    yield buffer
                    chunk_index += 1
                    logger.info(f"合并块 {chunk_index}: {title} (总长: {len(seg)})")
                    yield seg
                buffer = ""
                buffer_titles = []
            else:
                chunk_index += 1
                logger.info(f"合并块 {chunk_index}: {title} (总长: {len(seg)})")
                yield seg
        else:
            if len(buffer) + len(seg) > max_chunk:
                chunk_index += 1
                if buffer_titles:
                    logger.info(f"合并块 {chunk_index}: {' + '.join(buffer_titles)} (总长: {len(buffer)})")
                else:
                    logger.info(f"合并块 {chunk_index}: (总长: {len(buffer)})")
                yield buffer
                buffer = seg
                buffer_titles = [title] if title else []
            else:
                buffer += seg
                if title and (not buffer_titles or buffer_titles[-1] != title):
                    buffer_titles.append(title)
    if buffer:
        chunk_index += 1
        if buffer_titles:
            logger.info(f"合并块 {chunk_index}: {' + '.join(buffer_titles)} (总长: {len(buffer)})")
        else:
            logger.info(f"合并块 {chunk_index}: (总长: {len(buffer)})")
        yield buffer


def dedupe_extraction(all_entities, all_relationships):
    """跨批次去重：实体按「名称+类型」，关系按「主体+谓词+客体」

    实体重复出现时合并属性字典（先到先得，后到补空缺）并取最大出现次数，
    避免「先抽到的块没写属性、后抽到的块写了却被丢掉」。
    """
    seen = {}
    entities = []
    for e in all_entities:
        key = f"{e.get('n', '')}_{e.get('t', '')}"
        first = seen.get(key)
        if first is None:
            merged = dict(e)
            merged["a"] = dict(e.get("a") or {})
            seen[key] = merged
            entities.append(merged)
            continue
        for k, v in (e.get("a") or {}).items():
            if v not in (None, "", []) and not first["a"].get(k):
                first["a"][k] = v
        try:
            first["c"] = max(int(first.get("c") or 1), int(e.get("c") or 1))
        except (TypeError, ValueError):
            pass
        if not first.get("d") and e.get("d"):
            first["d"] = e["d"]

    seen_rel = set()
    relationships = []
    for r in all_relationships:
        key = f"{r.get('s', '')}_{r.get('p', '')}_{r.get('o', '')}"
        if key not in seen_rel:
            seen_rel.add(key)
            relationships.append(r)
    return entities, relationships
