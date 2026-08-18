from prcrew.worker.celery_app import app


@app.task(name="prcrew.ping")
def ping() -> str:
    return "pong"
