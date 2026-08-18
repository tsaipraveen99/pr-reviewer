"""Record a real review run as a showcase. Owner-only; needs real keys.

Usage: uv run python scripts/generate_showcase.py <pr_url> <slug> "<title>"
"""
import asyncio
import datetime
import json
import sys
import time
from pathlib import Path
from prcrew.github.client import GitHubClient
from prcrew.github.urls import parse_pr_url
from prcrew.graph.build import build_graph
from prcrew.llm import AgentLLM
from prcrew.settings import Settings

async def main(pr_url: str, slug: str, title: str) -> None:
    settings = Settings()
    ctx = await GitHubClient(settings.github_token).fetch_pr(*parse_pr_url(pr_url))
    events, start, seq = [], time.monotonic(), 0

    async def emit(ev):
        nonlocal seq
        seq += 1
        ms = int((time.monotonic() - start) * 1000)
        events.append({**ev, "seq": seq, "at_ms": ms})

    specialist = AgentLLM(settings.specialist_model)
    synth = AgentLLM(settings.synth_model)
    graph = build_graph(specialist, synth)
    result = await graph.ainvoke({"pr_context": ctx}, {"configurable": {"emit": emit}})
    out = {"slug": slug, "title": title, "pr_url": pr_url,
           "recorded_at": datetime.datetime.now(datetime.UTC).isoformat(),
           "events": events, "review": result["review"]}
    path = Path(__file__).parent.parent / "src/prcrew/showcases/data" / f"{slug}.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"wrote {path} ({len(events)} events)")

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
