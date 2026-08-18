from prcrew.settings import Settings
from prcrew.worker import tasks
from prcrew.worker.celery_app import app, make_celery


def test_make_celery_config():
    config_app = make_celery(Settings())
    assert config_app.conf.task_acks_late is True
    assert config_app.conf.broker_url.startswith("redis://")


def test_ping_eager():
    # Set eager mode on the module-level app that tasks.ping is bound to
    prior_eager = app.conf.task_always_eager
    try:
        app.conf.task_always_eager = True
        # Use delay() to route through eager mode (not apply())
        assert tasks.ping.delay().get() == "pong"
    finally:
        app.conf.task_always_eager = prior_eager
