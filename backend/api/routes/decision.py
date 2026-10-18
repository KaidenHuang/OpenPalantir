from fastapi import APIRouter, HTTPException

from decision_engine.contracts import DecisionRequest, DecisionResponse
from decision_engine.decision_kernel import decision_kernel
from decision_engine.conversation_manager import conv_manager as _conv_manager
from system.logger import logger

router = APIRouter()


@router.post("/ask", response_model=DecisionResponse)
def ask_decision(request: DecisionRequest):
    """智能决策问答入口。支持会话管理和多轮对话。"""
    try:
        logger.info(
            f"[decision][api] ask domain={request.domain or 'auto'}, "
            f"session_id={request.session_id}, connection_id={request.connection_id}, "
            f"question_length={len(request.question)}"
        )
        response = decision_kernel.run(request)
        logger.info(
            f"[decision][api] response domain={response.domain}, intent={response.intent}, "
            f"session_id={response.session_id}, "
            f"mode={response.decision_mode}, "
            f"confidence={response.confidence:.2f}, "
            f"turns={response.metadata.get('total_turns', '?')}, "
            f"tools={response.metadata.get('total_tool_calls', '?')}, "
            f"time={response.metadata.get('total_time_ms', 0):.0f}ms"
        )
        return response
    except Exception as exc:
        logger.error(f"[decision][api] ask failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/session/{session_id}")
def get_session(session_id: str):
    """获取会话历史，用于页面重载时恢复对话。"""
    session = _conv_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.model_dump()
