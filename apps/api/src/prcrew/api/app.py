from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from prcrew.settings import Settings


def create_app(run_manager=None, github=None, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if run_manager is None:
        from prcrew.api.runs import RunManager
        from prcrew.graph.build import build_graph
        from prcrew.llm import AgentLLM
        run_manager = RunManager(graph=build_graph(
            AgentLLM(settings.specialist_model), AgentLLM(settings.synth_model)))
    if github is None:
        from prcrew.github.client import GitHubClient
        github = GitHubClient(token=settings.github_token)

    app = FastAPI(title="pr-crew")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                       allow_methods=["*"], allow_headers=["*"])
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    from prcrew.api.routes import make_router
    app.include_router(make_router(run_manager, github, limiter, settings.daily_rate_limit))
    return app
