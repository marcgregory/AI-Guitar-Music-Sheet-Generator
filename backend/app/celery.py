from celery import Celery
from app.core.config import settings

# Initialize Celery app
celery_app = Celery(
    "ai_guitar_music_sheet_generator",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks"
    ]
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    # Railway MVP: Demucs can be CPU/RAM heavy, so one worker process handles
    # one selected-stem job at a time while Redis/Celery queues new requests.
    worker_concurrency=1,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)
