from __future__ import annotations

from datetime import datetime, timezone

from ..celery_app import celery_app
from ..db import SessionLocal
from ..models import EvaluationRun, IngestionJob
from ..services.evaluation import run_database_evaluation
from ..services.github_sync import GitHubSyncService


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def sync_github_repository(self, repository: str, job_id: str | None = None) -> dict:
    db = SessionLocal()
    try:
        job = db.get(IngestionJob, job_id) if job_id else None
        report = GitHubSyncService().sync_repository(db, repository, job=job)
        return report
    finally:
        db.close()


@celery_app.task(bind=True)
def run_evaluation_job(self, run_id: str, domain: str, gold_path: str) -> dict:
    db = SessionLocal()
    run = db.get(EvaluationRun, run_id)
    if not run:
        return {"status": "missing", "run_id": run_id}
    run.status = "running"
    db.commit()
    try:
        report = run_database_evaluation(db, domain=domain, gold_path=gold_path, run=run)
        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        return report
    except Exception as exc:
        run.status = "failed"
        run.metrics = {"error": str(exc)}
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise
    finally:
        db.close()

