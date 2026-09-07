"""
统一 JSON 提取与修复工具

合并 model_client.py、agentic/engine.py、pageindex/utils.py 三处的 JSON 处理逻辑，
提供单一的 extract_json() 入口。

处理链：
1. 空值/BOM 检查
2. 尝试直接 json.loads
3. 剥离 markdown 代码围栏
4. 常见文本替换（None→null、尾部逗号 ,] / ,}）
5. 实体/关系格式精准修复
6. 通用括号闭合 + 从后向前截断
"""

import json
import re
from typing import Any, List, Optional

from system.logger import logger


# ── 内部辅助函数 ─────────────────────────────────────────────────────────────

def _iter_json_aware(text: str):
    """遍历 JSON 字符串，产出 (index, char, in_str)，正确处理转义和字符串边界。

    in_str 为处理完当前字符后的字符串状态（True=在字符串内部）。
    """
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            yield i, ch, in_str
            continue
        if ch == '\\' and in_str:
            escape = True
            yield i, ch, in_str
            continue
        if ch == '"':
            in_str = not in_str
        yield i, ch, in_str


def _extract_json_body(text: str) -> Optional[str]:
    """从文本中提取 JSON 体：移除 markdown 代码围栏等前缀，定位到第一个 { 或 [。"""
    cleaned = text.strip()

    if cleaned.startswith('```'):
        first_nl = cleaned.find('\n')
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1:]
        else:
            cleaned = cleaned[3:]
        cleaned = cleaned.strip()

    if cleaned.endswith('```'):
        cleaned = cleaned[:-3].strip()

    first_brace = cleaned.find('{')
    first_bracket = cleaned.find('[')
    positions = [p for p in (first_brace, first_bracket) if p != -1]
    if not positions:
        return None
    return cleaned[min(positions):]


def _close_brackets(text: str) -> str:
    """在 text 末尾补全缺失的闭合括号（JSON-aware，跳过字符串内部）。"""
    stack: List[str] = []
    for _, ch, in_str in _iter_json_aware(text):
        if in_str:
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch == '}':
            if stack and stack[-1] == '{':
                stack.pop()
        elif ch == ']':
            if stack and stack[-1] == '[':
                stack.pop()

    result = text.rstrip(', \t\n\r')
    for ch in reversed(stack):
        result += '}' if ch == '{' else ']'
    return result


def _extract_array_objects(text: str, array_start: int) -> List[str]:
    """从 JSON 数组起始位置提取所有完整的扁平对象。"""
    objects: List[str] = []
    if array_start >= len(text) or text[array_start] != '[':
        return objects

    i = array_start + 1
    while i < len(text):
        while i < len(text) and (text[i].isspace() or text[i] == ','):
            i += 1
        if i >= len(text) or text[i] == ']':
            break
        if text[i] != '{':
            i += 1
            continue

        depth = 0
        for pos, ch, in_str in _iter_json_aware(text[i:]):
            actual_pos = i + pos
            if in_str:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    objects.append(text[i:actual_pos + 1])
                    i = actual_pos + 1
                    break
        else:
            break

    return objects


def _repair_entity_relationship(text: str) -> Optional[str]:
    """针对实体/关系 JSON 格式的修复：提取完整对象后重建 JSON。"""
    entities_match = re.search(r'"entities"\s*:\s*(\[)', text)
    rel_match = re.search(r'"relationships"\s*:\s*(\[)', text)

    entities_objects: List[str] = []
    rel_objects: List[str] = []

    if entities_match:
        entities_objects = _extract_array_objects(text, entities_match.start(1))
    if rel_match:
        rel_objects = _extract_array_objects(text, rel_match.start(1))

    result = '{"entities": [' + ','.join(entities_objects) + '], "relationships": [' + ','.join(rel_objects) + ']}'

    try:
        json.loads(result)
        return result
    except json.JSONDecodeError:
        return None


def _repair_by_closing(text: str) -> Optional[str]:
    """通用修复：补全缺失括号，必要时从后向前截断不完整内容。"""
    result = _close_brackets(text.rstrip(', \t\n\r'))
    try:
        json.loads(result)
        return result
    except json.JSONDecodeError:
        pass

    n = len(text)
    in_str_at = [False] * (n + 1)
    for pos, _, in_str in _iter_json_aware(text):
        in_str_at[pos + 1] = in_str

    for end in range(n, 0, -1):
        if in_str_at[end]:
            continue
        candidate = text[:end].rstrip(', \t\n\r')
        if not candidate:
            continue
        result = _close_brackets(candidate)
        try:
            json.loads(result)
            return result
        except json.JSONDecodeError:
            continue

    return None


def _apply_text_fixes(text: str) -> str:
    """应用常见的文本修复（来自 pageindex 和 engine 的经验策略）。"""
    # Python None → JSON null
    text = text.replace('None', 'null')
    # 尾部逗号：,] → ]  ,} → }
    text = text.replace(',]', ']').replace(',}', '}')
    return text


# ── 公共 API ─────────────────────────────────────────────────────────────────

def fix_json(json_str: str) -> Optional[str]:
    """修复 JSON 尾部被截断导致的不完整问题。

    优先尝试针对实体/关系 JSON 格式的精准修复，失败后回退到通用括号闭合修复。
    """
    if not json_str or not json_str.strip():
        return None

    cleaned = json_str.strip()

    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    body = _extract_json_body(cleaned)
    if not body:
        return None

    result = _repair_entity_relationship(body)
    if result:
        return result

    result = _repair_by_closing(body)
    if result:
        return result

    return None


def extract_json(raw: str) -> Any:
    """统一 JSON 提取入口。

    处理链：
    1. 空值/BOM 检查
    2. 尝试直接 json.loads
    3. 剥离 markdown 代码围栏 + 文本修复（None→null、尾部逗号）
    4. fix_json（实体/关系修复 → 通用括号闭合）
    5. 兜底返回 None

    Returns:
        解析后的 Python 对象（dict/list），失败返回 None。
    """
    if not raw or not raw.strip():
        return None

    # 1. 去 BOM + 首尾空白
    cleaned = raw.strip().lstrip('﻿')

    # 2. 直接尝试
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 3. 剥离 markdown 代码围栏 + 文本修复
    body = _extract_json_body(cleaned)
    if body:
        body = _apply_text_fixes(body)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            pass

        # 4. fix_json 修复链
        fixed = fix_json(body)
        if fixed:
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

    # 5. 兜底
    logger.warning(f"[extract_json] 所有修复策略均失败，原始长度: {len(raw)}")
    return None
