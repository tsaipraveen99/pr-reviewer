# pr-reviewer

**Live demo:** [pr-review-crew.vercel.app](https://pr-review-crew.vercel.app) · **API:** [pr-reviewer-production-ec03.up.railway.app](https://pr-reviewer-production-ec03.up.railway.app/healthz)

pr-reviewer reviews a public GitHub pull request with a small crew of LLM agents instead of one: four specialists read the diff in parallel, an adversarial verifier rejects anything they can't back up with a real quote from the diff, and a synthesizer turns the survivors into one report. A React frontend streams the whole run live, agent by agent, over SSE.

<!-- screenshot: added after deploy -->

## Architecture

pr-reviewer runs the same agent crew through two front doors: a **web demo**
(paste a PR URL, watch the run stream live) and a **GitHub App** that reviews
pull requests automatically with whole-repository context.

```mermaid
flowchart TB
    subgraph web["Web demo (Vercel + FastAPI)"]
        URL([PR URL]) --> API[FastAPI + SSE]
    end
    subgraph app["GitHub App (Celery worker)"]
        WH([PR webhook]) --> VER[verify signature] --> Q[(Redis queue)]
        Q --> CLONE[shallow clone PR head]
        CLONE --> IDX[tree-sitter index → Postgres graph]
        IDX --> SLICE[context slice: changed symbols + callers/callees/importers]
    end
    API --> CREW
    SLICE --> CREW
    subgraph CREW["LangGraph crew"]
        direction TB
        INTENT["intent (Sonnet tool loop:<br/>graph_neighbors · read_file · grep)"]
        C[correctness] & T[tests] & S[security]
        INTENT --> V[adversarial verifier]
        C --> V
        T --> V
        S --> V
        V --> SYN[synthesizer]
    end
    SYN --> OUT1([live SSE stream + permalink])
    SYN --> OUT2([GitHub Review: inline intent comments,<br/>collapsed crew report, cost footer + neutral check])
```

**The intent agent is the headline.** On the bot path it is not a one-shot
prompt: it is a bounded tool-use loop on Claude Sonnet that explores the
repository before judging whether the diff does what the PR description
claims. It queries a code graph (`graph_neighbors`: who calls this symbol),
reads exact file ranges, and greps the clone — all read-only, sandboxed to
the checkout, capped at 10 tool calls and a token budget, with a prompt-cache
breakpoint on the stable prefix. Divergences between the description and the
change land as inline comments on the exact changed lines.

**The code graph** is `packages/graph` (`prgraph`): a tree-sitter indexer for
Python/JS/TS that incrementally stores files, symbols, and call/import edges
in Postgres, plus a `context_slice` query that assembles the changed symbols
and their 1-hop neighborhood into a bounded prompt section every specialist
sees. The same tables serve the intent agent's `graph_neighbors` tool.

**Reliability shape:** reviews are idempotent per (repo, PR, head sha); a new
push supersedes the in-flight review of the old sha; the check run and review
row are created only after a successful clone so retries genuinely retry; and
every failure path completes the Check Run (always `neutral` — the bot
informs, it never blocks a merge).

## Why the verifier exists

Four independent LLM calls produce four independent hallucination surfaces. The **verifier** node (`apps/api/src/prcrew/graph/verifier.py`) is a fifth, adversarial LLM call that re-reads the diff against every numbered finding and rejects it if the quoted evidence doesn't actually appear in the diff, misreads the code, or describes something the diff didn't touch. It defaults to rejecting when uncertain, and if the verifier call itself fails, findings pass through unverified rather than silently vanishing. Only confirmed findings reach the synthesizer — this is the difference between "an agent said so" and "an agent said so and a second agent checked."

## Local development

**Backend** (from `apps/api`):

```bash
uv sync --all-extras --dev
ANTHROPIC_API_KEY=... GITHUB_TOKEN=... uv run uvicorn 'prcrew.api.app:create_app' --factory --port 8000
```

Required env vars:
- `ANTHROPIC_API_KEY` — Claude API key
- `GITHUB_TOKEN` — GitHub token for fetching PR diffs/issues

Optional env vars (see `apps/api/src/prcrew/settings.py`):
- `SPECIALIST_MODEL` (default `claude-haiku-4-5-20251001`)
- `SYNTH_MODEL` (default `claude-sonnet-5`)
- `DAILY_RATE_LIMIT` (default `5/day`)
- `CORS_ORIGINS` (default `*`)

**Running the full stack locally** (adds Postgres + Redis + the Celery worker instead of the SQLite-file default):

```bash
# from repo root — starts Postgres (5432) and Redis (6379)
docker compose up -d

# from apps/api — point the app at the compose Postgres/Redis instead of the SQLite default
export DATABASE_URL=postgresql+psycopg://prcrew:prcrew@localhost:5432/prcrew
export REDIS_URL=redis://localhost:6379/0

uv run alembic upgrade head
ANTHROPIC_API_KEY=... GITHUB_TOKEN=... uv run uvicorn 'prcrew.api.app:create_app' --factory --port 8000

# in a second terminal, same apps/api env vars
uv run celery -A prcrew.worker.celery_app.app worker --loglevel=info
```

`docker compose down` tears the stack down (add `-v` to also drop the `pgdata` volume).

**Frontend** (from `apps/web`):

```bash
npm install
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

**Showcase generation** (owner-run, records a real review as a replayable showcase — needs real API keys):

```bash
uv run python scripts/generate_showcase.py <pr_url> <slug> "<title>"
```

## Demo cost controls

This is a public demo backed by paid LLM calls, so it's guarded on several axes:

- **Per-IP rate limit** — 5 review requests per day by default (`DAILY_RATE_LIMIT`), enforced with `slowapi` in `apps/api/src/prcrew/api/app.py`
- **Size guards** — PRs over 20 changed files or 500 changed lines are rejected before any LLM call (`MAX_FILES`, `MAX_LINES` in `apps/api/src/prcrew/github/client.py`)
- **Public repos only** — private repos are rejected at the GitHub-fetch step
- **Haiku for live runs** — specialists default to `claude-haiku-4-5-20251001`; only the synthesizer uses a larger model
- **Showcase replays cost zero** — the showcase gallery replays precomputed event streams from disk (`apps/api/src/prcrew/showcases/store.py`); no LLM calls happen on replay

Bot-path guards (GitHub App):

- **Size guards** — PRs over 40 files / 1,500 changed lines are skipped with a neutral check explaining why (`MAX_PR_FILES`, `MAX_PR_LINES`)
- **Daily cap** — 20 reviews per repo per day (`DAILY_REPO_CAP`)
- **Intent-loop budget** — ≤10 tool calls, 8,192 output tokens per call, cumulative input-token budget (`INTENT_TOKEN_BUDGET`), prompt caching on the stable prefix
- **Kill switch** — `REVIEWS_ENABLED=false` stops all bot reviews instantly
- **Installation allowlist** — only allowlisted installation ids are reviewed, even if the App is somehow installed elsewhere

## Testing

```bash
# backend, from apps/api
uv run pytest

# frontend, from apps/web
npm test
```

CI (`.github/workflows/ci.yml`) runs `ruff check` + `pytest` for the backend and `tsc -b --noEmit` + `vitest` for the frontend on every push and PR to `main`.
