"""Compose and post the GitHub Review for a bot run."""

from prcrew.diffs import ChangedFile, line_is_changed
from prcrew.github.app_client import AppClient
from prcrew.github.client import GitHubError
from prcrew.models import VerifiedFinding


def build_inline_comments(confirmed: list[VerifiedFinding],
                          files: list[ChangedFile]) -> tuple[list[dict], list[VerifiedFinding]]:
    comments, unmapped = [], []
    for f in confirmed:
        if (f.agent == "intent" and f.line is not None
                and line_is_changed(files, f.file, f.line)):
            comments.append({"path": f.file, "line": f.line, "side": "RIGHT",
                             "body": f"**intent · {f.severity}** — {f.claim}\n\n{f.evidence}"})
        else:
            unmapped.append(f)
    return comments, unmapped


def _finding_line(f: VerifiedFinding) -> str:
    loc = f"{f.file}:{f.line}" if f.line is not None else f.file
    return f"- **{f.severity}** ({f.agent}) `{loc}` — {f.claim}"


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
    return (f"{verdict}{extra}\n\n<details><summary>Full crew review</summary>\n\n"
            f"{review_md}\n\n</details>{footer}")


def post_review(client: AppClient, installation_id: int, owner: str, repo: str,
                number: int, body: str, comments: list[dict]) -> int:
    path = f"/repos/{owner}/{repo}/pulls/{number}/reviews"
    payload = {"event": "COMMENT", "body": body, "comments": comments}
    try:
        return client.request(installation_id, "POST", path, json_body=payload).json()["id"]
    except GitHubError as e:
        if e.status != 422 or not comments:
            raise
        orphans = "\n".join(f"- `{c['path']}:{c['line']}` {c['body']}" for c in comments)
        fallback = {"event": "COMMENT", "comments": [],
                    "body": f"{body}\n\nInline placement unavailable:\n{orphans}"}
        return client.request(installation_id, "POST", path, json_body=fallback).json()["id"]
