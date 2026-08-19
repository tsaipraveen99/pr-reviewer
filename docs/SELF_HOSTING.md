# Self-hosting pr-reviewer

Run the whole thing on your own infrastructure, your own GitHub App, and your
own Anthropic API key. Nothing phones home; every review is billed to the key
you configure.

The stack is three deployables plus two stores:

| Piece | What it is | Needs |
|---|---|---|
| api | FastAPI service: web demo + `/webhooks/github` | public HTTPS URL |
| worker | Celery worker: clones, indexes, reviews, posts | outbound network only |
| web (optional) | The React demo/landing UI | any static host |
| Postgres | reviews, installations, repos, code-graph tables | |
| Redis | Celery broker/backend | |

The api and worker are the **same Docker image** (`apps/api/Dockerfile`,
build context = repo root); `SERVICE_ROLE=worker` switches the role.

## 1. Quick start (local, web demo only)

No GitHub App needed for the paste-a-URL demo path:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # your key
export GITHUB_TOKEN=github_pat_...      # fine-grained PAT, public repo read
docker compose --profile app up --build
# api on http://localhost:8000 — migrations run automatically
cd apps/web && npm install && VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

## 2. Register your own GitHub App

Create one at `github.com/settings/apps/new` (or under an org):

- **Webhook URL**: `https://<your-api-host>/webhooks/github`
- **Webhook secret**: generate one (`openssl rand -hex 32`) and keep it
- **Repository permissions**: Checks **Read and write**, Pull requests
  **Read and write**, Contents **Read-only**, Metadata **Read-only**
- **Subscribe to events** (its own section, easy to miss — with no events
  checked you will receive zero PR webhooks and nothing will ever happen):
  **Pull request** and **Push**
- Where can it be installed: your call

After creating: note the **App ID**, then **generate a private key** (a
`.pem` downloads). Install the app on the repositories you want reviewed,
and note the **installation id** (it's in the URL of the installed app's
settings page, or in any webhook delivery payload).

## 3. Environment variables

Both api and worker unless noted. Only the first block is required.

| Variable | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | your Anthropic key — all review spend lands here |
| `DATABASE_URL` | yes | `postgresql+psycopg://user:pass@host:5432/db` (psycopg v3 serves the async api and sync worker from one URL) |
| `REDIS_URL` | yes | `redis://host:6379/0` |
| `GITHUB_APP_ID` | bot | from step 2 |
| `GITHUB_APP_PRIVATE_KEY` | bot | the full PEM, newlines preserved |
| `GITHUB_WEBHOOK_SECRET` | bot (api only) | from step 2; unset = every webhook rejected (fails closed) |
| `ALLOWED_INSTALLATION_IDS` | bot | comma-separated installation ids that get reviews; empty = nobody (fails closed) |
| `GITHUB_TOKEN` | web demo only (api) | fine-grained PAT with public-repo read, used by the paste-a-URL path |
| `REVIEWS_ENABLED` | no (default true) | kill switch for all bot reviews |
| `SPECIALIST_MODEL` | no (`claude-haiku-4-5-...`) | correctness/tests/security agents |
| `SYNTH_MODEL` / `INTENT_MODEL` | no (`claude-sonnet-5`) | synthesizer / intent tool-loop agent |
| `INTENT_TOKEN_BUDGET` | no (200000) | cumulative uncached-input cap for the intent loop |
| `MAX_PR_FILES` / `MAX_PR_LINES` | no (40 / 1500) | PRs above either are skipped with a polite check |
| `DAILY_REPO_CAP` | no (20) | bot reviews per repo per day |
| `CLONES_DIR` | no (`./data/clones`) | worker scratch space; ephemeral is fine |
| `CELERY_CONCURRENCY` | no (2, worker) | concurrent reviews per worker |
| `CORS_ORIGINS` | no (`*`, api) | lock to your web origin in production |
| `DAILY_RATE_LIMIT` | no (`5/day`, api) | per-IP limit for the public web demo |
| `PORT` | no (8000, api) | |

Typical per-review cost: $0.02 to $0.07 (about $0.01 of Haiku for the
specialists, the rest Sonnet for the intent tool loop and synthesis).
Worst case on a maximum-size PR is bounded around $2 by the caps above.

## 4. Deploy

Any host that runs containers works. The shape that runs the reference
deployment (Railway):

1. Create a project with Postgres and Redis plugins.
2. Two services from this repo (build from GitHub, Dockerfile path
   `apps/api/Dockerfile`, build context repo root). On the second service
   set `SERVICE_ROLE=worker`.
3. Set the env vars from step 3 on both (webhook secret only on the api).
4. Run migrations once: `railway ssh --service <api> -- uv run alembic upgrade head`
   (or `docker compose` runs them automatically; on any host:
   `uv run alembic upgrade head` from `apps/api` against your `DATABASE_URL`).
5. Point the App's webhook URL at `https://<api-domain>/webhooks/github`.

For local bot development, expose your local api to GitHub with
[smee.io](https://smee.io) (set the App's webhook URL to your smee channel
and run `npx smee -u <channel> -t http://localhost:8000/webhooks/github`).

## 5. Verify

Open a small PR on an installed repo. Within about a minute you should see
a `pr-reviewer` check run complete (always `neutral` — the bot never blocks
merges) and a review comment: intent verdict first, inline comments on
changed lines where the description and diff diverge, the full crew report
collapsed, and a cost footer. If nothing appears: check the App's webhook
deliveries tab (401 = wrong secret; 202 + nothing = check
`ALLOWED_INSTALLATION_IDS` and the worker logs).

## Operational notes

- The webhook endpoint fails closed on every misconfiguration (missing
  secret, unlisted installation) rather than spending your money.
- Reviews are idempotent per (repo, PR, head sha); a new push supersedes
  the in-flight review of the old sha; failed attempts retry cleanly on
  redelivery (Advanced tab → Redeliver).
- The code graph lives in Postgres and updates incrementally on every
  reviewed PR and every push to the default branch.
