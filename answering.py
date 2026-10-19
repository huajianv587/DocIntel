from __future__ import annotations

import re
import uuid
from time import perf_counter
from typing import Iterable

from .config import DomainConfig
from .models import Citation, QueryResponse, RetrievalHit
from .observability import TraceLogger
from .retrieval import tokenize


ABSTENTION_TEXT = "I cannot answer from the indexed evidence."
INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "system message:",
    "developer message:",
    "assistant message:",
    "jailbreak",
)


def sanitize_evidence(text: str) -> tuple[str, bool]:
    """Keep document text as evidence while neutralising instruction-like lines."""
    removed = False
    safe_lines: list[str] = []
    for line in text.splitlines():
        sentences = re.split(r"(?<=[.!?。！？])\s+", line)
        safe_sentences: list[str] = []
        for sentence in sentences:
            lowered = sentence.lower()
            if any(marker in lowered for marker in INJECTION_MARKERS):
                removed = True
                continue
            safe_sentences.append(sentence)
        if safe_sentences:
            safe_lines.append(" ".join(safe_sentences))
    return "\n".join(safe_lines).strip(), removed


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?。！？])\s+", text) if item.strip()]


def _support_score(query: str, hits: list[RetrievalHit]) -> float:
    if not hits:
        return 0.0
    query_terms = set(tokenize(query))
    evidence_terms = set(tokenize(" ".join(hit.chunk.text for hit in hits[:3])))
    overlap = len(query_terms & evidence_terms) / max(len(query_terms), 1)
    score_signal = min(max(hits[0].score * 3.0, 0.0), 1.0)
    return min(1.0, 0.72 * overlap + 0.28 * score_signal)


def _extractive_answer(query: str, hits: list[RetrievalHit]) -> tuple[str, bool]:
    query_terms = set(tokenize(query))
    safe_sentences: list[str] = []
    injection_removed = False
    for hit in hits[:3]:
        text, removed = sanitize_evidence(hit.chunk.text)
        injection_removed = injection_removed or removed
        accepted_answer = hit.chunk.metadata.get("accepted_answer")
        if accepted_answer:
            accepted_text, accepted_removed = sanitize_evidence(str(accepted_answer))
            injection_removed = injection_removed or accepted_removed
            if accepted_text:
                safe_sentences.append(f"Accepted answer: {accepted_text}")
        sentences = _sentences(text) or [text]
        ranked = sorted(
            sentences,
            key=lambda sentence: len(query_terms & set(tokenize(sentence))),
            reverse=True,
        )
        safe_sentences.extend(ranked[:2])
    answer = " ".join(sentence for sentence in safe_sentences if sentence).strip()
    return answer[:1000], injection_removed


class AnswerEngine:
    def __init__(self, domain: DomainConfig, *, trace_logger: TraceLogger | None = None):
        self.domain = domain
        self.trace_logger = trace_logger

    def answer(
        self,
        query: str,
        hits: list[RetrievalHit],
        *,
        route: str,
        trace_id: str,
        escalation: dict | None = None,
    ) -> QueryResponse:
        started = perf_counter()
        confidence = _support_score(query, hits)
        abstained = confidence < self.domain.abstention_threshold
        safety = {"evidence_treated_as_untrusted": True, "injection_lines_removed": False}
        if abstained:
            answer = ABSTENTION_TEXT
            citations: list[Citation] = []
        else:
            answer, removed = _extractive_answer(query, hits)
            safety["injection_lines_removed"] = removed
            citations = [Citation.from_hit(hit) for hit in hits[:3]]
            if not answer:
                answer = ABSTENTION_TEXT
                abstained = True
                citations = []
        latency = perf_counter() - started
        response = QueryResponse(
            query=query,
            domain=self.domain.id,
            route=route,
            answer=answer,
            abstained=abstained,
            confidence=confidence,
            citations=citations,
            retrieved=hits,
            trace_id=trace_id,
            escalation=escalation,
            safety=safety,
            latency_seconds=latency,
        )
        if self.trace_logger:
            self.trace_logger.emit({
                "trace_id": trace_id,
                "span": "answer",
                "route": route,
                "domain": self.domain.id,
                "abstained": abstained,
                "citation_count": len(citations),
                "confidence": round(confidence, 4),
                "latency_seconds": round(latency, 6),
            })
        return response

