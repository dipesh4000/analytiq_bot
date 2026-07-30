# Analytiq Bot

Analytiq is a Telegram data-analysis agent built for the IIT Madras TDS project. It
answers questions over inline data and public datasets, then returns exactly one JSON
object:

```json
{"answer":{"state":"Assam"},"log_url":"https://your-host/logs/<run_id>.jsonl"}
```

The `answer` value follows the shape requested in the latest Telegram message. The
`log_url` is an unauthenticated JSONL trace containing one JSON object per line.

## What is implemented

- Single-turn and short multi-turn Telegram conversations
- Production Telegram webhook and local polling modes
- OpenRouter's zero-cost model router or explicit `:free` model fallbacks
- Tavily public-web discovery
- SSRF-protected public URL fetching
- CSV, TSV, JSON, Excel, HTML-table, and text-PDF extraction
- Safe arithmetic/statistics and read-only DuckDB queries
- Exact top-level JSON validation and serialization
- SQLite locally or Supabase PostgreSQL in production
- Persistent sessions, Telegram update deduplication, and JSONL logs
- Public log, liveness, and readiness HTTP routes
- Docker and Railway deployment configuration

## Architecture

```text
Telegram -> webhook -> per-chat session/lock -> free-model agent
                                            -> search/fetch/extract
                                            -> calculator/DuckDB
         <- exact JSON reply <- validated answer <- public JSONL log

GET /healthz
GET /readyz
GET /logs/<run_id>.jsonl
```

Before the model runs, a zero-token router selects exactly one specialist:

- `dataset_analyst` for structured data embedded in the message
- `search_analyst` for public URLs, MOSPI, and other public-data questions
- `general_analyst` only for ambiguous or mixed questions

Exact greetings are answered without an LLM request. Specialists receive only their
relevant tools, use bounded tool-call budgets, and cache repeated tool calls. The bot
does not run the search and dataset specialists together because that would consume
more free-model quota and increase latency.

While an analysis is running, the bot refreshes Telegram's non-message `typing` status
every four seconds. It stops the status before sending the single required JSON reply.

The model produces only the inner `answer` value. Application code constructs the outer
object and injects the immutable log URL, so the model cannot omit or modify it.

## Requirements

- Python 3.11-3.13
- A Telegram token from BotFather
- An OpenRouter API key
- A Tavily API key

Only free OpenRouter models are accepted. `LLM_MODELS` entries must be
`openrouter/free` or end in `:free`. The default is `openrouter/free`, which selects
an available zero-cost model that supports the requested features.

## Local setup

```bash
cp .env.example .env
uv sync
uv run python main.py
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
uv sync
uv run python main.py
```

Set these values in `.env`:

```dotenv
BOT_API_KEY=<BotFather token>
OPENROUTER_API_KEY=<OpenRouter key>
TAVILY_API_KEY=<Tavily key>
LLM_MODELS=openrouter/free
BOT_MODE=polling
PUBLIC_BASE_URL=http://localhost:8000
TELEGRAM_WEBHOOK_SECRET=<random letters, numbers, underscores, or dashes>
```

Polling is intended only for local development. Local log URLs are not public.

## Render + Supabase production deployment

The repository includes `render.yaml` and a Dockerfile. Production uses Supabase
PostgreSQL because Render Free has an ephemeral filesystem.

1. In Supabase, open the project and click **Connect**.
2. Select **Session pooler** and copy the port `5432` connection string. Replace its
   password placeholder with the database password. If the password contains reserved
   URL characters, URL-encode it.
3. Push this repository to its public GitHub repository.
4. In Render, choose **New > Blueprint**, connect the repository, and select
   `render.yaml`.
5. Enter the prompted secret values:

```dotenv
BOT_API_KEY=<BotFather token>
OPENROUTER_API_KEY=<OpenRouter key>
TAVILY_API_KEY=<Tavily key>
TELEGRAM_WEBHOOK_SECRET=<letters-digits-underscore-dash only>
DATABASE_URL=postgresql://postgres.<project-ref>:<encoded-password>@<region>.pooler.supabase.com:5432/postgres
```

Render supplies `RENDER_EXTERNAL_URL`, so `PUBLIC_BASE_URL` is discovered automatically.
The application creates its three PostgreSQL tables on startup. `render.yaml` selects
webhook mode, the free model router, one concurrent analysis, Singapore, and `/healthz`
as the health check.

6. After the deploy is live, open:

```text
https://<your-render-service>.onrender.com/healthz
https://<your-render-service>.onrender.com/readyz
```

7. Verify Telegram from your private terminal:

```bash
curl -fsS "https://api.telegram.org/bot${BOT_API_KEY}/getWebhookInfo"
```

The returned webhook URL should start with the Render URL and its status should not
contain `last_error_message`.

8. Send the bot a data-analysis question. Copy `log_url` from its JSON reply and confirm
that it downloads publicly.

### Railway alternative

The repository includes a `Dockerfile` and `railway.toml`.

1. Create a Railway project from this public GitHub repository.
2. Add a persistent volume mounted at `/data`.
3. Generate a public Railway domain.
4. Configure:

```dotenv
BOT_MODE=webhook
PUBLIC_BASE_URL=https://<your-domain>
DATA_DIR=/data
BOT_API_KEY=<secret>
OPENROUTER_API_KEY=<secret>
TAVILY_API_KEY=<secret>
LLM_MODELS=openrouter/free
TELEGRAM_WEBHOOK_SECRET=<long-random-value>
SESSION_TTL_SECONDS=900
MAX_AGENT_STEPS=8
AGENT_TIMEOUT_SECONDS=180
MAX_CONCURRENT_RUNS=3
PORT=8000
```

5. Deploy. At startup the application registers:

```text
https://<your-domain>/telegram/<TELEGRAM_WEBHOOK_SECRET>
```

The same secret is supplied to Telegram as its webhook secret token and checked on each
request. Do not expose it in the repository.

6. Verify:

```bash
curl -fsS https://<your-domain>/healthz
curl -fsS "https://api.telegram.org/bot${BOT_API_KEY}/getWebhookInfo"
```

The second command contains a secret; run it only in your own terminal and do not paste
its full output into public logs.

### Persistent logs

SQLite is stored below `DATA_DIR`. A persistent Railway volume is required so public log
URLs remain valid after a restart. Do not deploy multiple replicas against the same
SQLite file.

## Agent behavior

The agent receives a bounded recent conversation and can:

- search for authoritative sources;
- download a selected public source;
- extract tables or text;
- load inline CSV, TSV, or JSON;
- query one extracted table with safe read-only SQL;
- perform deterministic arithmetic and statistics;
- submit a JSON answer value.

Fetched pages and datasets are treated as untrusted data, not instructions. Private,
loopback, link-local, and metadata-service URLs are blocked. Model-generated Python is
never executed.

If all configured free models or tools fail, the bot still sends one valid JSON object:

```json
{"answer":{"error":"analysis_failed"},"log_url":"https://.../logs/<run_id>.jsonl"}
```

This preserves the response contract and makes the failure reviewable, though it will
not receive correctness credit.

## Tests

```bash
uv run ruff check .
uv run pytest
```

The suite covers free-model configuration, exact JSON output, session persistence,
update deduplication, secret redaction, safe calculations, inline table analysis,
private URL rejection, and end-to-end service wrapping.

For live grading rehearsal, clone the published grader separately:

```text
https://github.com/Jivraj-18/tds-p1-t2-2026-telegram-bot
```

Use a one-row `students.csv`:

```csv
email,github_url,telegram_bot_username
you@example.com,https://github.com/dipesh4000/analytiq_bot,analytiq_iitm_bot
```

The supplied assignment requires the two-key `answer`/`log_url` wrapper. At the time of
implementation, the public grader's placeholder example still exact-matched a bare
answer object. Re-check the latest grader revision before final submission and test with
the exact assignment message.

## Public registration

```text
https://github.com/dipesh4000/analytiq_bot, analytiq_iitm_bot
```

## Security notes

- Never commit `.env`, the SQLite database, grader `key.json`, or Telegram session files.
- Rotate any credential that was ever pasted into a tracked file or public log.
- Run one production bot replica when using SQLite.
- Free inference is capacity-limited. Configure multiple explicit `:free` IDs in
  `LLM_MODELS` if you want deterministic fallback order.
- The public JSONL log intentionally contains grading questions and compact evidence,
  but never API keys, authorization headers, or private chain-of-thought.

## License

MIT
