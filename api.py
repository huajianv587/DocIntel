from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .agent import SupportAgent
from .config import DEFAULT_DOMAIN_DIR, list_domains, load_domain, runtime_config
from .ingestion import load_chunks
from .observability import TraceLogger
from .retrieval import HybridRetriever


def build_agent(
    *,
    domain_name: str | None = None,
    index_path: str | None = None,
    trace_path: str | None = None,
) -> SupportAgent:
    runtime = runtime_config()
    domain = load_domain(domain_name or runtime["domain"], DEFAULT_DOMAIN_DIR)
    resolved_index = Path(index_path or runtime["index_path"])
    chunks = load_chunks(resolved_index, domain=domain.id) if resolved_index.exists() else []
    logger = TraceLogger(trace_path or runtime["trace_path"])
    return SupportAgent(domain, HybridRetriever(chunks), trace_logger=logger)


def create_app(*, agent: SupportAgent | None = None):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import FileResponse
    except ImportError as exc:
        raise RuntimeError("HTTP API requires: pip install -r requirements.txt") from exc

    current_agent = agent or build_agent()
    app = FastAPI(title="DocIntel", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "domain": current_agent.domain.id,
            "indexed_chunks": len(current_agent.retriever.chunks),
            "evidence_mode": "extractive_with_citations",
        }

    @app.get("/domains")
    def domains() -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "abstention_threshold": item.abstention_threshold,
            }
            for item in list_domains()
        ]

    @app.post("/query")
    def query(payload: dict[str, Any]) -> dict[str, Any]:
        question = str(payload.get("query", "")).strip()
        if not question:
            raise HTTPException(status_code=400, detail="query is required")
        allowed = payload.get("allowed_source_ids")
        allowed_source_ids = {str(value) for value in allowed} if isinstance(allowed, list) else None
        response = current_agent.answer(
            question,
            top_k=max(1, min(int(payload.get("top_k", 5)), 20)),
            tenant_id=str(payload.get("tenant_id", "default")),
            allowed_source_ids=allowed_source_ids,
        )
        return response.to_dict()

    @app.get("/", include_in_schema=False)
    def index():
        path = Path(__file__).resolve().parents[1] / "web" / "index.html"
        return FileResponse(path)

    return app

