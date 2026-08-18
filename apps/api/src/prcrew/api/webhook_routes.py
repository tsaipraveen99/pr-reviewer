"""GitHub App webhook endpoint: verify, upkeep, enqueue."""

import json
from collections.abc import Callable

from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, func

from prcrew.db import Installation, Repo
from prcrew.github.webhooks import RecentDeliveries, verify_signature
from prcrew.settings import Settings

PR_ACTIONS = {"opened", "synchronize", "reopened"}


def make_webhook_router(settings: Settings, session_factory,
                        enqueue: Callable[[dict], None],
                        deliveries: RecentDeliveries) -> APIRouter:
    router = APIRouter()

    @router.post("/webhooks/github", status_code=202)
    async def github_webhook(request: Request):
        body = await request.body()
        signature = request.headers.get("x-hub-signature-256")
        if not verify_signature(settings.github_webhook_secret, body, signature):
            return Response(status_code=401)
        delivery = request.headers.get("x-github-delivery", "")
        if delivery and deliveries.seen(delivery):
            return {"status": "duplicate"}
        event = request.headers.get("x-github-event", "")
        payload = json.loads(body)

        if event == "pull_request":
            return await _pull_request(payload)
        if event == "installation":
            return await _installation(payload)
        if event == "installation_repositories":
            return await _installation_repositories(payload)
        return {"status": "ignored"}

    async def _pull_request(payload: dict):
        pr = payload.get("pull_request") or {}
        installation_id = (payload.get("installation") or {}).get("id")
        if (payload.get("action") not in PR_ACTIONS
                or pr.get("draft")
                or (pr.get("user") or {}).get("type") == "Bot"
                or installation_id not in settings.allowed_installations()):
            return {"status": "skipped"}
        repo = payload["repository"]
        enqueue({"installation_id": installation_id, "repo_id": repo["id"],
                 "repo_full_name": repo["full_name"], "pr_number": pr["number"],
                 "head_sha": pr["head"]["sha"]})
        return {"status": "queued"}

    async def _installation(payload: dict):
        action = payload.get("action")
        inst = payload["installation"]
        async with session_factory() as session:
            if action == "created":
                await session.merge(Installation(id=inst["id"],
                                                 account_login=inst["account"]["login"]))
                for repo in payload.get("repositories") or []:
                    await session.merge(_repo_row(repo, inst["id"]))
            elif action == "deleted":
                await session.execute(
                    delete(Repo).where(Repo.installation_id == inst["id"]))
                await session.execute(
                    delete(Installation).where(Installation.id == inst["id"]))
            elif action == "suspend":
                row = await session.get(Installation, inst["id"])
                if row:
                    row.suspended_at = func.now()
            elif action == "unsuspend":
                row = await session.get(Installation, inst["id"])
                if row:
                    row.suspended_at = None
            await session.commit()
        return {"status": "ok"}

    async def _installation_repositories(payload: dict):
        inst_id = payload["installation"]["id"]
        async with session_factory() as session:
            for repo in payload.get("repositories_added") or []:
                await session.merge(_repo_row(repo, inst_id))
            removed = [r["id"] for r in payload.get("repositories_removed") or []]
            if removed:
                await session.execute(delete(Repo).where(Repo.id.in_(removed)))
            await session.commit()
        return {"status": "ok"}

    def _repo_row(repo: dict, installation_id: int) -> Repo:
        return Repo(id=repo["id"], installation_id=installation_id,
                    full_name=repo["full_name"],
                    default_branch=repo.get("default_branch", "main"),
                    index_status="pending")

    return router
