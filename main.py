from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .api import admin, auth, conversations, query, tickets
from .auth import hash_password
from .db import SessionLocal, engine, init_db
from .models import DocumentSource, User
from .observability import instrument_http, metrics_payload
from .settings import get_settings


def bootstrap_admin() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == settings.bootstrap_admin_email.lower()).first()
        if not user:
            db.add(User(email=settings.bootstrap_admin_email.lower(), password_hash=hash_password(settings.bootstrap_admin_password), role="admin"))
            db.commit()
    finally:
        db.close()


def bootstrap_sources() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        for repository in settings.github_repository_list:
            key = f"github:{repository}"
            if not db.query(DocumentSource).filter(DocumentSource.source_key == key).first():
                db.add(DocumentSource(source_key=key, kind="github", repository=repository, name=repository, config={"issues": True, "documents": True}))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bootstrap_admin()
    bootstrap_sources()
    yield
    engine.dispose()


app = FastAPI(title="DocIntel Support Workbench", version="1.0.0", lifespan=lifespan)
settings = get_settings()
app.middleware("http")(instrument_http)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(query.router)
app.include_router(conversations.router)
app.include_router(tickets.router)
app.include_router(admin.router)

frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="frontend-assets")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}


@app.get("/ready")
def ready() -> dict:
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
    return {"status": "ready", "database": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(metrics_payload(), media_type="text/plain; version=0.0.4")


@app.get("/domains")
def domains() -> list[dict]:
    return [
        {"id": "tech_support", "name": "Developer technical support", "status": "primary"},
        {"id": "esg", "name": "ESG long documents", "status": "adapter"},
    ]


@app.get("/", include_in_schema=False)
def root():
    frontend_index = Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html"
    fallback = Path(__file__).resolve().parents[1] / "web" / "index.html"
    return FileResponse(frontend_index if frontend_index.exists() else fallback)

