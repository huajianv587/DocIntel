from __future__ import annotations

import re
import uuid
from time import perf_counter

from .answering import AnswerEngine
from .config import DomainConfig
from .models import QueryResponse
from .observability import TraceLogger
from .retrieval import HybridRetriever


class SupportAgent:
    def __init__(
        self,
        domain: DomainConfig,
        retriever: HybridRetriever,
        *,
        trace_logger: TraceLogger | None = None,
    ):
        self.domain = domain
        self.retriever = retriever
        self.trace_logger = trace_logger
        self.answer_engine = AnswerEngine(domain, trace_logger=trace_logger)

    def route(self, query: str) -> str:
        lowered = query.lower()
        if lowered.strip() in {"hi", "hello", "hey", "thanks", "thank you", "你好", "谢谢"}:
            return "direct"
        if any(term in lowered for term in ("human", "person", "escalate", "support ticket", "人工")):
            return "handoff"
        if self.domain.id == "tech_support" and any(
            term in lowered for term in ("error", "exception", "bug", "issue", "traceback", "not working")
        ):
            return "issue_search"
        if self.domain.id == "tech_support" and any(term in lowered for term in ("how do i", "how can i", "configure")):
            return "issue_search"
        return "document_search"

    def answer(
        self,
        query: str,
        *,
        top_k: int = 5,
        tenant_id: str = "default",
        allowed_source_ids: set[str] | None = None,
    ) -> QueryResponse:
        started = perf_counter()
        trace_id = uuid.uuid4().hex
        route = self.route(query)
        if self.trace_logger:
            self.trace_logger.emit({
                "trace_id": trace_id,
                "span": "route",
                "domain": self.domain.id,
                "route": route,
                "query_length": len(query),
            })

        if route == "direct":
            response = QueryResponse(
                query=query,
                domain=self.domain.id,
                route=route,
                answer="I can help answer questions grounded in the indexed documents.",
                abstained=False,
                confidence=1.0,
                trace_id=trace_id,
                safety={"evidence_treated_as_untrusted": True, "external_actions_taken": False},
                latency_seconds=perf_counter() - started,
            )
            return response

        if route == "handoff":
            escalation = {
                "status": "draft",
                "ticket_title": query[:120],
                "summary": "User requested human support; no external action was taken.",
                "allowed_actions": ["review", "assign", "reply"],
            }
            response = self.answer_engine.answer(query, [], route=route, trace_id=trace_id, escalation=escalation)
            response.answer = "I cannot answer from the indexed evidence. A human support ticket draft was prepared; no external action was taken."
            response.latency_seconds = perf_counter() - started
            return response

        source_type = "issue" if route == "issue_search" else None
        hits = self.retriever.retrieve(
            query,
            top_k=top_k,
            domain=self.domain.id,
            source_type=source_type,
            tenant_id=tenant_id,
            allowed_source_ids=allowed_source_ids,
        )
        response = self.answer_engine.answer(query, hits, route=route, trace_id=trace_id)
        response.latency_seconds = perf_counter() - started
        if self.trace_logger:
            self.trace_logger.emit({
                "trace_id": trace_id,
                "span": "retrieval",
                "domain": self.domain.id,
                "route": route,
                "hit_count": len(hits),
                "source_ids": [hit.chunk.source_id for hit in hits],
            })
        return response

