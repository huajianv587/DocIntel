from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_role
from ..celery_app import celery_app
from ..db import get_db
from ..models import AuditEvent, DocumentSource, EvaluationRun, GoldCase, IngestionJob, TraceRecord, User
from ..schemas import EvaluationRunCreate, EvaluationRunOut, GoldCaseCreate, GoldCaseOut, GoldCaseUpdate, SourceCreate, SourceOut, TraceOut, UserOut, UserUpdate
from ..settings import get_settings
from ..tasks.jobs import run_evaluation_job, sync_github_repository


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at.desc())).all())


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, payload: UserUpdate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> User:
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == user.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="The current administrator cannot deactivate their own account")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(target, key, value)
    db.add(AuditEvent(user_id=user.id, action="user.update", resource_type="user", resource_id=target.id, payload=payload.model_dump(exclude_unset=True)))
    db.commit()
    db.refresh(target)
    return target


@router.get("/sources", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> list[DocumentSource]:
    return list(db.scalars(select(DocumentSource).order_by(DocumentSource.created_at.desc())).all())


@router.post("/sources", response_model=SourceOut)
def create_source(payload: SourceCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> DocumentSource:
    key = f"github:{payload.repository}"
    source = db.scalar(select(DocumentSource).where(DocumentSource.source_key == key))
    if source:
        raise HTTPException(status_code=409, detail="Source already exists")
    source = DocumentSource(source_key=key, kind="github", repository=payload.repository, name=payload.name or payload.repository, config=payload.config)
    db.add(source)
    db.add(AuditEvent(user_id=user.id, action="source.create", resource_type="document_source", payload={"repository": payload.repository}))
    db.commit()
    db.refresh(source)
    return source


@router.post("/sources/{source_id}/sync")
def sync_source(source_id: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> dict:
    source = db.get(DocumentSource, source_id)
    if not source or not source.repository:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.status == "paused":
        raise HTTPException(status_code=409, detail="Source is paused")
    job = IngestionJob(source_id=source.id, kind="sync", status="queued")
    db.add(job)
    db.add(AuditEvent(user_id=user.id, action="source.sync", resource_type="document_source", resource_id=source.id, payload={"repository": source.repository}))
    db.commit()
    try:
        task = sync_github_repository.delay(source.repository, job.id)
        job.report = {"celery_task_id": task.id}
        db.commit()
        return {"job_id": job.id, "task_id": task.id, "status": job.status}
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        db.commit()
        raise HTTPException(status_code=503, detail="Worker queue unavailable") from exc


@router.post("/ingestion-jobs/{job_id}/retry")
def retry_ingestion_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> dict:
    job = db.get(IngestionJob, job_id)
    if not job or not job.source_id:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    source = db.get(DocumentSource, job.source_id)
    if not source or not source.repository:
        raise HTTPException(status_code=404, detail="Source not found")
    retry_job = IngestionJob(source_id=source.id, kind="sync", status="queued", attempt=job.attempt)
    db.add(retry_job)
    db.add(AuditEvent(user_id=user.id, action="ingestion.retry", resource_type="ingestion_job", resource_id=job.id, payload={"source_id": source.id}))
    db.commit()
    try:
        task = sync_github_repository.delay(source.repository, retry_job.id)
    except Exception as exc:
        retry_job.status = "failed"
        retry_job.error = str(exc)
        db.commit()
        raise HTTPException(status_code=503, detail="Worker queue unavailable") from exc
    retry_job.report = {"celery_task_id": task.id, "retried_from": job.id}
    db.commit()
    return {"job_id": retry_job.id, "task_id": task.id, "status": retry_job.status}


@router.post("/sources/{source_id}/pause", response_model=SourceOut)
def pause_source(source_id: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> DocumentSource:
    source = db.get(DocumentSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.status = "paused"
    db.add(AuditEvent(user_id=user.id, action="source.pause", resource_type="document_source", resource_id=source.id))
    db.commit()
    db.refresh(source)
    return source


@router.post("/sources/{source_id}/resume", response_model=SourceOut)
def resume_source(source_id: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> DocumentSource:
    source = db.get(DocumentSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.status = "active"
    db.add(AuditEvent(user_id=user.id, action="source.resume", resource_type="document_source", resource_id=source.id))
    db.commit()
    db.refresh(source)
    return source


@router.get("/ingestion-jobs")
def ingestion_jobs(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> list[dict]:
    rows = db.scalars(select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(100)).all()
    return [{"id": row.id, "source_id": row.source_id, "kind": row.kind, "status": row.status, "attempt": row.attempt, "error": row.error, "report": row.report, "created_at": row.created_at, "finished_at": row.finished_at} for row in rows]


@router.get("/evaluations", response_model=list[EvaluationRunOut])
def list_evaluations(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> list[EvaluationRun]:
    return list(db.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc())).all())


@router.get("/gold-cases", response_model=list[GoldCaseOut])
def list_gold_cases(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> list[GoldCase]:
    return list(db.scalars(select(GoldCase).order_by(GoldCase.updated_at.desc())).all())


@router.post("/gold-cases", response_model=GoldCaseOut)
def create_gold_case(payload: GoldCaseCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> GoldCase:
    existing = db.scalar(select(GoldCase).where(GoldCase.domain == payload.domain, GoldCase.case_key == payload.case_key))
    if existing:
        raise HTTPException(status_code=409, detail="Gold case key already exists for this domain")
    case = GoldCase(**payload.model_dump())
    db.add(case)
    db.add(AuditEvent(user_id=user.id, action="gold_case.create", resource_type="gold_case", payload={"case_key": case.case_key, "domain": case.domain}))
    db.commit()
    db.refresh(case)
    return case


@router.patch("/gold-cases/{case_id}", response_model=GoldCaseOut)
def update_gold_case(case_id: str, payload: GoldCaseUpdate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> GoldCase:
    case = db.get(GoldCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Gold case not found")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(case, key, value)
    if changes.get("status") == "approved":
        case.reviewed_by = user.id
    db.add(AuditEvent(user_id=user.id, action="gold_case.update", resource_type="gold_case", resource_id=case.id, payload=changes))
    db.commit()
    db.refresh(case)
    return case


@router.post("/evaluations/run", response_model=EvaluationRunOut)
def run_evaluation(payload: EvaluationRunCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> EvaluationRun:
    gold_path = payload.gold_path or ""
    run = EvaluationRun(created_by=user.id, version_label=payload.version_label, domain=payload.domain, status="queued", metrics={"gold_path": gold_path})
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        task = run_evaluation_job.delay(run.id, payload.domain, gold_path)
        run.metrics = {"gold_path": gold_path, "celery_task_id": task.id}
        db.commit()
    except Exception as exc:
        run.status = "failed"
        run.metrics = {"gold_path": gold_path, "error": str(exc), "status": "worker_unavailable"}
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
    return run


@router.get("/traces", response_model=list[TraceOut])
def list_traces(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> list[TraceRecord]:
    return list(db.scalars(select(TraceRecord).order_by(TraceRecord.created_at.desc()).limit(200)).all())


@router.get("/traces/{trace_id}", response_model=TraceOut)
def get_trace(trace_id: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> TraceRecord:
    trace = db.get(TraceRecord, trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.get("/metrics")
def metrics(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))) -> dict:
    return {
        "users": db.query(User).count(),
        "sources": db.query(DocumentSource).count(),
        "queued_ingestion_jobs": db.query(IngestionJob).filter(IngestionJob.status == "queued").count(),
        "failed_ingestion_jobs": db.query(IngestionJob).filter(IngestionJob.status == "failed").count(),
        "evaluation_runs": db.query(EvaluationRun).count(),
        "traces": db.query(TraceRecord).count(),
        "deepseek_configured": bool(get_settings().deepseek_api_key),
        "worker_broker": get_settings().redis_url,
    }

