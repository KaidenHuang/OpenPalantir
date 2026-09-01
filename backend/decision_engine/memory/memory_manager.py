"""
记忆管理器 — 统一管理短期记忆（SQLite）和长期记忆（MEMORY.md）
"""
import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from config.database import SessionLocal
from models.memory import ShortTermMemory
from system.logger import logger

# 长期记忆文件路径
_MEMORY_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "conversations")
_MEMORY_FILE = os.path.join(_MEMORY_DIR, "MEMORY.md")

# 短期记忆 TTL（天）
SHORT_TERM_TTL_DAYS = 7
# 过期前提升检查阈值（天）
PROMOTION_CHECK_DAYS = 6
# 长期记忆条数上限
MAX_LONG_TERM_ITEMS = 10
# 长期记忆总字数上限
MAX_LONG_TERM_CHARS = 300


class MemoryManager:
    """记忆管理器 — 短期记忆（SQLite）+ 长期记忆（MEMORY.md）"""

    # ─── 短期记忆 ────────────────────────────────────────

    def add_short_term(self, content: str, category: str = "fact",
                       importance: float = 0.5, session_id: str = "",
                       domain: str = "general") -> Optional[str]:
        """添加一条短期记忆"""
        try:
            db = SessionLocal()
            now = datetime.now()
            entry = ShortTermMemory(
                id=uuid.uuid4().hex[:12],
                content=content,
                category=category,
                importance=importance,
                session_id=session_id,
                domain=domain,
                created_at=now,
                expires_at=now + timedelta(days=SHORT_TERM_TTL_DAYS),
            )
            db.add(entry)
            db.commit()
            logger.debug(f"[memory] 短期记忆已存储: {content[:40]}...")
            return entry.id
        except Exception as e:
            logger.error(f"[memory] 短期记忆存储失败: {e}")
            return None
        finally:
            db.close()

    def add_short_term_batch(self, entries: list) -> int:
        """批量添加短期记忆，返回成功条数"""
        count = 0
        for entry in entries:
            if self.add_short_term(
                content=entry.get("content", ""),
                category=entry.get("category", "fact"),
                importance=entry.get("importance", 0.5),
                session_id=entry.get("session_id", ""),
                domain=entry.get("domain", "general"),
            ):
                count += 1
        return count

    def retrieve_short_term(self, query: str, domain: str = "general",
                            limit: int = 5) -> List[dict]:
        """
        检索相关短期记忆
        策略：关键词匹配 + 域过滤 + 排除过期 + 重要性*时间衰减排序
        """
        try:
            db = SessionLocal()
            now = datetime.now()

            # 提取查询关键词
            keywords = self._extract_keywords(query)

            # 先按时间取最近的一批记录，避免全量加载
            rows = db.query(ShortTermMemory).filter(
                ShortTermMemory.expires_at > now,
                ShortTermMemory.domain == domain,
            ).order_by(
                ShortTermMemory.created_at.desc()
            ).limit(200).all()

            # 计算相关性分数并排序
            scored = []
            for row in rows:
                score = self._relevance_score(row.content, keywords)
                if score <= 0:
                    continue
                # 时间衰减
                days = (now - row.created_at).total_seconds() / 86400
                recency = 0.9 ** days
                final_score = row.importance * recency * score
                scored.append((row, final_score))

            scored.sort(key=lambda x: x[1], reverse=True)

            # 检查是否需要提升检查
            for row, _ in scored:
                days_old = (now - row.created_at).total_seconds() / 86400
                if days_old >= PROMOTION_CHECK_DAYS and row.importance >= 0.7:
                    self._check_promotion(row)

            result = [r[0].to_dict() for r in scored[:limit]]
            if result:
                logger.info(f"[memory] 检索到 {len(result)} 条短期记忆")
            return result
        except Exception as e:
            logger.error(f"[memory] 短期记忆检索失败: {e}")
            return []
        finally:
            db.close()

    def clean_expired(self) -> int:
        """清理过期的短期记忆，返回清理条数"""
        try:
            db = SessionLocal()
            now = datetime.now()
            count = db.query(ShortTermMemory).filter(
                ShortTermMemory.expires_at <= now
            ).delete()
            db.commit()
            if count > 0:
                logger.info(f"[memory] 清理了 {count} 条过期短期记忆")
            return count
        except Exception as e:
            logger.error(f"[memory] 清理过期记忆失败: {e}")
            return 0
        finally:
            db.close()

    @staticmethod
    def _extract_keywords(query: str) -> List[str]:
        """从查询中提取关键词（简单分词）"""
        # 按常见分隔符拆分，取长度≥2的词
        tokens = re.split(r'[，。！？、\s,!.?]+', query)
        return [t for t in tokens if len(t) >= 2]

    @staticmethod
    def _relevance_score(content: str, keywords: List[str]) -> float:
        """计算内容与关键词的相关性分数"""
        if not keywords:
            return 0.1  # 无关键词时给一个基础分
        hits = sum(1 for kw in keywords if kw in content)
        return hits / len(keywords)

    def _check_promotion(self, row: ShortTermMemory):
        """检查是否需要提升为长期记忆（第 6 天，importance >= 0.7）"""
        logger.info(f"[memory] 短期记忆即将过期，检查是否提升: {row.content[:40]}...")
        # 注意：提升检查需要 LLM 调用，在 MemoryExtractor 中实现
        # 这里只记录日志，实际提升由 MemoryExtractor._maybe_promote() 处理

    # ─── 长期记忆（MEMORY.md）──────────────────────────────

    def read_long_term_memories(self) -> Optional[dict]:
        """读取 MEMORY.md，返回 {preferences: [...], decisions: [...]}"""
        try:
            if not os.path.isfile(_MEMORY_FILE):
                self._ensure_memory_file()
                return None

            with open(_MEMORY_FILE, "r", encoding="utf-8") as f:
                content = f.read()

            return self._parse_memory_md(content)
        except Exception as e:
            logger.error(f"[memory] 读取长期记忆失败: {e}")
            return None

    def merge_long_term_memories(self, new_prefs: List[str],
                                 new_decisions: List[str]) -> bool:
        """合并新的长期记忆候选，自动去重和超限提炼"""
        existing = self.read_long_term_memories() or {"preferences": [], "decisions": []}

        # 去重合并
        all_prefs = existing["preferences"] + [
            p for p in new_prefs
            if not any(self._is_similar(p, ep) for ep in existing["preferences"])
        ]
        all_decs = existing["decisions"] + [
            d for d in new_decisions
            if not any(self._is_similar(d, ed) for ed in existing["decisions"])
        ]

        return self._write_long_term(all_prefs, all_decs)

    def write_long_term_memories(self, preferences: List[str],
                                 decisions: List[str]) -> bool:
        """写入长期记忆（公开接口，用于提炼后的记忆覆写）"""
        return self._write_long_term(preferences, decisions)

    def get_long_term_hash(self) -> str:
        """获取 MEMORY.md 内容的 MD5 hash，用于多轮去重"""
        try:
            if not os.path.isfile(_MEMORY_FILE):
                return ""
            with open(_MEMORY_FILE, "r", encoding="utf-8") as f:
                return hashlib.md5(f.read().encode()).hexdigest()
        except Exception:
            return ""

    def _write_long_term(self, preferences: List[str],
                         decisions: List[str]) -> bool:
        """写入 MEMORY.md，自动检查限值，超限则调用 LLM 提炼"""
        try:
            # 检查是否超限
            total = len(preferences) + len(decisions)
            total_chars = sum(len(s) for s in preferences + decisions)

            if total > MAX_LONG_TERM_ITEMS or total_chars > MAX_LONG_TERM_CHARS:
                logger.info(
                    f"[memory] 长期记忆超限 (条目={total}/{MAX_LONG_TERM_ITEMS}, "
                    f"字数={total_chars}/{MAX_LONG_TERM_CHARS})，需要提炼"
                )
                # 超限提炼由 MemoryExtractor._condense_long_term() 处理
                # 这里先按简单策略截断：保留最新的
                preferences = preferences[-MAX_LONG_TERM_ITEMS // 2:]
                decisions = decisions[-MAX_LONG_TERM_ITEMS // 2:]

            now = datetime.now().isoformat()
            domain = "workforce"

            # 构建 MEMORY.md 内容
            lines = [
                "---",
                f"updated: {now}",
                f"domain: {domain}",
                "---",
                "",
                "# 长期记忆",
                "",
            ]

            if preferences:
                lines.append("## 用户偏好")
                for p in preferences:
                    lines.append(f"- {p}")
                lines.append("")

            if decisions:
                lines.append("## 重要决策")
                for d in decisions:
                    lines.append(f"- {d}")
                lines.append("")

            os.makedirs(_MEMORY_DIR, exist_ok=True)
            with open(_MEMORY_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            logger.info(
                f"[memory] 长期记忆已更新: 偏好={len(preferences)}条, "
                f"决策={len(decisions)}条"
            )
            return True
        except Exception as e:
            logger.error(f"[memory] 写入长期记忆失败: {e}")
            return False

    def _ensure_memory_file(self):
        """创建空的 MEMORY.md 模板"""
        os.makedirs(_MEMORY_DIR, exist_ok=True)
        now = datetime.now().isoformat()
        template = f"""---
updated: {now}
domain: workforce
---

# 长期记忆

## 用户偏好

## 重要决策
"""
        with open(_MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write(template)
        logger.info("[memory] 创建 MEMORY.md 模板")

    @staticmethod
    def _parse_memory_md(content: str) -> dict:
        """解析 MEMORY.md 内容"""
        preferences = []
        decisions = []
        current_section = None

        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("## 用户偏好"):
                current_section = "preferences"
            elif line.startswith("## 重要决策"):
                current_section = "decisions"
            elif line.startswith("- ") and current_section:
                item = line[2:].strip()
                if item:
                    if current_section == "preferences":
                        preferences.append(item)
                    elif current_section == "decisions":
                        decisions.append(item)
            elif line.startswith("## ") or line.startswith("# "):
                current_section = None

        return {"preferences": preferences, "decisions": decisions}

    @staticmethod
    def _is_similar(a: str, b: str) -> bool:
        """简单相似度判断（基于共同字符比例）"""
        if a == b:
            return True
        set_a = set(a)
        set_b = set(b)
        if not set_a or not set_b:
            return False
        intersection = set_a & set_b
        return len(intersection) / min(len(set_a), len(set_b)) > 0.6


# 全局单例
memory_manager = MemoryManager()