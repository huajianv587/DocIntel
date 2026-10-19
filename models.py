from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    domain: str
    source_id: str
    source_type: str
    title: str
    text: str
    content_hash: str
    version: str
    path: str = ""
    page: int | None = None
    section: str = ""
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "Chunk":
        return cls(
            chunk_id=str(row["chunk_id"]),
            domain=str(row.get("domain", "")),
            source_id=str(row["source_id"]),
            source_type=str(row.get("source_type", "document")),
            title=str(row.get("title", "")),
            text=str(row.get("text", "")),
            content_hash=str(row.get("content_hash", "")),
            version=str(row.get("version", "")),
            path=str(row.get("path", "")),
            page=int(row["page"]) if row.get("page") is not None else None,
            section=str(row.get("section", "")),
            url=str(row.get("url", "")),
            metadata=dict(row.get("metadata") or {}),
        )


@dataclass(frozen=True)
class RetrievalHit:
    chunk: Chunk
    score: float
    rank: int
    retriever: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk": self.chunk.to_dict(),
            "score": round(self.score, 6),
            "rank": self.rank,
            "retriever": self.retriever,
        }


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    source_id: str
    source_type: str
    title: str
    page: int | None
    section: str
    url: str
    score: float

    @classmethod
    def from_hit(cls, hit: RetrievalHit) -> "Citation":
        chunk = hit.chunk
        return cls(
            chunk_id=chunk.chunk_id,
            source_id=chunk.source_id,
            source_type=chunk.source_type,
            title=chunk.title,
            page=chunk.page,
            section=chunk.section,
            url=chunk.url,
            score=hit.score,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueryResponse:
    query: str
    domain: str
    route: str
    answer: str
    abstained: bool
    confidence: float
    citations: list[Citation] = field(default_factory=list)
    retrieved: list[RetrievalHit] = field(default_factory=list)
    trace_id: str = ""
    escalation: dict[str, Any] | None = None
    safety: dict[str, Any] = field(default_factory=dict)
    latency_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "domain": self.domain,
            "route": self.route,
            "answer": self.answer,
            "abstained": self.abstained,
            "confidence": round(self.confidence, 4),
            "citations": [item.to_dict() for item in self.citations],
            "retrieved": [item.to_dict() for item in self.retrieved],
            "trace_id": self.trace_id,
            "escalation": self.escalation,
            "safety": self.safety,
            "latency_seconds": round(self.latency_seconds, 4),
        }


@dataclass(frozen=True)
class GoldCase:
    case_id: str
    query: str
    expected_source_id: str
    expected_answer_contains: list[str] = field(default_factory=list)
    should_abstain: bool = False
    tenant_id: str = "default"

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "GoldCase":
        return cls(
            case_id=str(row["case_id"]),
            query=str(row["query"]),
            expected_source_id=str(row.get("expected_source_id", "")),
            expected_answer_contains=[str(value) for value in row.get("expected_answer_contains", [])],
            should_abstain=bool(row.get("should_abstain", False)),
            tenant_id=str(row.get("tenant_id", "default")),
        )

