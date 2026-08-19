import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from celery.exceptions import Retry
from sqlalchemy import delete, func, select, update

from prcrew.worker.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="prcrew.ping")
def ping() -> str:
    return "pong"


_ENGINES: dict[str, object] = {}


def _cached_engine(url: str):
    """One sync engine per DATABASE_URL for the life of the worker process
    (a fresh engine per task invocation leaks connections)."""
    if url not in _ENGINES:
        from prcrew.db import make_sync_engine
        _ENGINES[url] = make_sync_engine(url)
    return _ENGINES[url]


def _complete_quietly(checks, installation_id: int, owner: str, repo: str,
                      check_run_id: int, conclusion: str, title: str, summary: str) -> None:
    """Complete the check run, swallowing errors: a completion failure must
    never mask the original failure or crash the task."""
    try:
        checks.complete(installation_id, owner, repo, check_run_id, conclusion, title, summary)
    except Exception:
        logger.exception("failed to complete check run %s", check_run_id)


@dataclass
class Deps:
    session_factory: object
    checks: object
    app_client: object
    tokens: object
    settings: object


def _deps() -> Deps:
    """Build real dependencies; tests monkeypatch this function."""
    from prcrew.db import make_sync_session_factory
    from prcrew.github.app_auth import InstallationTokens
    from prcrew.github.app_client import AppClient
    from prcrew.github.checks import CheckRuns
    from prcrew.settings import Settings

    settings = Settings()
    factory = make_sync_session_factory(_cached_engine(settings.database_url))
    tokens = InstallationTokens(settings.github_app_id, settings.github_app_private_key)
    client = AppClient(tokens)
    return Deps(factory, CheckRuns(tokens), client, tokens, settings)


def _run_crew(ctx, slice_text: str, toolbelt, settings) -> tuple[dict, list[dict]]:
    """Run the bot graph; returns (web-shaped result, seq-stamped events)."""
    from prcrew.graph.build import build_graph
    from prcrew.graph.intent_loop import make_intent_agent
    from prcrew.llm import AgentLLM

    graph = build_graph(
        AgentLLM(settings.specialist_model), AgentLLM(settings.synth_model),
        intent_node=make_intent_agent(AgentLLM(settings.intent_model), toolbelt,
                                      token_budget=settings.intent_token_budget))
    events: list[dict] = []
    seq = 0

    async def emit(event: dict) -> None:
        nonlocal seq
        seq += 1
        events.append({**event, "seq": seq})

    async def run():
        return await graph.ainvoke(
            {"pr_context": ctx, "graph_slice": slice_text},
            {"configurable": {"emit": emit}})

    out = asyncio.run(run())
    usage_list = out.get("usage", [])
    result = {
        "review": out.get("review", ""),
        "verified": [v.model_dump() for v in out.get("verified", [])],
        "usage": {
            "input_tokens": sum(u.input_tokens for u in usage_list),
            "output_tokens": sum(u.output_tokens for u in usage_list),
            "cost_usd": round(sum(u.cost_usd for u in usage_list
                                  if u.cost_usd is not None), 6),
        },
    }
    events.append({"type": "done", "seq": seq + 1})
    return result, events


@app.task(name="prcrew.handle_pr_event", bind=True, max_retries=2)
def handle_pr_event(self, installation_id: int, repo_id: int, repo_full_name: str,
                    pr_number: int, head_sha: str) -> str:
    from prcrew.db import Review
    from prcrew.diffs import changed_ranges
    from prcrew.github.pr_data import fetch_pr
    from prcrew.github.pr_reviews import (
        build_inline_comments,
        compose_body,
        post_review,
    )
    from prcrew.graph.intent_tools import ToolBelt, render_slice
    from prcrew.worker.clones import CloneError, ensure_clone
    from prcrew.worker.indexing import build_slice, ensure_index

    deps = _deps()
    settings = deps.settings
    if not settings.reviews_enabled:
        return "disabled"
    if installation_id not in settings.allowed_installations():
        return "not_allowed"

    with deps.session_factory() as session:
        existing = session.execute(
            select(Review).where(Review.repo_id == repo_id,
                                 Review.pr_number == pr_number,
                                 Review.head_sha == head_sha,
                                 Review.status != "failed")).scalar_one_or_none()
        if existing is not None:
            return "duplicate"
        # A prior "failed" row for this exact (repo, pr, sha) is terminal and
        # carries no permalink/check-run value once a fresh delivery is
        # retrying the same commit; purge it so the inserts below (made only
        # after a successful clone) can never collide with the unique index
        # on (repo_id, pr_number, head_sha).
        session.execute(
            delete(Review).where(Review.repo_id == repo_id,
                                 Review.pr_number == pr_number,
                                 Review.head_sha == head_sha,
                                 Review.status == "failed"))
        # A newer push supersedes any still-running review of this PR.
        session.execute(
            update(Review).where(Review.repo_id == repo_id,
                                 Review.pr_number == pr_number,
                                 Review.head_sha != head_sha,
                                 Review.status == "running")
            .values(status="superseded"))
        session.commit()

    owner, repo = repo_full_name.split("/", 1)
    from prcrew.github.client import GitHubError
    try:
        ctx, _meta = fetch_pr(deps.app_client, installation_id, owner, repo, pr_number)
    except GitHubError:
        logger.exception("fetch_pr failed for %s#%s", repo_full_name, pr_number)
        try:
            cr = deps.checks.create(installation_id, owner, repo, head_sha)
            _complete_quietly(deps.checks, installation_id, owner, repo, cr, "neutral",
                              "pr-reviewer could not fetch this PR",
                              "pr-reviewer could not fetch this pull request from "
                              "GitHub; it will retry on the next push.")
        except Exception:
            # GitHub fully down: the visibility check itself can't be posted.
            # Nothing was written, so a redelivery retries cleanly.
            logger.exception("could not post fetch-failure check for %s#%s",
                             repo_full_name, pr_number)
        return "failed"

    reason = _ineligible_reason(deps, repo_id, ctx, settings)
    if reason is not None:
        check_run_id = deps.checks.create(installation_id, owner, repo, head_sha)
        _complete_quietly(deps.checks, installation_id, owner, repo, check_run_id,
                          "neutral", "pr-reviewer: skipped", reason)
        with deps.session_factory() as session:
            session.add(Review(id=uuid.uuid4().hex, source="github", repo_id=repo_id,
                               pr_number=pr_number, head_sha=head_sha,
                               pr_url=f"https://github.com/{repo_full_name}/pull/{pr_number}",
                               status="skipped", check_run_id=check_run_id,
                               result_json={"skipped": reason}))
            session.commit()
        return "ineligible"

    # check_run_id/review_id are created only once the clone has actually
    # succeeded (below): creating them earlier means a CloneError -> retry
    # redelivery finds its own "running" row via the idempotency check above
    # and returns "duplicate" forever, leaving the check run stuck
    # in_progress and never actually retrying the clone.
    check_run_id = None
    review_id = None
    try:
        clone_root = Path(settings.clones_dir) / f"{repo_id}-pr{pr_number}"
        token = deps.tokens.token(installation_id)
        clone_url = f"https://x-access-token:{token}@github.com/{repo_full_name}.git"
        try:
            ensure_clone(clone_url, clone_root, f"refs/pull/{pr_number}/head",
                         head_sha, token=token)
        except CloneError as e:
            raise self.retry(exc=e, countdown=30) from e

        check_run_id = deps.checks.create(installation_id, owner, repo, head_sha)
        review_id = uuid.uuid4().hex
        with deps.session_factory() as session:
            session.add(Review(id=review_id, source="github", repo_id=repo_id,
                               pr_number=pr_number, head_sha=head_sha,
                               pr_url=f"https://github.com/{repo_full_name}/pull/{pr_number}",
                               status="running", check_run_id=check_run_id))
            session.commit()

        ensure_index(deps.session_factory, repo_id, clone_root, head_sha)
        if _superseded(deps.session_factory, review_id):
            return _abort_superseded(deps, installation_id, owner, repo,
                                     check_run_id, review_id)

        files = changed_ranges(ctx.diff)
        slice_text = render_slice(
            build_slice(deps.session_factory, repo_id, clone_root, files))
        toolbelt = ToolBelt(root=clone_root, session_factory=deps.session_factory,
                            repo_id=repo_id)
        result, events = _run_crew(ctx, slice_text, toolbelt, settings)
        if _superseded(deps.session_factory, review_id):
            return _abort_superseded(deps, installation_id, owner, repo,
                                     check_run_id, review_id)

        confirmed = [v for v in _as_verified(result) if v.verdict == "confirmed"]
        comments, unmapped_pool = build_inline_comments(confirmed, files)
        intent_confirmed = [v for v in confirmed if v.agent == "intent"]
        # Intent findings (inline or not) are listed in the verdict block via
        # intent_confirmed; the body's "other findings" list is everything else.
        other_findings = [v for v in unmapped_pool if v.agent != "intent"]
        body = compose_body(intent_confirmed, other_findings,
                            result["review"], result["usage"])
        github_review_id = post_review(deps.app_client, installation_id, owner,
                                       repo, pr_number, body, comments)

        with deps.session_factory() as session:
            row = session.get(Review, review_id)
            row.status = "done"
            row.result_json = result
            row.events_json = events
            row.usage_json = result["usage"]
            row.github_review_id = github_review_id
            session.commit()
        n = len(confirmed)
        title = (f"pr-reviewer: {n} confirmed finding(s), "
                 f"{len(intent_confirmed)} on intent") if n else "pr-reviewer: no findings"
        _complete_quietly(deps.checks, installation_id, owner, repo, check_run_id,
                          "neutral", title, body[:60000])
        return "completed"
    except Retry:
        # self.retry() raises celery.exceptions.Retry, which subclasses
        # Exception -- it must escape untouched, or a retryable clone
        # failure would be swallowed by the generic handler below and
        # reported as a permanent failure instead of being requeued.
        raise
    except Exception:
        logger.exception("handle_pr_event failed for repo %s pr %s", repo_id, pr_number)
        # Both guards below are needed because check_run_id/review_id are
        # now only set after a successful clone (see above): a failure
        # before that point (e.g. a clone that exhausts its retries) has
        # neither a check run nor a review row to update.
        if review_id is not None:
            try:
                with deps.session_factory() as session:
                    row = session.get(Review, review_id)
                    if row is not None:
                        row.status = "failed"
                        session.commit()
            except Exception:
                # Best-effort like _complete_quietly: a DB error while
                # recording the failure must not mask the original failure
                # or crash the task.
                logger.exception("failed to mark review %s as failed", review_id)
        if check_run_id is not None:
            _complete_quietly(deps.checks, installation_id, owner, repo, check_run_id,
                              "neutral", "pr-reviewer hit an internal error",
                              "Something went wrong on our side; this PR was not reviewed.")
        return "failed"


@app.task(name="prcrew.refresh_index")
def refresh_index(installation_id: int, repo_id: int, repo_full_name: str,
                  head_sha: str, default_branch: str) -> str:
    """Keep the default-branch index warm after a push. No LLM calls."""
    from prcrew.worker.clones import CloneError, ensure_clone
    from prcrew.worker.indexing import ensure_index

    deps = _deps()
    if installation_id not in deps.settings.allowed_installations():
        return "not_allowed"
    clone_root = Path(deps.settings.clones_dir) / f"{repo_id}-default"
    token = deps.tokens.token(installation_id)
    clone_url = f"https://x-access-token:{token}@github.com/{repo_full_name}.git"
    try:
        ensure_clone(clone_url, clone_root, f"refs/heads/{default_branch}",
                     head_sha, token=token)
    except CloneError:
        logger.exception("refresh_index clone failed for repo %s", repo_id)
        return "failed"
    try:
        ensure_index(deps.session_factory, repo_id, clone_root, head_sha)
    except Exception:
        logger.exception("refresh_index indexing failed for repo %s", repo_id)
        return "failed"
    return "indexed"


def _ineligible_reason(deps, repo_id: int, ctx, settings) -> str | None:
    if ctx.changed_files > settings.max_pr_files or ctx.changed_lines > settings.max_pr_lines:
        return (f"PR too large to review: {ctx.changed_files} files / "
                f"{ctx.changed_lines} lines (limits {settings.max_pr_files} / "
                f"{settings.max_pr_lines}).")
    from prcrew.db import Review
    # Review.created_at is a server-side timestamp (server_default=func.now()).
    # sqlite round-trips DateTime(timezone=True) values as naive UTC (no
    # tzinfo survives the driver), so comparing the column against an aware
    # cutoff can silently misbehave depending on driver/version. Both
    # dialects store the same instant in UTC here, so a single naive
    # UTC-based cutoff compares correctly against either.
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
    with deps.session_factory() as session:
        count = session.execute(
            select(func.count()).select_from(Review).where(
                Review.repo_id == repo_id, Review.source == "github",
                Review.created_at >= since)).scalar_one()
    if count >= settings.daily_repo_cap:
        return f"Daily review cap reached for this repository ({settings.daily_repo_cap}/day)."
    return None


def _superseded(session_factory, review_id: str) -> bool:
    from prcrew.db import Review
    with session_factory() as session:
        row = session.get(Review, review_id)
        return row is not None and row.status == "superseded"


def _abort_superseded(deps, installation_id, owner, repo, check_run_id, review_id) -> str:
    _complete_quietly(deps.checks, installation_id, owner, repo, check_run_id,
                      "neutral", "pr-reviewer: superseded",
                      "A newer push replaced this review.")
    return "superseded"


def _as_verified(result: dict):
    from prcrew.models import VerifiedFinding
    return [VerifiedFinding(**v) for v in result.get("verified", [])]
