import logging
import uuid

from sqlalchemy import select

from prcrew.worker.celery_app import app

logger = logging.getLogger(__name__)

STUB_TITLE = "pr-reviewer connected"
STUB_SUMMARY = (
    "pr-reviewer received this pull request and completed a connectivity "
    "round trip. Intent-vs-execution review lands in the next release.")


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


def _deps():
    """Build real dependencies; tests monkeypatch this function."""
    from prcrew.db import make_sync_session_factory
    from prcrew.github.app_auth import InstallationTokens
    from prcrew.github.checks import CheckRuns
    from prcrew.settings import Settings

    settings = Settings()
    factory = make_sync_session_factory(_cached_engine(settings.database_url))
    checks = CheckRuns(InstallationTokens(settings.github_app_id,
                                          settings.github_app_private_key))
    return factory, checks, settings


@app.task(name="prcrew.handle_pr_event")
def handle_pr_event(installation_id: int, repo_id: int, repo_full_name: str,
                    pr_number: int, head_sha: str) -> str:
    from prcrew.db import Review

    session_factory, checks, settings = _deps()
    if not settings.reviews_enabled:
        return "disabled"
    if installation_id not in settings.allowed_installations():
        return "not_allowed"

    with session_factory() as session:
        existing = session.execute(
            select(Review).where(Review.repo_id == repo_id,
                                 Review.pr_number == pr_number,
                                 Review.head_sha == head_sha,
                                 Review.status != "failed")).scalar_one_or_none()
        if existing is not None:
            return "duplicate"

    owner, repo = repo_full_name.split("/", 1)
    check_run_id = checks.create(installation_id, owner, repo, head_sha)
    try:
        with session_factory() as session:
            session.add(Review(
                id=uuid.uuid4().hex, source="github", repo_id=repo_id,
                pr_number=pr_number, head_sha=head_sha,
                pr_url=f"https://github.com/{repo_full_name}/pull/{pr_number}",
                status="done", check_run_id=check_run_id,
                result_json={"stub": True, "summary": STUB_SUMMARY}))
            session.commit()
        checks.complete(installation_id, owner, repo, check_run_id,
                        "neutral", STUB_TITLE, STUB_SUMMARY)
        return "completed"
    except Exception:
        # Never leave a hanging pending check.
        logger.exception("handle_pr_event failed for repo %s pr %s", repo_id, pr_number)
        _complete_quietly(checks, installation_id, owner, repo, check_run_id, "neutral",
                          "pr-reviewer hit an internal error",
                          "Something went wrong on our side; this PR was not reviewed.")
        return "failed"
