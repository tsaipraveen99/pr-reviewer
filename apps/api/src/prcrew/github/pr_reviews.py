"""Compose and post the GitHub Review for a bot run."""

import re

from prcrew.diffs import ChangedFile, line_is_changed
from prcrew.github.app_client import AppClient
from prcrew.github.client import GitHubError
from prcrew.models import VerifiedFinding


def _safe(text: str, limit: int) -> str:
    """LLM-derived text goes into markdown we author: escape angle brackets so
    planted tags (a PR can steer what the model quotes) cannot break the
    <details> structure or make the bot 'say' arbitrary HTML, and cap the
    length."""
    escaped = text.replace("<", "&lt;").replace(">", "&gt;")
    return escaped if len(escaped) <= limit else escaped[: limit - 1] + "…"


def build_inline_comments(confirmed: list[VerifiedFinding],
                          files: list[ChangedFile]) -> tuple[list[dict], list[VerifiedFinding]]:
    comments, unmapped = [], []
    for f in confirmed:
        if (f.agent == "intent" and f.line is not None
                and line_is_changed(files, f.file, f.line)):
            comments.append({"path": f.file, "line": f.line, "side": "RIGHT",
                             "body": f"**intent · {f.severity}** — {_safe(f.claim, 400)}"
                                     f"\n\n{_safe(f.evidence, 600)}"})
        else:
            unmapped.append(f)
    return comments, unmapped


_DETAILS_CLOSE = re.compile(r"</details", re.IGNORECASE)


def _finding_line(f: VerifiedFinding) -> str:
    loc = f"{f.file}:{f.line}" if f.line is not None else f.file
    return f"- **{f.severity}** ({f.agent}) `{_safe(loc, 200)}` — {_safe(f.claim, 400)}"


def compose_body(intent_confirmed: list[VerifiedFinding],
                 unmapped: list[VerifiedFinding], review_md: str, usage: dict) -> str:
    if intent_confirmed:
        verdict = (f"### Intent check: {len(intent_confirmed)} divergence(s) between "
                   "the description and the change\n"
                   + "\n".join(_finding_line(f) for f in intent_confirmed))
    else:
        verdict = "### Intent check: the change matches its description"
    extra = ("\n\nOther confirmed findings:\n"
             + "\n".join(_finding_line(f) for f in unmapped)) if unmapped else ""
    total = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    footer = f"\n\n---\ncost: ${usage.get('cost_usd', 0):.3f} · {total:,} tokens"
    # The synthesizer's markdown must keep its formatting, so it is NOT run
    # through _safe -- but a planted closing tag (a PR can steer what the
    # model writes) would pop our collapse block. Neutralize just that.
    review_md = _DETAILS_CLOSE.sub("&lt;/details", review_md)
    return (f"{verdict}{extra}\n\n<details><summary>Full crew review</summary>\n\n"
            f"{review_md}\n\n</details>{footer}")


def post_review(client: AppClient, installation_id: int, owner: str, repo: str,
                number: int, body: str, comments: list[dict]) -> int:
    path = f"/repos/{owner}/{repo}/pulls/{number}/reviews"
    body = body[:60000]
    payload = {"event": "COMMENT", "body": body, "comments": comments}
    try:
        return client.request(installation_id, "POST", path, json_body=payload).json()["id"]
    except GitHubError as e:
        if e.status != 422 or not comments:
            raise
        orphans = "\n".join(f"- `{c['path']}:{c['line']}` {c['body']}" for c in comments)
        fallback_body = f"{body}\n\nInline placement unavailable:\n{orphans}"[:60000]
        fallback = {"event": "COMMENT", "comments": [], "body": fallback_body}
        return client.request(installation_id, "POST", path, json_body=fallback).json()["id"]
