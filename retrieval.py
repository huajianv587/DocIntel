from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from .models import Chunk, RetrievalHit


TOKEN_PATTERN = re.compile(r"[\w]+", re.UNICODE)
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "before", "by", "can", "do", "does", "for",
    "from", "how", "i", "in", "is", "it", "make", "of", "on", "or", "the", "this", "to", "was",
    "what", "when", "where", "which", "why", "with", "were", "you", "your",
}


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text or "") if token.lower() not in STOP_WORDS]


@dataclass(frozen=True)
class _IndexedChunk:
    chunk: Chunk
    counts: Counter[str]
    length: int
    norm: float


class HybridRetriever:
    """Small dependency-free BM25 + TF-IDF retriever with RRF fusion."""

    def __init__(self, chunks: Iterable[Chunk]):
        self.chunks = list(chunks)
        document_frequency: Counter[str] = Counter()
        staged: list[tuple[Chunk, Counter[str], int]] = []
        for chunk in self.chunks:
            counts = Counter(tokenize(f"{chunk.title}\n{chunk.section}\n{chunk.text}"))
            staged.append((chunk, counts, sum(counts.values())))
            document_frequency.update(counts.keys())
        self.document_count = max(len(staged), 1)
        self.average_length = sum(length for _chunk, _counts, length in staged) / self.document_count
        self.idf = {
            token: math.log(1.0 + (self.document_count - frequency + 0.5) / (frequency + 0.5))
            for token, frequency in document_frequency.items()
        }
        self.index: list[_IndexedChunk] = []
        for chunk, counts, length in staged:
            norm = math.sqrt(
                sum((count * self.idf.get(token, 0.0)) ** 2 for token, count in counts.items())
            )
            self.index.append(_IndexedChunk(chunk, counts, length, norm))

    def _bm25(self, query: Counter[str], item: _IndexedChunk) -> float:
        k1 = 1.5
        b = 0.75
        score = 0.0
        for token in query:
            tf = item.counts.get(token, 0)
            if not tf:
                continue
            idf = self.idf.get(token, 0.0)
            denominator = tf + k1 * (1 - b + b * item.length / max(self.average_length, 1.0))
            score += idf * (tf * (k1 + 1)) / max(denominator, 1e-9)
        return score

    def _tfidf_cosine(self, query: Counter[str], item: _IndexedChunk) -> float:
        query_norm = 0.0
        numerator = 0.0
        for token, count in query.items():
            weight = count * self.idf.get(token, 0.0)
            query_norm += weight * weight
            numerator += weight * (item.counts.get(token, 0) * self.idf.get(token, 0.0))
        if not query_norm or not item.norm:
            return 0.0
        return numerator / math.sqrt(query_norm * item.norm * item.norm)

    @staticmethod
    def _overlap(query: Counter[str], item: _IndexedChunk) -> float:
        if not query:
            return 0.0
        return len(set(query) & set(item.counts)) / len(set(query))

    @staticmethod
    def _filter(
        item: _IndexedChunk,
        *,
        domain: str | None,
        source_type: str | None,
        tenant_id: str | None,
        allowed_source_ids: set[str] | None,
    ) -> bool:
        chunk = item.chunk
        if domain and chunk.domain != domain:
            return False
        if source_type and chunk.source_type != source_type:
            return False
        if allowed_source_ids is not None and chunk.source_id not in allowed_source_ids:
            return False
        if tenant_id and str(chunk.metadata.get("tenant_id", "default")) != tenant_id:
            return False
        return True

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        domain: str | None = None,
        source_type: str | None = None,
        tenant_id: str | None = None,
        allowed_source_ids: set[str] | None = None,
    ) -> list[RetrievalHit]:
        query_counts = Counter(tokenize(query))
        candidates = [
            item for item in self.index
            if self._filter(
                item,
                domain=domain,
                source_type=source_type,
                tenant_id=tenant_id,
                allowed_source_ids=allowed_source_ids,
            )
        ]
        if not candidates or not query_counts:
            return []

        bm25_scores = {item.chunk.chunk_id: self._bm25(query_counts, item) for item in candidates}
        dense_scores = {item.chunk.chunk_id: self._tfidf_cosine(query_counts, item) for item in candidates}
        overlap_scores = {item.chunk.chunk_id: self._overlap(query_counts, item) for item in candidates}
        bm25_rank = {
            item.chunk.chunk_id: rank
            for rank, item in enumerate(
                sorted(candidates, key=lambda item: (bm25_scores[item.chunk.chunk_id], item.chunk.chunk_id), reverse=True),
                1,
            )
        }
        dense_rank = {
            item.chunk.chunk_id: rank
            for rank, item in enumerate(
                sorted(candidates, key=lambda item: (dense_scores[item.chunk.chunk_id], item.chunk.chunk_id), reverse=True),
                1,
            )
        }
        scored: list[tuple[float, _IndexedChunk, str]] = []
        for item in candidates:
            chunk_id = item.chunk.chunk_id
            if not (
                bm25_scores[chunk_id]
                or dense_scores[chunk_id]
                or overlap_scores[chunk_id]
            ):
                # Reciprocal-rank fusion must not turn an unrelated chunk into evidence.
                continue
            score = (
                0.52 * bm25_scores[chunk_id]
                + 0.28 * dense_scores[chunk_id]
                + 0.10 * overlap_scores[chunk_id]
                + 0.10 * (1 / (60 + bm25_rank[chunk_id]) + 1 / (60 + dense_rank[chunk_id]))
            )
            scored.append((score, item, "hybrid_rrf"))
        scored.sort(key=lambda row: (row[0], row[1].chunk.chunk_id), reverse=True)

        # Avoid returning repeated chunks from the same source and page when a parser emits overlaps.
        selected: list[RetrievalHit] = []
        seen_keys: set[tuple[str, int | None, str]] = set()
        for score, item, retriever_name in scored:
            key = (item.chunk.source_id, item.chunk.page, item.chunk.section)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            selected.append(
                RetrievalHit(
                    chunk=item.chunk,
                    score=max(0.0, score),
                    rank=len(selected) + 1,
                    retriever=retriever_name,
                )
            )
            if len(selected) >= max(1, top_k):
                break
        return selected

