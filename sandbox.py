from __future__ import annotations

from ..celery_app import celery_app
from ..services.sandbox import SandboxService
from ..services.tracing import TraceContext


@celery_app.task(bind=True)
def run_sandbox_task(self, code: str) -> dict:
    trace = TraceContext(route="code_validation")
    return SandboxService()._run_python_local(code, trace=trace)

