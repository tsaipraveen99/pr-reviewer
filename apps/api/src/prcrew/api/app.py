from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from prcrew.settings import Settings


def client_ip(request: Request) -> str:
    """Rate-limit key that survives a trusted edge proxy (e.g. Railway).

    The RIGHTMOST X-Forwarded-For entry is the one appended by the trusted
    edge; entries further left are client-spoofable. Without the header,
    fall back to the socket peer address.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "127.0.0.1"


def create_app(run_manager=None, github=None, settings: Settings | None = None,
               webhook_router=None) -> FastAPI:
    settings = settings or Settings()
    engine = None
    if run_manager is None:
        from prcrew import db
        from prcrew.api.review_store import ReviewStore
        from prcrew.api.runs import RunManager
        from prcrew.graph.build import build_graph
        from prcrew.llm import AgentLLM
        engine = db.make_engine(settings.database_url)
        run_manager = RunManager(
            graph=build_graph(AgentLLM(settings.specialist_model), AgentLLM(settings.synth_model)),
            store=ReviewStore(db.make_session_factory(engine)))
    if github is None:
        from prcrew.github.client import GitHubClient
        github = GitHubClient(token=settings.github_token)

    lifespan = None
    if engine is not None:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            if settings.database_url.startswith("sqlite"):
                # Local-dev convenience only: production schema is owned by
                # alembic migrations.
                from pathlib import Path

                from prcrew.db import Base
                db_path = settings.database_url.rsplit("///", 1)[-1]
                if db_path and not db_path.startswith(":"):
                    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
            yield
            await engine.dispose()

    app = FastAPI(title="pr-crew", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                       allow_methods=["*"], allow_headers=["*"])
    limiter = Limiter(key_func=client_ip)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    from prcrew.api.routes import make_router
    app.include_router(make_router(run_manager, github, limiter, settings.daily_rate_limit))

    if webhook_router is None and engine is not None:
        from prcrew.api.webhook_routes import make_webhook_router
        from prcrew.github.webhooks import RecentDeliveries
        from prcrew.worker.celery_app import app as celery_app
        session_factory = db.make_session_factory(engine)

        def enqueue(kwargs: dict) -> None:
            celery_app.send_task("prcrew.handle_pr_event", kwargs=kwargs)

        webhook_router = make_webhook_router(settings, session_factory, enqueue,
                                             RecentDeliveries())
    if webhook_router is not None:
        app.include_router(webhook_router)
    return app
