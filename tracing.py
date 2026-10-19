from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..models import TraceRecord

try:
    from opentelemetry import trace as otel_trace
except Exception:  # pragma: no cover - optional runtime integration
    otel_trace = None


@dataclass
class TraceContext:
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    route: str = "document_search"
    model: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.perf_counter)

    def event(self, name: str, *, status: str = "ok", **payload: Any) -> None:
        if otel_trace is not None:
            tracer = otel_trace.get_tracer("docintel")
            with tracer.start_as_current_span(name) as span:
                span.set_attribute("docintel.trace_id", self.trace_id)
                span.set_attribute("docintel.status", status)
                for key, value in payload.items():
                    if isinstance(value, (str, int, float, bool)):
                        span.set_attribute(f"docintel.{key}", value)
        self.events.append({
            "name": name,
            "status": status,
            "at_ms": round((time.perf_counter() - self.started_at) * 1000, 2),
            **payload,
        })

    @property
    def latency_ms(self) -> int:
        return round((time.perf_counter() - self.started_at) * 1000)

    def persist(
        self,
        db: Session,
        *,
        user_id: str | None = None,
        conversation_id: str | None = None,
        status: str = "ok",
        cost_usd: float = 0.0,
    ) -> TraceRecord:
        record = TraceRecord(
            id=self.trace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            route=self.route,
            status=status,
            model=self.model,
            latency_ms=self.latency_ms,
            cost_usd=cost_usd,
            events=self.events,
            extra_metadata=self.metadata,
        )
        db.add(record)
        db.flush()
        return record

