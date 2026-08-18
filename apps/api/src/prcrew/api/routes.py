import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from prcrew.api.runs import TERMINAL, RunManager
from prcrew.github.client import GitHubError, PrivateRepoError, PRTooLargeError
from prcrew.github.urls import InvalidPRUrl, parse_pr_url


class ReviewRequest(BaseModel):
    pr_url: str

def make_router(run_manager: RunManager, github, limiter, limit_str: str) -> APIRouter:
    router = APIRouter()

    @router.post("/reviews", status_code=202)
    @limiter.limit(limit_str)
    async def create_review(request: Request, body: ReviewRequest):
        try:
            owner, repo, number = parse_pr_url(body.pr_url)
        except InvalidPRUrl as e:
            raise HTTPException(400, str(e))
        try:
            ctx = await github.fetch_pr(owner, repo, number)
        except PrivateRepoError as e:
            raise HTTPException(403, str(e))
        except PRTooLargeError as e:
            raise HTTPException(413, str(e))
        except GitHubError as e:
            raise HTTPException(502, f"GitHub API error: {e.detail}")
        return {"run_id": await run_manager.start(ctx)}

    @router.get("/reviews/{run_id}")
    async def get_review(run_id: str):
        run = run_manager.get(run_id)
        if not run:
            raise HTTPException(404, "Unknown run")
        return {"status": run.status, "result": run.result}

    @router.get("/reviews/{run_id}/stream")
    async def stream_review(run_id: str):
        run = run_manager.get(run_id)
        if not run:
            raise HTTPException(404, "Unknown run")

        async def gen():
            idx = 0
            while True:
                while idx < len(run.events):
                    ev = run.events[idx]; idx += 1
                    yield {"event": ev["type"], "data": json.dumps(ev)}
                    if ev["type"] in TERMINAL:
                        return
                if run.status != "running" and idx >= len(run.events):
                    return
                # `run.events` is written from RunManager's dedicated
                # background loop (see RunManager docstring), so we poll it
                # rather than block on `run.queue`, which would be awaited
                # here on a different event loop than the one that would
                # write it.
                await asyncio.sleep(0.02)
        return EventSourceResponse(gen())

    return router
