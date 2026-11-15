"""混合检索：BM25 关键词通道 + 向量语义通道，加权融合。

不依赖 numpy / faiss / chroma，全部纯 Python 实现。
以本项目的知识库规模（千级 chunk）而言，单次检索耗时为毫秒级。
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

from ..config import settings
from ..llm import cosine, llm, tokenize
from ..models import KnowledgeChunk, KnowledgeDoc

#: BM25 软化系数。bm25/(bm25+K)，K 越大分数上升越慢。
BM25_SOFT_K = 8.0

_jieba = None
_jieba_lock = threading.Lock()
_jieba_tried = False


def _get_jieba():
    global _jieba, _jieba_tried
    if _jieba_tried:
        return _jieba
    with _jieba_lock:
        if not _jieba_tried:
            try:
                import jieba

                jieba.setLogLevel(20)
                _jieba = jieba
            except Exception:
                _jieba = None
            _jieba_tried = True
    return _jieba


def cut(text: str) -> list[str]:
    jb = _get_jieba()
    if jb is not None:
        return [t for t in jb.lcut(text, cut_all=False) if t.strip() and t not in {"的", "了", "和", "与", "及"}]
    return tokenize(text)


@dataclass
class Chunk:
    id: int
    doc_id: int
    seq: int
    content: str
    heading: str
    page: int | None
    vector: list[float]
    tokens: list[str]
    doc_title: str
    doc_filename: str
    category: str
    year: int | None


@dataclass
class Hit:
    chunk: Chunk
    score: float
    bm25: float
    vector: float
    matched: list[str] = field(default_factory=list)

    def citation(self) -> dict:
        snippet = self.chunk.content.strip()
        if len(snippet) > 260:
            snippet = snippet[:260] + "…"
        return {
            "doc_id": self.chunk.doc_id,
            "chunk_id": self.chunk.id,
            "title": self.chunk.doc_title,
            "filename": self.chunk.doc_filename,
            "category": self.chunk.category,
            "year": self.chunk.year,
            "heading": self.chunk.heading,
            "page": self.chunk.page,
            "seq": self.chunk.seq,
            "snippet": snippet,
            "score": round(self.score, 4),
        }


class RetrievalIndex:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self.df: dict[str, int] = {}
        self.avg_len: float = 0.0
        self.version: int = 0

    # ---------------------------------------------------------- 构建
    def build(self, db) -> "RetrievalIndex":  # noqa: ANN001
        rows = (
            db.query(KnowledgeChunk, KnowledgeDoc)
            .join(KnowledgeDoc, KnowledgeChunk.doc_id == KnowledgeDoc.id)
            .filter(KnowledgeDoc.status == "已入库")
            .all()
        )
        chunks: list[Chunk] = []
        df: dict[str, int] = {}
        total_len = 0

        for chunk, doc in rows:
            content = chunk.content or ""
            vec = chunk.vector
            if not isinstance(vec, list) or not vec:
                vec = llm.embed([content])[0]
            if chunk.tokens:
                toks = chunk.tokens.split()
            else:
                toks = cut(content)
            uniq = set(toks)
            for t in uniq:
                df[t] = df.get(t, 0) + 1
            total_len += len(toks)
            chunks.append(
                Chunk(
                    id=chunk.id,
                    doc_id=doc.id,
                    seq=chunk.seq,
                    content=content,
                    heading=chunk.heading or "",
                    page=chunk.page,
                    vector=vec,
                    tokens=toks,
                    doc_title=doc.title,
                    doc_filename=doc.filename,
                    category=doc.category,
                    year=doc.year,
                )
            )

        self.chunks = chunks
        self.df = df
        self.avg_len = (total_len / len(chunks)) if chunks else 0.0
        self.version += 1
        return self

    @property
    def size(self) -> int:
        return len(self.chunks)

    # ---------------------------------------------------------- 检索
    def search(
        self,
        query: str,
        top_k: int | None = None,
        category: str | None = None,
        year: int | None = None,
    ) -> list[Hit]:
        top_k = top_k or settings.RETRIEVE_TOP_K
        if not self.chunks or not query.strip():
            return []

        q_tokens = cut(query)
        if not q_tokens:
            return []
        q_vec = llm.embed([query])[0]
        n = len(self.chunks)
        k1, b = 1.5, 0.75

        raw: list[tuple[Chunk, float, float, list[str]]] = []
        for ch in self.chunks:
            if category and ch.category != category:
                continue
            if year and ch.year and ch.year != year:
                continue

            bm25 = 0.0
            matched: list[str] = []
            tf: dict[str, int] = {}
            for t in ch.tokens:
                tf[t] = tf.get(t, 0) + 1
            dl = len(ch.tokens) or 1
            for t in set(q_tokens):
                f = tf.get(t)
                if not f:
                    continue
                df_t = self.df.get(t, 0)
                idf = math.log(1 + (n - df_t + 0.5) / (df_t + 0.5))
                denom = f + k1 * (1 - b + b * dl / (self.avg_len or 1))
                bm25 += idf * f * (k1 + 1) / denom
                matched.append(t)

            vec_score = max(0.0, cosine(q_vec, ch.vector))
            raw.append((ch, bm25, vec_score, matched))

        if not raw:
            return []

        # BM25 用软化函数映射到 0-1（绝对值，不做相对归一化）。
        # 相对归一化会让 top1 的 bm25 分量恒为 1.0，导致任何问题都能拿到 0.5 分以上，
        # 阈值判断失效——不相关的问题也会被硬答。
        w_v = settings.RETRIEVE_VECTOR_WEIGHT
        w_b = settings.RETRIEVE_BM25_WEIGHT

        hits: list[Hit] = []
        for ch, bm25, vec_score, matched in raw:
            bm25_soft = bm25 / (bm25 + BM25_SOFT_K) if bm25 > 0 else 0.0
            score = w_b * bm25_soft + w_v * vec_score
            hits.append(
                Hit(
                    chunk=ch,
                    score=score,
                    bm25=bm25_soft,
                    vector=vec_score,
                    matched=sorted(set(matched), key=len, reverse=True)[:8],
                )
            )

        hits.sort(key=lambda h: h.score, reverse=True)
        # 去重：同一文档相邻块只留最优的一条，避免引用重复
        out: list[Hit] = []
        seen: set[tuple[int, int]] = set()
        for h in hits:
            key = (h.chunk.doc_id, h.chunk.seq // 2)
            if key in seen:
                continue
            seen.add(key)
            out.append(h)
            if len(out) >= top_k:
                break
        return out

    def search_multi(self, queries: list[str], top_k: int = 6) -> list[Hit]:
        """多查询召回后按最高分合并，用于"赛事推荐""备赛要求"等多角度检索。"""
        best: dict[int, Hit] = {}
        for q in queries:
            if not q.strip():
                continue
            for h in self.search(q, top_k=top_k * 2):
                cur = best.get(h.chunk.id)
                if cur is None or h.score > cur.score:
                    best[h.chunk.id] = h
        hits = sorted(best.values(), key=lambda h: h.score, reverse=True)
        return hits[:top_k]


_cache: dict[str, object] = {"index": None, "stamp": 0.0}
_cache_lock = threading.Lock()


def get_index(db, force: bool = False) -> RetrievalIndex:  # noqa: ANN001
    """带缓存地获取索引；知识库变更后调用 invalidate() 失效。"""
    with _cache_lock:
        idx = _cache.get("index")
        if idx is None or force:
            idx = RetrievalIndex().build(db)
            _cache["index"] = idx
        return idx  # type: ignore[return-value]


def invalidate() -> None:
    with _cache_lock:
        _cache["index"] = None
