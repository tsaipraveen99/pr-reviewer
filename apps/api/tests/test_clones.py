import subprocess
from pathlib import Path

import pytest

from prcrew.worker.clones import CloneError, ensure_clone


def make_origin(tmp_path: Path) -> Path:
    """A local 'origin' repo with a PR ref, like GitHub's refs/pull/N/head."""
    origin = tmp_path / "origin"
    origin.mkdir()
    run = lambda *args: subprocess.run(
        args, cwd=origin, check=True, capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "HOME": str(tmp_path),
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin"})
    run("git", "init", "-b", "main")
    (origin / "app.py").write_text("def f():\n    return 1\n")
    run("git", "add", ".")
    run("git", "commit", "-m", "init")
    run("git", "update-ref", "refs/pull/1/head", "HEAD")
    return origin


def head_sha(origin: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=origin, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_fresh_clone_checks_out_sha(tmp_path):
    origin = make_origin(tmp_path)
    dest = tmp_path / "clone"
    sha = head_sha(origin)
    ensure_clone(f"file://{origin}", dest, ref="refs/pull/1/head", sha=sha)
    assert (dest / "app.py").read_text().startswith("def f")


def test_incremental_fetch_new_sha(tmp_path):
    origin = make_origin(tmp_path)
    dest = tmp_path / "clone"
    ensure_clone(f"file://{origin}", dest, "refs/pull/1/head", head_sha(origin))
    (origin / "app.py").write_text("def f():\n    return 2\n")
    subprocess.run(["git", "commit", "-am", "change"], cwd=origin, check=True,
                   capture_output=True, env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                                             "PATH": "/usr/bin:/bin:/usr/local/bin"})
    subprocess.run(["git", "update-ref", "refs/pull/1/head", "HEAD"], cwd=origin,
                   check=True, capture_output=True)
    ensure_clone(f"file://{origin}", dest, "refs/pull/1/head", head_sha(origin))
    assert "return 2" in (dest / "app.py").read_text()


def test_fetch_branch_ref(tmp_path):
    origin = make_origin(tmp_path)
    dest = tmp_path / "clone"
    ensure_clone(f"file://{origin}", dest, "refs/heads/main", head_sha(origin))
    assert (dest / "app.py").is_file()


def test_clone_error_scrubs_token(tmp_path):
    # Token and URL live in variables so the test's own source lines (echoed
    # in tracebacks) don't contain the literal — the assertion below then
    # genuinely tests the exception-chain path, not the test file itself.
    secret = "SECRET" + "TOKEN"
    url = f"https://x-access-token:{secret}@127.0.0.1:1/none.git"
    with pytest.raises(CloneError) as exc:
        ensure_clone(url, tmp_path / "c", "refs/pull/1/head", "a" * 40, token=secret)
    assert secret not in str(exc.value)
    # The full formatted traceback is what logger.exception prints — the
    # suppressed chain must not resurrect the token via CalledProcessError.cmd.
    import traceback
    chain = "".join(traceback.format_exception(exc.value))
    assert secret not in chain
