from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import DomainConfig
from .io import read_jsonl, write_json, write_jsonl
from .models import Chunk


SUPPORTED_TEXT_EXTENSIONS = {".md", ".txt", ".rst", ".html", ".csv"}
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 160


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: str) -> str:
    value = value.replace("\x00", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _split_text(text: str, *, title: str = "") -> list[tuple[str, str]]:
    """Split on headings first, then use bounded overlapping windows."""
    sections: list[tuple[str, str]] = []
    current_title = title
    buffer: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match and buffer:
            sections.append((current_title, "\n".join(buffer).strip()))
            buffer = []
        if match:
            current_title = match.group(1).strip()
        else:
            buffer.append(line)
    if buffer:
        sections.append((current_title, "\n".join(buffer).strip()))

    chunks: list[tuple[str, str]] = []
    for section, body in sections or [(title, text)]:
        body = _clean_text(body)
        if not body:
            continue
        start = 0
        while start < len(body):
            end = min(start + CHUNK_SIZE, len(body))
            window = body[start:end]
            if start > 0:
                window = body[max(0, start - CHUNK_OVERLAP):end]
            chunks.append((section, window.strip()))
            if end >= len(body):
                break
            start = end
    return chunks


def _read_pdf_pages(path: Path) -> list[tuple[int, str]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF ingestion requires the optional 'pypdf' dependency") from exc
    reader = PdfReader(str(path))
    pages: list[tuple[int, str]] = []
    for page_number, page in enumerate(reader.pages, 1):
        pages.append((page_number, _clean_text(page.extract_text() or "")))
    return pages


def _issue_text(row: dict[str, Any]) -> str:
    comments = row.get("comments") or []
    if isinstance(comments, list):
        comment_text = "\n".join(str(item) for item in comments)
    else:
        comment_text = str(comments)
    fields = [
        f"Title: {row.get('title', '')}",
        f"State: {row.get('state', '')}",
        f"Body: {row.get('body', '')}",
        f"Accepted answer: {row.get('accepted_answer', '')}",
        f"Comments: {comment_text}",
    ]
    return _clean_text("\n".join(field for field in fields if field.split(":", 1)[-1].strip()))


@dataclass
class IngestReport:
    domain: str
    input_path: str
    index_path: str
    files_seen: int = 0
    chunks_written: int = 0
    duplicate_files: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)
    quality_flags: list[dict[str, str]] = field(default_factory=list)
    versions: list[dict[str, str]] = field(default_factory=list)
    started_at: str = field(default_factory=_utc_now)
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "input_path": self.input_path,
            "index_path": self.index_path,
            "files_seen": self.files_seen,
            "chunks_written": self.chunks_written,
            "duplicate_files": self.duplicate_files,
            "failures": self.failures,
            "quality_flags": self.quality_flags,
            "versions": self.versions,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _read_file_records(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return read_jsonl(path)
    if suffix == ".pdf":
        return [
            {"page": page_number, "text": text}
            for page_number, text in _read_pdf_pages(path)
        ]
    if suffix in SUPPORTED_TEXT_EXTENSIONS:
        return [{"text": path.read_text(encoding="utf-8", errors="replace")}]
    raise ValueError(f"unsupported extension: {suffix}")


def _is_issue_file(path: Path, domain: DomainConfig) -> bool:
    return path.name.lower() in {"issues.jsonl", "issues.json"} or path.suffix.lower() in domain.issue_extensions and "issue" in path.stem.lower()


def _is_corpus_file(path: Path, domain: DomainConfig) -> bool:
    if path.name.lower() in {"gold.jsonl", "benchmark.jsonl", "review.jsonl"}:
        return False
    return path.suffix.lower() in set(domain.document_extensions) | set(domain.issue_extensions)


def _build_chunks(path: Path, root: Path, domain: DomainConfig) -> list[Chunk]:
    raw_bytes = path.read_bytes()
    file_hash = sha256_bytes(raw_bytes)
    version = file_hash[:16]
    relative_path = str(path.relative_to(root))
    is_issue = _is_issue_file(path, domain)
    source_type = "issue" if is_issue else "document"
    rows = _read_file_records(path)
    result: list[Chunk] = []

    for row_index, row in enumerate(rows):
        if is_issue:
            source_id = str(row.get("id") or row.get("issue_id") or f"{relative_path}:{row_index + 1}")
            title = str(row.get("title") or source_id)
            url = str(row.get("url") or "")
            metadata = {
                key: row.get(key)
                for key in ("repository", "state", "accepted_answer", "issue_id")
                if row.get(key) is not None
            }
            sections = [("issue", _issue_text(row))]
            page = None
        else:
            source_id = relative_path
            title = path.stem.replace("_", " ")
            url = ""
            metadata = {}
            text = str(row.get("text") or "")
            page = int(row["page"]) if row.get("page") is not None else None
            sections = _split_text(text, title=title)

        for chunk_index, (section, text) in enumerate(sections):
            text = _clean_text(text)
            if not text:
                continue
            chunk_hash = sha256_text(f"{domain.id}\n{source_id}\n{page}\n{text}")
            chunk_id = f"{domain.id}:{source_id}:{version}:{page or 0}:{chunk_index}"
            result.append(
                Chunk(
                    chunk_id=chunk_id,
                    domain=domain.id,
                    source_id=source_id,
                    source_type=source_type,
                    title=title,
                    text=text,
                    content_hash=chunk_hash,
                    version=version,
                    path=relative_path,
                    page=page,
                    section=section,
                    url=url,
                    metadata=metadata,
                )
            )
    return result


def _load_existing_chunks(index_path: Path) -> list[Chunk]:
    if not index_path.exists():
        return []
    chunks: list[Chunk] = []
    with index_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                chunks.append(Chunk.from_dict(json.loads(line)))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"{index_path}:{line_number}: invalid chunk row") from exc
    return chunks


def ingest_directory(
    domain: DomainConfig,
    input_path: str | Path,
    index_path: str | Path,
    *,
    retries: int = 2,
    include_extensions: set[str] | None = None,
    manifest_path: str | Path | None = None,
) -> IngestReport:
    root = Path(input_path).expanduser().resolve()
    target = Path(index_path)
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    allowed = include_extensions or set(domain.document_extensions) | set(domain.issue_extensions)
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in allowed and _is_corpus_file(path, domain)
    )
    existing = _load_existing_chunks(target)
    existing_by_file = {(chunk.path, chunk.version) for chunk in existing}
    dedupe_by_hash = {chunk.content_hash for chunk in existing}
    new_chunks = list(existing)
    report = IngestReport(domain=domain.id, input_path=str(root), index_path=str(target))

    for path in files:
        report.files_seen += 1
        try:
            file_hash = sha256_bytes(path.read_bytes())
            version = file_hash[:16]
            relative_path = str(path.relative_to(root))
            if (relative_path, version) in existing_by_file:
                report.duplicate_files += 1
                continue

            chunks: list[Chunk] | None = None
            last_error: Exception | None = None
            for attempt in range(retries + 1):
                try:
                    chunks = _build_chunks(path, root, domain)
                    break
                except Exception as exc:  # retry parse failures, then preserve the failure
                    last_error = exc
                    if attempt < retries:
                        continue
            if chunks is None:
                report.failures.append({"path": relative_path, "error": str(last_error)})
                continue

            fresh_chunks = []
            for chunk in chunks:
                if chunk.content_hash in dedupe_by_hash:
                    continue
                dedupe_by_hash.add(chunk.content_hash)
                fresh_chunks.append(chunk)
            new_chunks.extend(fresh_chunks)
            report.chunks_written += len(fresh_chunks)
            report.versions.append({"path": relative_path, "version": version, "chunks": str(len(fresh_chunks))})
            if not fresh_chunks:
                report.quality_flags.append({"path": relative_path, "flag": "no_new_content_after_deduplication"})
            if len(fresh_chunks) == 1 and sum(len(chunk.text) for chunk in fresh_chunks) < 80:
                report.quality_flags.append({"path": relative_path, "flag": "short_extracted_text"})
        except Exception as exc:
            report.failures.append({"path": str(path), "error": str(exc)})

    write_jsonl(target, (chunk.to_dict() for chunk in new_chunks))
    report.finished_at = _utc_now()
    report_path = Path(manifest_path) if manifest_path else target.with_suffix(".ingest.json")
    write_json(report_path, report.to_dict())
    return report


def load_chunks(index_path: str | Path, *, domain: str | None = None) -> list[Chunk]:
    chunks = _load_existing_chunks(Path(index_path))
    if domain is None:
        return chunks
    return [chunk for chunk in chunks if chunk.domain == domain]

