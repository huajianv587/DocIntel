from __future__ import annotations

import json
from statistics import mean
from time import perf_counter
from typing import Any

from .agent import SupportAgent
from .io import read_jsonl, write_json
from .models import GoldCase


def load_gold(path: str) -> list[GoldCase]:
    return [GoldCase.from_dict(row) for row in read_jsonl(path)]


def _contains_all(answer: str, expected: list[str]) -> bool:
    lowered = answer.lower()
    return bool(expected) and all(term.lower() in lowered for term in expected)


def evaluate_case(agent: SupportAgent, case: GoldCase, *, top_k: int = 5) -> dict[str, Any]:
    started = perf_counter()
    response = agent.answer(case.query, top_k=top_k, tenant_id=case.tenant_id)
    source_ids = {item.source_id for item in response.citations}
    retrieved_source_ids = {item.chunk.source_id for item in response.retrieved}
    expected_source_hit = case.expected_source_id in retrieved_source_ids
    citation_correct = case.expected_source_id in source_ids
    answer_match = _contains_all(response.answer, case.expected_answer_contains)
    abstention_correct = response.abstained == case.should_abstain
    return {
        "case_id": case.case_id,
        "query": case.query,
        "expected_source_id": case.expected_source_id,
        "should_abstain": case.should_abstain,
        "retrieved_source_ids": sorted(retrieved_source_ids),
        "cited_source_ids": sorted(source_ids),
        "hit_at_5": 1.0 if expected_source_hit else 0.0,
        "citation_accuracy": 1.0 if citation_correct else 0.0,
        "answer_match": 1.0 if answer_match else 0.0,
        "abstention_correct": 1.0 if abstention_correct else 0.0,
        "unsupported_answer": 1.0 if not response.abstained and not response.citations else 0.0,
        "abstained": response.abstained,
        "confidence": response.confidence,
        "latency_seconds": response.latency_seconds,
        "route": response.route,
        "answer": response.answer,
        "response": response.to_dict(),
        "wall_latency_seconds": perf_counter() - started,
    }


def run_evaluation(
    agent: SupportAgent,
    gold_path: str,
    *,
    top_k: int = 5,
    fixture: bool = False,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    cases = load_gold(gold_path)
    rows = [evaluate_case(agent, case, top_k=top_k) for case in cases]
    answerable_rows = [row for row in rows if not row["should_abstain"]]
    def average(field: str, selected: list[dict[str, Any]]) -> float:
        return round(mean(float(row[field]) for row in selected), 6) if selected else 0.0

    summary = {
        "hit_at_5": average("hit_at_5", answerable_rows),
        "citation_accuracy": average("citation_accuracy", answerable_rows),
        "answer_match": average("answer_match", answerable_rows),
        "abstention_correct": average("abstention_correct", rows),
        "unsupported_answer": average("unsupported_answer", answerable_rows),
        "latency_seconds": average("latency_seconds", rows),
    }
    thresholds = thresholds or {}
    checks = {
        key: summary.get(key, 0.0) >= value
        for key, value in thresholds.items()
    }
    return {
        "schema_version": "docintel.eval.v1",
        "fixture": fixture,
        "domain": agent.domain.id,
        "gold_path": gold_path,
        "n": len(rows),
        "summary": summary,
        "thresholds": thresholds,
        "checks": checks,
        "passed": all(checks.values()) if checks else True,
        "rows": rows,
    }


def write_evaluation(report: dict[str, Any], path: str) -> None:
    write_json(path, report)


def compare_reports(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    current_summary = current.get("summary", {})
    baseline_summary = baseline.get("summary", {})
    fields = sorted(set(current_summary) & set(baseline_summary))
    return {
        "current_domain": current.get("domain"),
        "baseline_domain": baseline.get("domain"),
        "current_fixture": current.get("fixture", False),
        "baseline_fixture": baseline.get("fixture", False),
        "delta": {
            field: round(float(current_summary[field]) - float(baseline_summary[field]), 6)
            for field in fields
        },
    }

