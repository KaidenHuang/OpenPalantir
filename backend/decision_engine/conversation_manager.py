import json
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from decision_engine.contracts import (
    AnalyzedQuery, ConversationSession, ConversationTurn, DecisionAnswer,
    EvidenceCitation, EvidenceItem,
)

CONVERSATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "conversations")


class _ConversationManager:
    def __init__(self):
        os.makedirs(CONVERSATIONS_DIR, exist_ok=True)
        self._cache: Dict[str, ConversationSession] = {}

    def _path(self, session_id: str) -> str:
        return os.path.join(CONVERSATIONS_DIR, f"{session_id}.json")

    def _load(self, session_id: str) -> Optional[ConversationSession]:
        path = self._path(session_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return ConversationSession(**json.load(f))
        except Exception:
            return None

    def _save(self, session: ConversationSession):
        path = self._path(session.session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session.model_dump(), f, ensure_ascii=False, indent=2)

    def get_or_create(self, session_id: Optional[str] = None, domain: str = "general") -> str:
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
                 evidence_citations: Optional[List[EvidenceCitation]] = None) -> str:
        session = self._cache.get(session_id) or self._load(session_id)
        if not session:
            session_id = self.get_or_create(session_id)
            session = self._cache[session_id]
        turn_id = f"turn_{len(session.turns) + 1}"
        session.turns.append(ConversationTurn(
            turn_id=turn_id, question=question,
            analyzed_query=analyzed_query, answer=answer,
            evidence=evidence or [],
            evidence_citations=evidence_citations or [],
            timestamp=datetime.now().isoformat(),
        ))
        session.updated_at = datetime.now().isoformat()
        self._save(session)
        return turn_id

    def get_history(self, session_id: str) -> List[Dict]:
        session = self._cache.get(session_id) or self._load(session_id)
        if not session:
            return []
        self._cache[session_id] = session
        return [
            {"turn_id": t.turn_id, "question": t.question,
             "summary": t.answer.summary, "timestamp": t.timestamp}
            for t in session.turns[-5:]
        ]

    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        session = self._cache.get(session_id) or self._load(session_id)
        if session:
            self._cache[session_id] = session
        return session


conv_manager = _ConversationManager()
