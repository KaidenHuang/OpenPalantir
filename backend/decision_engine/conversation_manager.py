import json
import os
import tempfile
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from decision_engine.contracts import (
    AnalyzedQuery, ConversationSession, ConversationTurn, DecisionAnswer,
    EvidenceCitation, EvidenceItem, ToolTrace,
)
from decision_engine.config import get_config
from system.logger import logger

CONVERSATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "conversations")


class _ConversationManager:
    def __init__(self):
        os.makedirs(CONVERSATIONS_DIR, exist_ok=True)
        self._cache: Dict[str, ConversationSession] = {}
        # 会话对象的并发守护：读取、追加、落盘共用（决策流量单进程即可，不做 per-session 粒度）
        self._lock = threading.RLock()

    def _path(self, session_id: str) -> str:
        return os.path.join(CONVERSATIONS_DIR, f"{session_id}.json")

    def _load(self, session_id: str) -> Optional[ConversationSession]:
        path = self._path(session_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                body = f.read()
            return ConversationSession(**json.loads(body))
        except (OSError, json.JSONDecodeError, TypeError) as e:
            # 半截/损坏 JSON 视为不存在：宁可让会话从空开始，也不能把异常吞成 None 后让上层误判为"无历史"
            logger.warning(f"[conversation] 会话文件不可读，按新会话处理 {session_id}: {e}")
            return None

    def _save(self, session: ConversationSession):
        """原子写：临时文件 + os.replace，读者永远看不到半截 JSON"""
        path = self._path(session.session_id)
        fd, tmp = tempfile.mkstemp(prefix="conv_", suffix=".json", dir=CONVERSATIONS_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(session.model_dump(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def get_or_create(self, session_id: Optional[str] = None, domain: str = "general") -> str:
        with self._lock:
            if session_id:
                session = self._cache.get(session_id) or self._load(session_id)
                if session:
                    self._cache[session_id] = session
                    return session_id
            sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
            now = datetime.now().isoformat()
            self._cache[sid] = ConversationSession(
                session_id=sid, domain=domain, created_at=now, updated_at=now,
            )
            self._save(self._cache[sid])
            return sid

    def add_turn(self, session_id: str, question: str,
                 analyzed_query: AnalyzedQuery, answer: DecisionAnswer,
                 evidence: Optional[List[EvidenceItem]] = None,
                 evidence_citations: Optional[List[EvidenceCitation]] = None,
                 tool_trace: Optional[List[ToolTrace]] = None,
                 response_type: str = "normal") -> str:
        with self._lock:
            session = self._cache.get(session_id) or self._load(session_id)
            if not session:
                sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
                now = datetime.now().isoformat()
                session = ConversationSession(
                    session_id=sid, domain="general", created_at=now, updated_at=now,
                )
                session_id = sid
                self._cache[sid] = session
            turn_id = f"turn_{len(session.turns) + 1}"
            session.turns.append(ConversationTurn(
                turn_id=turn_id, question=question,
                analyzed_query=analyzed_query, answer=answer,
                evidence=evidence or [],
                evidence_citations=evidence_citations or [],
                tool_trace=tool_trace or [],
                timestamp=datetime.now().isoformat(),
                response_type=response_type,
            ))
            session.updated_at = datetime.now().isoformat()
            self._save(session)
            return turn_id

    def get_history(self, session_id: str, max_turns: int = None) -> List[Dict]:
        if max_turns is None:
            max_turns = get_config()["conversation"]["max_history_turns"]
        with self._lock:
            session = self._cache.get(session_id) or self._load(session_id)
            if not session:
                return []
            self._cache[session_id] = session
            turns = session.turns if max_turns <= 0 else session.turns[-max_turns:]
            return [
                {"turn_id": t.turn_id, "question": t.question,
                 "summary": t.answer.summary, "timestamp": t.timestamp}
                for t in turns
            ]

    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        with self._lock:
            session = self._cache.get(session_id) or self._load(session_id)
            if session:
                self._cache[session_id] = session
            return session

    def save_session(self, session: ConversationSession):
        """持久化会话（公开接口，供外部更新 long_term_memory_hash 等字段后调用）"""
        with self._lock:
            self._cache[session.session_id] = session
            self._save(session)


conv_manager = _ConversationManager()
