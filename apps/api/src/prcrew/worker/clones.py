"""Shallow clone/fetch of a PR head into a local workspace via the git CLI."""

import subprocess
from pathlib import Path


class CloneError(Exception):
    pass


def _git(args: list[str], cwd: Path, token: str | None) -> None:
    try:
        subprocess.run(["git", *args], cwd=cwd, check=True,
                       capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired as e:
        raise CloneError(f"git {args[0]} timed out") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "")[-500:]
        if token:
            detail = detail.replace(token, "***")
        raise CloneError(f"git {args[0]} failed: {detail}") from e


def ensure_clone(clone_url: str, dest: Path, pr_number: int, head_sha: str,
                 token: str | None = None) -> None:
    """Make `dest` a checkout of `head_sha`, creating or reusing the clone.

    Fetches GitHub's refs/pull/{n}/head, which exists for same-repo and
    fork PRs alike. The remote URL (which may embed a token) is passed per
    command, never written to .git/config.
    """
    if not (dest / ".git").is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        _git(["init", "-q"], dest, token)
    _git(["fetch", "--depth", "50", clone_url,
          f"refs/pull/{pr_number}/head"], dest, token)
    _git(["-c", "advice.detachedHead=false", "checkout", "-q", head_sha], dest, token)
