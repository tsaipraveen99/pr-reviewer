import subprocess
import sys


def test_upgrade_head_on_empty_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/m.db")
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "m.db").exists()
