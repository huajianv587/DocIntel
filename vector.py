from __future__ import annotations

import uuid
from typing import Any

from ..settings import get_settings


class QdrantVectorService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = None
        self.embedder = None
        try:
            from qdrant_client import QdrantClient

            client_options = {"url": self.settings.qdrant_url}
            if self.settings.qdrant_api_key:
                client_options["api_key"] = self.settings.qdrant_api_key
            self.client = QdrantClient(**client_options)
            try:
                from fastembed import TextEmbedding

                self.embedder = TextEmbedding(model_name=self.settings.embedding_model)
            except Exception:
                self.embedder = None
        except Exception:
            self.client = None

    @property
    def configured(self) -> bool:
        return self.client is not None and self.embedder is not None

    def _vectors(self, texts: list[str]) -> list[list[float]]:
        if not self.embedder:
            return []
        return [list(vector) for vector in self.embedder.embed(texts)]

    def ensure_collection(self, vector_size: int) -> None:
        if not self.client:
            return
        from qdrant_client.http import models

        collections = {item.name for item in self.client.get_collections().collections}
        if self.settings.qdrant_collection not in collections:
            self.client.create_collection(
                collection_name=self.settings.qdrant_collection,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )

    def upsert(self, chunks: list[dict[str, Any]]) -> int:
        if not self.configured or not chunks:
            return 0
        from qdrant_client.http import models

        vectors = self._vectors([str(item["text"]) for item in chunks])
        if not vectors:
            return 0
        self.ensure_collection(len(vectors[0]))
        points = []
        for chunk, vector in zip(chunks, vectors):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(chunk["chunk_key"])))
            points.append(models.PointStruct(id=point_id, vector=vector, payload=chunk))
        self.client.upsert(collection_name=self.settings.qdrant_collection, points=points, wait=True)
        return len(points)

    def search(self, query: str, *, top_k: int = 20, domain: str | None = None) -> dict[str, float]:
        if not self.configured:
            return {}
        vector = self._vectors([query])
        if not vector:
            return {}
        query_filter = None
        if domain:
            from qdrant_client.http import models

            query_filter = models.Filter(must=[models.FieldCondition(key="domain", match=models.MatchValue(value=domain))])
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=self.settings.qdrant_collection,
                query=vector[0],
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
            results = getattr(response, "points", response)
        else:
            results = self.client.search(
                collection_name=self.settings.qdrant_collection,
                query_vector=vector[0],
                query_filter=query_filter,
                limit=top_k,
            )
        return {str(item.payload.get("chunk_key")): float(item.score) for item in results if item.payload}

