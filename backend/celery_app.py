import os
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv
from .config import JobSettings

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
settings = JobSettings.from_env()

celery_app = Celery(
    "ocr",
    broker=os.getenv("CELERY_BROKER_URL") or "redis://127.0.0.1:6379/0",
    include=["backend.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,  # Durable status and results are stored in PostgreSQL.
    task_default_queue="ocr",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=5,
    broker_transport_options={"visibility_timeout": 3600, "socket_connect_timeout": 5, "socket_timeout": 5},
    task_publish_retry=False,
    task_soft_time_limit=settings.soft_limit,
    task_time_limit=settings.hard_limit,
    timezone="UTC",
)
