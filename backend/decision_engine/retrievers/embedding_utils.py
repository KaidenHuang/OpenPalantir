"""
embedding 工具 — 向量获取（带 SQLite 缓存）与混合重排

embedding 不可用（模型未部署/调用失败）时全部优雅降级为 None，
调用方回退纯关键词逻辑。
"""
import hashlib
import json
import math
from typing import Dict, List, Optional

from system.logger import logger


def _text_hash(model_name: str, text: str) -> str:
    return hashlib.md5(f"{model_name}\n{text}".encode("utf-8")).hexdigest()


def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """批量取向量，优先命中缓存。embedding 不可用时返回 None。"""
    if not texts:
        return []
    from config.database import SessionLocal
    from model_management.model_client import get_model_client
    from models.embedding import EmbeddingCache

    client = get_model_client()
    if client is None:
        return None
    model_name = client.config.embedding_model
    if not model_name:
        return None

    db = SessionLocal()
    try:
        vectors: Dict[str, List[float]] = {}
        for text in texts:
            h = _text_hash(model_name, text)
            if h in vectors:
                continue
            cached = db.query(EmbeddingCache).filter_by(text_hash=h).first()
            if cached:
                try:
                    vectors[h] = json.loads(cached.vector)
                except json.JSONDecodeError:
                    continue

        missing = [(t, _text_hash(model_name, t)) for t in texts
                   if _text_hash(model_name, t) not in vectors]
        if missing:
            fresh = client.embed([t for t, _ in missing])
            if fresh is None:
                return None
            for (text, h), vec in zip(missing, fresh):
                if not vec:
                    continue
                vectors[h] = vec
                db.merge(EmbeddingCache(text_hash=h, model_name=model_name,
                                        vector=json.dumps(vec)))
            db.commit()

        return [vectors.get(_text_hash(model_name, t), []) for t in texts]
    except Exception as e:
        logger.warning(f"[embedding] embed_texts 失败: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def semantic_scores(query: str, texts: List[str]) -> Optional[List[float]]:
    """query 对一组文本的语义相似度（clamp 到 [0,1]）。不可用返回 None。"""
    if not query or not texts:
        return None
    vectors = embed_texts([query] + list(texts))
    if not vectors or len(vectors) != len(texts) + 1:
        return None
    q_vec = vectors[0]
    return [max(0.0, cosine_similarity(q_vec, v)) for v in vectors[1:]]


def hybrid_rank(query: str, items: List, text_of, score_of,
                keyword_weight: float = 0.5, top_k: Optional[int] = None) -> List:
    """
    关键词分 + 语义分混合重排。embedding 不可用时按原分排序返回。

    Args:
        items: 候选对象列表
        text_of: item -> 用于语义打分的文本
        score_of: item -> 关键词相关性分（0~1）
    """
    if not items:
        return []
    texts = [text_of(i) for i in items]
    scores = semantic_scores(query, texts)
    if scores is None:
        ranked = sorted(items, key=score_of, reverse=True)
    else:
        blended = {}
        for idx, item in enumerate(items):
            blended[id(item)] = (1 - keyword_weight) * score_of(item) + keyword_weight * scores[idx]
        ranked = sorted(items, key=lambda i: blended[id(i)], reverse=True)
    return ranked[:top_k] if top_k else ranked
