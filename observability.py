from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class TraceLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def emit(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    @contextmanager
    def span(self, name: str, *, trace_id: str | None = None, **metadata: Any) -> Iterator[str]:
        span_id = uuid.uuid4().hex[:16]
        active_trace = trace_id or uuid.uuid4().hex
        started = time.perf_counter()
        try:
            yield span_id
            status = "ok"
        except Exception as exc:
            status = "error"
            self.emit({
                "trace_id": active_trace,
                "span_id": span_id,
                "name": name,
                "status": status,
                "error": str(exc),
                "latency_seconds": round(time.perf_counter() - started, 6),
                "metadata": metadata,
            })
            raise
        self.emit({
            "trace_id": active_trace,
            "span_id": span_id,
            "name": name,
            "status": status,
            "latency_seconds": round(time.perf_counter() - started, 6),
            "metadata": metadata,
        })

