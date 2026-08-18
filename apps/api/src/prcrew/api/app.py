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


def create_app(run_manager=None, github=None, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = None
    if run_manager is None:
        from prcrew.api.review_store import ReviewStore
        from prcrew.api.runs import RunManager
        from prcrew.db import make_engine, make_session_factory
        from prcrew.graph.build import build_graph
        from prcrew.llm import AgentLLM
        engine = make_engine(settings.database_url)
        run_manager = RunManager(
            graph=build_graph(AgentLLM(settings.specialist_model), AgentLLM(settings.synth_model)),
            store=ReviewStore(make_session_factory(engine)))
    if github is None:
        from prcrew.github.client import GitHubClient
        github = GitHubClient(token=settings.github_token)

    lifespan = None
    if engine is not None and settings.database_url.startswith("sqlite"):
        # Local-dev convenience only: production schema is owned by alembic
        # migrations. Best-effort so `uv run uvicorn` just works out of the box.
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            from prcrew.db import Base
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            yield

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
    return app
