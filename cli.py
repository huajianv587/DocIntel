from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .api import build_agent
from .config import DEFAULT_DOMAIN_DIR, load_domain
from .evaluation import compare_reports, run_evaluation, write_evaluation
from .ingestion import ingest_directory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docintel", description="Auditable multi-domain RAG support platform")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="ingest documents and issues into a versioned JSONL index")
    ingest.add_argument("--domain", required=True)
    ingest.add_argument("--path", required=True)
    ingest.add_argument("--index", required=True)

    query = sub.add_parser("query", help="answer one question from an index")
    query.add_argument("--domain", default=None)
    query.add_argument("--index", default=None)
    query.add_argument("--query", required=True)
    query.add_argument("--top-k", type=int, default=5)

    evaluate = sub.add_parser("evaluate", help="run a gold-set regression evaluation")
    evaluate.add_argument("--domain", required=True)
    evaluate.add_argument("--index", required=True)
    evaluate.add_argument("--gold", required=True)
    evaluate.add_argument("--report", required=True)
    evaluate.add_argument("--top-k", type=int, default=5)
    evaluate.add_argument("--min-recall-at-5", type=float, default=None)
    evaluate.add_argument("--min-citation-accuracy", type=float, default=None)
    evaluate.add_argument("--min-abstention-correct", type=float, default=None)
    evaluate.add_argument("--baseline", default=None, help="previous evaluation JSON for metric deltas")

    serve = sub.add_parser("serve", help="run the FastAPI server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "ingest":
        domain = load_domain(args.domain, DEFAULT_DOMAIN_DIR)
        report = ingest_directory(domain, args.path, args.index)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 1 if report.failures else 0

    if args.command == "query":
        agent = build_agent(domain_name=args.domain, index_path=args.index)
        print(json.dumps(agent.answer(args.query, top_k=args.top_k).to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "evaluate":
        agent = build_agent(domain_name=args.domain, index_path=args.index)
        thresholds = {}
        if args.min_recall_at_5 is not None:
            thresholds["hit_at_5"] = args.min_recall_at_5
        if args.min_citation_accuracy is not None:
            thresholds["citation_accuracy"] = args.min_citation_accuracy
        if args.min_abstention_correct is not None:
            thresholds["abstention_correct"] = args.min_abstention_correct
        report = run_evaluation(agent, args.gold, top_k=args.top_k, fixture="fixtures" in str(args.gold), thresholds=thresholds)
        if args.baseline:
            with Path(args.baseline).open("r", encoding="utf-8") as handle:
                report["comparison"] = compare_reports(report, json.load(handle))
        write_evaluation(report, args.report)
        print(json.dumps({"report": args.report, "summary": report["summary"], "passed": report["passed"]}, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1

    if args.command == "serve":
        try:
            import uvicorn
            from .api import create_app
        except ImportError as exc:
            print(f"{exc}. Install optional API dependencies with: pip install -r requirements.txt", file=sys.stderr)
            return 2
        uvicorn.run(create_app(), host=args.host, port=args.port)
        return 0

    return 2

