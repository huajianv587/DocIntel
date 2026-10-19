from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import Mock


class AppApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.database.close()
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.database.name}"
        os.environ["S3_ENDPOINT_URL"] = ""
        os.environ["DEEPSEEK_API_KEY"] = ""
        os.environ["SANDBOX_ENABLED"] = "false"
        os.environ["GITHUB_REPOSITORIES"] = "fastapi/fastapi,django/django,kubernetes/website"
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        os.unlink(cls.database.name)

    def login(self) -> str:
        response = self.client.post("/auth/login", json={"email": "admin@docintel.io", "password": "change-me-now"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["access_token"]

    def test_auth_conversation_abstention_trace_and_ticket(self) -> None:
        token = self.login()
        headers = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 200)
        conversation = self.client.post("/api/conversations", headers=headers, json={"title": "API test", "domain": "tech_support"})
        self.assertEqual(conversation.status_code, 200, conversation.text)
        conversation_id = conversation.json()["id"]

        result = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=headers,
            json={"query": "Explain the undocumented nebula-xyz behavior."},
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["abstained"])
        self.assertEqual(result.json()["citations"], [])

        traces = self.client.get(f"/api/conversations/{conversation_id}/trace", headers=headers)
        self.assertEqual(traces.status_code, 200, traces.text)
        self.assertEqual([event["name"] for event in traces.json()[0]["events"]], ["route", "retrieval", "abstention", "result"])

        ticket = self.client.post("/api/tickets", headers=headers, json={"conversation_id": conversation_id, "title": "Needs review", "summary": "Evidence was insufficient"})
        self.assertEqual(ticket.status_code, 200, ticket.text)
        updated = self.client.patch(f"/api/tickets/{ticket.json()['id']}", headers=headers, json={"status": "in_progress"})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["status"], "in_progress")

    def test_admin_sources_and_metrics_are_protected(self) -> None:
        token = self.login()
        headers = {"Authorization": f"Bearer {token}"}
        sources = self.client.get("/api/admin/sources", headers=headers)
        self.assertEqual(sources.status_code, 200, sources.text)
        self.assertEqual({item["repository"] for item in sources.json()}, {"fastapi/fastapi", "django/django", "kubernetes/website"})
        self.assertEqual(self.client.get("/api/admin/metrics", headers=headers).status_code, 200)
        created = self.client.post("/api/admin/gold-cases", headers=headers, json={"case_key": "smoke-001", "domain": "tech_support", "query": "How should this be configured?", "expected_source_id": "issue:1"})
        self.assertEqual(created.status_code, 200, created.text)
        approved = self.client.patch(f"/api/admin/gold-cases/{created.json()['id']}", headers=headers, json={"status": "approved"})
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["status"], "approved")

    def test_celery_background_tasks_are_registered(self) -> None:
        from app.celery_app import celery_app

        self.assertIn("app.tasks.jobs.sync_github_repository", celery_app.tasks)
        self.assertIn("app.tasks.jobs.run_evaluation_job", celery_app.tasks)
        self.assertIn("app.tasks.sandbox.run_sandbox_task", celery_app.tasks)

    def test_low_score_vector_only_candidates_do_not_defeat_abstention(self) -> None:
        from app.services.retrieval import RetrievalService

        lexical_hit = Mock()
        lexical_hit.chunk.chunk_id = "lexical-1"
        eligible = RetrievalService._eligible_vector_keys(
            [lexical_hit],
            {"lexical-1": 0.20, "unrelated-1": 0.41, "semantic-1": 0.42},
            0.42,
        )
        self.assertEqual(eligible, {"lexical-1", "semantic-1"})


if __name__ == "__main__":
    unittest.main()
