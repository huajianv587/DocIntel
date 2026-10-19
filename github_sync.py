from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DocumentChunk, DocumentSource, DocumentVersion, IngestionJob, new_id
from ..settings import get_settings
from docintel.ingestion import _split_text
from .storage import ObjectStorage
from .vector import QdrantVectorService


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class GitHubSyncService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.storage = ObjectStorage()
        self.vector = QdrantVectorService()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "docintel-sync/1.0"}
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        return headers

    def _get(self, client: httpx.Client, url: str, **params: Any) -> Any:
        response = client.get(url, params=params or None, headers=self._headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    def sync_repository(self, db: Session, repository: str, job: IngestionJob | None = None) -> dict[str, Any]:
        if job is None:
            job = IngestionJob(kind="sync", status="running", attempt=1)
            db.add(job)
            db.flush()
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.attempt += 1
        source = db.scalar(select(DocumentSource).where(DocumentSource.source_key == f"github:{repository}"))
        if not source:
            source = DocumentSource(source_key=f"github:{repository}", repository=repository, name=repository, kind="github")
            db.add(source)
            db.flush()
        job.source_id = source.id
        created = 0
        updated = 0
        failures: list[dict[str, str]] = []
        try:
            with httpx.Client(base_url="https://api.github.com") as client:
                repo_meta = self._get(client, f"/repos/{repository}")
                branch = str(repo_meta.get("default_branch") or "main")
                commit = self._get(client, f"/repos/{repository}/commits/{branch}")
                commit_sha = str(commit.get("sha", ""))
                tree = self._get(client, f"/repos/{repository}/git/trees/{commit_sha or branch}", recursive=1)
                paths = [item for item in tree.get("tree", []) if item.get("type") == "blob" and str(item.get("path", "")).lower().endswith((".md", ".rst", ".txt"))]
                selected_paths = paths[: self.settings.github_max_documents]
                for item in selected_paths:
                    path = str(item["path"])
                    try:
                        raw_url = f"https://raw.githubusercontent.com/{repository}/{commit_sha}/{path}"
                        raw_response = client.get(raw_url, headers={"User-Agent": "docintel-sync/1.0"}, timeout=30)
                        raw_response.raise_for_status()
                        content = raw_response.text
                        created_one, updated_one = self._upsert_document(
                            db, source, external_id=f"file:{path}", title=path, url=f"https://github.com/{repository}/blob/{commit_sha}/{path}",
                            content=content, commit_sha=commit_sha, content_type="markdown",
                        )
                        created += created_one
                        updated += updated_one
                    except Exception as exc:
                        failures.append({"path": path, "error": str(exc)})
                issue_page_size = min(max(self.settings.github_max_issues * 2, 20), 100)
                issues = self._get(client, f"/repos/{repository}/issues", state="all", per_page=issue_page_size, page=1)
                for issue in [item for item in issues if "pull_request" not in item][: self.settings.github_max_issues]:
                    issue_number = int(issue["number"])
                    comments = self._get(client, f"/repos/{repository}/issues/{issue_number}/comments", per_page=self.settings.github_max_comments)
                    body = "\n".join([
                        f"Title: {issue.get('title', '')}",
                        f"State: {issue.get('state', '')}",
                        f"Body: {issue.get('body') or ''}",
                        "Comments:",
                        *[str(comment.get("body") or "") for comment in comments],
                    ])
                    created_one, updated_one = self._upsert_document(
                        db, source, external_id=f"issue:{issue_number}", title=f"Issue #{issue_number}: {issue.get('title', '')}",
                        url=str(issue.get("html_url", "")), content=body, commit_sha=None, content_type="github_issue",
                        issue_metadata={"issue_number": issue_number, "state": issue.get("state"), "repository": repository, "closed_at": issue.get("closed_at")},
                    )
                    created += created_one
                    updated += updated_one
            source.last_synced_at = datetime.now(timezone.utc)
            source.status = "active"
            job.status = "completed"
            job.report = {
                "repository": repository,
                "created": created,
                "updated": updated,
                "failures": failures,
                "branch": branch,
                "commit_sha": commit_sha,
                "documents_seen": len(paths),
                "documents_selected": len(selected_paths),
                "limits": {
                    "documents": self.settings.github_max_documents,
                    "issues": self.settings.github_max_issues,
                    "comments": self.settings.github_max_comments,
                },
            }
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.report = {"repository": repository, "failures": failures}
            raise
        finally:
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
        return job.report

    def _upsert_document(
        self,
        db: Session,
        source: DocumentSource,
        *,
        external_id: str,
        title: str,
        url: str,
        content: str,
        commit_sha: str | None,
        content_type: str,
        issue_metadata: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        content_sha = _sha(content)
        existing = db.scalar(select(DocumentVersion).where(DocumentVersion.source_id == source.id, DocumentVersion.content_sha == content_sha))
        if existing:
            return 0, 0
        version = DocumentVersion(
            source_id=source.id,
            external_id=external_id,
            title=title,
            source_url=url,
            repository=source.repository,
            commit_sha=commit_sha,
            content_sha=content_sha,
            content_type=content_type,
            status="processing",
        )
        db.add(version)
        db.flush()
        version.raw_object_key = self.storage.put_bytes(f"raw/{source.repository}/{content_sha}.txt", content.encode("utf-8"), "text/plain")
        sections = _split_text(content, title=title)
        quality_report = {
            "character_count": len(content),
            "section_count": len({section for section, _ in sections}),
            "chunk_count": len(sections),
            "empty_chunks": sum(1 for _, text in sections if not text.strip()),
            "issue_closed_not_gold": content_type == "github_issue" and (issue_metadata or {}).get("state") == "closed",
        }
        for index, (section, text) in enumerate(sections):
            chunk_key = f"{source.repository}:{external_id}:{content_sha[:16]}:{index}"
            db.add(DocumentChunk(
                version_id=version.id,
                chunk_key=chunk_key,
                text=text,
                section=section,
                extra_metadata={
                    "source_id": external_id,
                    "source_type": "issue" if content_type == "github_issue" else "document",
                    "title": title,
                    "url": url,
                    "repository": source.repository,
                    "content_sha": content_sha,
                    "commit_sha": commit_sha,
                    "version_id": version.id,
                    **(issue_metadata or {}),
                },
            ))
        db.flush()
        persisted_chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.version_id == version.id)).all())
        self.vector.upsert([
            {
                "chunk_key": chunk.chunk_key,
                "text": chunk.text,
                "domain": "tech_support",
                "source_id": external_id,
                "source_type": "issue" if content_type == "github_issue" else "document",
                "title": title,
                "url": url,
                "section": chunk.section,
                "page": chunk.page,
            }
            for chunk in persisted_chunks
        ])
        version.chunk_count = len(sections)
        version.quality_report = quality_report
        version.status = "ready"
        db.flush()
        return 1, 0

