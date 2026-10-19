from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise the running DocIntel Compose stack.")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--frontend", default="http://127.0.0.1:5173")
    parser.add_argument("--prometheus", default="http://127.0.0.1:9090")
    parser.add_argument("--grafana", default="http://127.0.0.1:3001")
    parser.add_argument("--email", default="admin@docintel.io")
    parser.add_argument("--password", default="change-me-now")
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    client = httpx.Client(timeout=30, follow_redirects=True)

    def check(name: str, response: httpx.Response, expected: set[int]) -> httpx.Response:
        ok = response.status_code in expected
        results.append({
            "name": name,
            "status": response.status_code,
            "ok": ok,
            "detail": "" if ok else response.text[:300].replace("\n", " "),
        })
        return response

    check("health", client.get(f"{args.api}/health"), {200})
    check("ready", client.get(f"{args.api}/ready"), {200})
    login = check("login", client.post(f"{args.api}/auth/login", json={"email": args.email, "password": args.password}), {200})
    if login.status_code != 200:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 2
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    check("me", client.get(f"{args.api}/auth/me", headers=headers), {200})
    check("admin_metrics", client.get(f"{args.api}/api/admin/metrics", headers=headers), {200})
    conversation = check(
        "create_conversation",
        client.post(f"{args.api}/api/conversations", headers=headers, json={"title": "Compose smoke", "domain": "tech_support"}),
        {200},
    )
    if conversation.status_code != 200:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 2
    conversation_id = conversation.json()["id"]

    direct = check("direct_answer", client.post(f"{args.api}/api/conversations/{conversation_id}/messages", headers=headers, json={"query": "hello"}), {200})
    if direct.status_code == 200:
        results.append({"name": "direct_route", "status": 200, "ok": direct.json().get("route") == "direct", "detail": direct.json().get("route")})
    abstain = check(
        "abstention",
        client.post(f"{args.api}/api/conversations/{conversation_id}/messages", headers=headers, json={"query": "Explain the unindexed nebula-xyz behavior."}),
        {200},
    )
    if abstain.status_code == 200:
        results.append({"name": "abstention_assertion", "status": 200, "ok": bool(abstain.json().get("abstained")), "detail": str(abstain.json().get("abstained"))})
    sandbox = check(
        "sandbox_route",
        client.post(
            f"{args.api}/api/conversations/{conversation_id}/messages",
            headers=headers,
            json={"query": "run this reproduction", "code": "print('compose-sandbox')"},
        ),
        {200},
    )
    if sandbox.status_code == 200:
        sandbox_body = sandbox.json()
        results.append({"name": "sandbox_route_assertion", "status": 200, "ok": sandbox_body.get("route") == "code_validation", "detail": str(sandbox_body.get("route"))})
        sandbox_events = sandbox_body.get("tool_events") or []
        results.append({"name": "sandbox_execution_assertion", "status": 200, "ok": bool(sandbox_events) and sandbox_events[0].get("status") == "passed", "detail": str(sandbox_events)})
    stream = check(
        "sse_stream",
        client.post(f"{args.api}/api/conversations/{conversation_id}/messages/stream", headers=headers, json={"query": "thanks"}),
        {200},
    )
    if stream.status_code == 200:
        for marker in ("event: meta", "event: result", "event: done"):
            results.append({"name": f"sse_{marker[7:].strip()}", "status": 200, "ok": marker in stream.text, "detail": marker})
    trace = check("trace", client.get(f"{args.api}/api/conversations/{conversation_id}/trace", headers=headers), {200})
    if trace.status_code == 200:
        results.append({"name": "trace_events", "status": 200, "ok": len(trace.json()) >= 2, "detail": str(len(trace.json()))})
    ticket = check(
        "create_ticket",
        client.post(f"{args.api}/api/tickets", headers=headers, json={"conversation_id": conversation_id, "title": "Compose smoke ticket", "summary": "Smoke test"}),
        {200},
    )
    if ticket.status_code == 200:
        check("update_ticket", client.patch(f"{args.api}/api/tickets/{ticket.json()['id']}", headers=headers, json={"status": "queued"}), {200})
    check("frontend", client.get(args.frontend), {200})
    check("prometheus", client.get(f"{args.prometheus}/-/ready"), {200})
    check("grafana", client.get(f"{args.grafana}/api/health"), {200})

    print(json.dumps(results, ensure_ascii=False, indent=2))
    failed = [item for item in results if not item["ok"]]
    print(f"PASS={len(results) - len(failed)} FAIL={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
