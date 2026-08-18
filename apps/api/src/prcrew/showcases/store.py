import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

def list_showcases() -> list[dict]:
    out = []
    for path in sorted(DATA_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        out.append({k: data[k] for k in ("slug", "title", "pr_url")})
    return out

def get_showcase(slug: str) -> dict | None:
    path = DATA_DIR / f"{slug}.json"
    if not path.is_file() or path.parent != DATA_DIR:
        return None
    return json.loads(path.read_text())
