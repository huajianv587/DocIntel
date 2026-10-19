from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOMAIN_DIR = ROOT / "config" / "domains"


@dataclass(frozen=True)
class DomainConfig:
    id: str
    name: str
    description: str
    document_extensions: tuple[str, ...] = ()
    issue_extensions: tuple[str, ...] = ()
    routing_keywords: tuple[str, ...] = ()
    answer_style: str = ""
    required_citation_fields: tuple[str, ...] = ()
    abstention_threshold: float = 0.15
    metadata_fields: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "DomainConfig":
        known = {
            "id", "name", "description", "document_extensions", "issue_extensions",
            "routing_keywords", "answer_style", "required_citation_fields",
            "abstention_threshold", "metadata_fields",
        }
        return cls(
            id=str(row["id"]),
            name=str(row.get("name", row["id"])),
            description=str(row.get("description", "")),
            document_extensions=tuple(str(v).lower() for v in row.get("document_extensions", [])),
            issue_extensions=tuple(str(v).lower() for v in row.get("issue_extensions", [])),
            routing_keywords=tuple(str(v).lower() for v in row.get("routing_keywords", [])),
            answer_style=str(row.get("answer_style", "")),
            required_citation_fields=tuple(str(v) for v in row.get("required_citation_fields", [])),
            abstention_threshold=float(row.get("abstention_threshold", 0.15)),
            metadata_fields=tuple(str(v) for v in row.get("metadata_fields", [])),
            extra={key: value for key, value in row.items() if key not in known},
        )


def load_domain(domain: str, domain_dir: str | Path = DEFAULT_DOMAIN_DIR) -> DomainConfig:
    path = Path(domain_dir) / f"{domain}.json"
    if not path.exists():
        raise FileNotFoundError(f"Unknown domain {domain!r}; expected {path}")
    with path.open("r", encoding="utf-8") as handle:
        return DomainConfig.from_dict(json.load(handle))


def list_domains(domain_dir: str | Path = DEFAULT_DOMAIN_DIR) -> list[DomainConfig]:
    return [
        load_domain(path.stem, domain_dir)
        for path in sorted(Path(domain_dir).glob("*.json"))
    ]


def runtime_config() -> dict[str, str]:
    return {
        "domain": os.getenv("DOCINTEL_DOMAIN", "tech_support"),
        "index_path": os.getenv("DOCINTEL_INDEX_PATH", "artifacts/index.jsonl"),
        "trace_path": os.getenv("DOCINTEL_TRACE_PATH", "artifacts/traces.jsonl"),
    }

