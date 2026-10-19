from __future__ import annotations

from celery import Celery
import ssl

from .settings import get_settings


settings = get_settings()
celery_app = Celery("docintel", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    include=["app.tasks.jobs", "app.tasks.sandbox"],
    task_routes={"app.tasks.sandbox.run_sandbox_task": {"queue": "sandbox"}},
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    task_time_limit=1800,
    task_soft_time_limit=1500,
    broker_connection_retry_on_startup=True,
)

if settings.redis_url.startswith("rediss://"):
    celery_app.conf.update(
        broker_use_ssl={"ssl_cert_reqs": ssl.CERT_REQUIRED},
        redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_REQUIRED},
    )

# Import task modules eagerly so API processes, tests, and Celery workers expose
# the same task registry instead of relying on worker-only lazy discovery.
from .tasks import jobs as _jobs  # noqa: E402,F401
from .tasks import sandbox as _sandbox  # noqa: E402,F401

