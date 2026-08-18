from celery import Celery

from prcrew.settings import Settings


def make_celery(settings: Settings) -> Celery:
    app = Celery("prcrew", broker=settings.redis_url, backend=settings.redis_url,
                 include=["prcrew.worker.tasks"])
    app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1,
                    task_serializer="json", result_serializer="json",
                    accept_content=["json"])
    return app


app = make_celery(Settings())
