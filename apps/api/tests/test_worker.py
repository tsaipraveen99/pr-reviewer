from prcrew.settings import Settings
from prcrew.worker import tasks
from prcrew.worker.celery_app import make_celery


def test_make_celery_config():
    app = make_celery(Settings())
    assert app.conf.task_acks_late is True
    assert app.conf.broker_url.startswith("redis://")


def test_ping_eager():
    app = make_celery(Settings())
    app.conf.task_always_eager = True
    assert tasks.ping.apply().get() == "pong"
