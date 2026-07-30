# Analytiq Bot — Completion Plan

## Implementation status

Implemented on 2026-07-30. The production code, tests, Docker/Railway artifacts, free-model
guardrails, webhook service, persistent sessions/logs, and data tools described below
are now present. Local verification passes, including a live OpenRouter inline-analysis
run, a live Tavily discovery check, a corrected end-to-end MOSPI answer (`Assam`), and a
read-only Telegram identity check for `@analytiq_iitm_bot`.

Deployment itself remains a user-owned step because the final hosting account, public
domain, persistent volume, and production environment variables live outside this
repository.

## 1. Goal and grading contract

Build and deploy a Telegram data-analysis agent that:

- accepts plain-text questions from a real Telegram user;
- uses earlier messages from the same short conversation when a task is multi-turn;
- answers the latest message;
- solves inline-data and public-dataset questions;
- emits exactly one JSON object with no Markdown or surrounding prose;
- publishes a public, unauthenticated, wget-able JSONL run log;
- remains reachable throughout grading;
- keeps its implementation in the public repository.

Target production response:

```json
{"answer": <JSON value in the requested shape>, "log_url": "https://<host>/logs/<run_id>.jsonl"}
```

The application, rather than the LLM, must create the outer object and serialize it. This prevents the model from omitting or altering `log_url`.

## 2. Current state (2026-07-30)

Verified:

- Public repository: `https://github.com/dipesh4000/analytiq_bot`
- Git remote is reachable without authentication.
- Configured Telegram identity: `@analytiq_iitm_bot`
- The username ends in `bot`.
- The current source compiles with the local Python environment.
- Installed core versions include `python-telegram-bot 22.8` and `pydantic 2.13.4`.
- `.env` is ignored by Git.

Baseline gaps that this implementation addressed:

- `app/agents.py` returns only a placeholder string.
- No LLM client or agent loop exists.
- No search, URL fetch, document parsing, or deterministic analysis tools exist.
- No multi-turn conversation persistence exists.
- No response-schema or exact-JSON enforcement exists.
- No JSONL run logging or public log endpoint exists.
- No health endpoint, webhook server, deployment manifest, persistent storage, or uptime check exists.
- No tests or local grader integration exist.
- The README describes files and behavior that are not present.
- `app/config.py` is empty.
- `main.py` performs synchronous analysis inside an async handler and currently uses polling only.
- Python `>=3.13` unnecessarily narrows deployment options.
- The untracked `.env.example` contains key-like sample strings; replace all values with obvious placeholders and rotate any value if it was ever real.

## 3. Upstream contract discrepancy

The assignment text supplied for this project requires the two-key wrapper:

```json
{"answer": ..., "log_url": "..."}
```

As of 2026-07-30, the public grading repository's checked-in example instead asks for and exact-matches a bare answer object such as:

```json
{"state": "Assam"}
```

The private/final contract should be treated as authoritative, so production will default to the two-key wrapper. Before final submission:

1. pull the latest grader repository;
2. inspect its latest `README.md`, `evals/questions.json`, and `grade.py`;
3. run the exact public pipeline;
4. if the discrepancy remains, preserve the required production wrapper and document the upstream mismatch rather than silently shipping an ambiguous format.

Do not make output depend on undocumented guesses about the grader. The final smoke test must use the exact message from the assignment.

## 4. Recommended architecture

```text
Telegram webhook
    -> update validation and per-chat lock
    -> short-lived conversation store
    -> analysis agent
         -> web search
         -> safe URL fetch
         -> table/document extraction
         -> DuckDB read-only analysis
         -> deterministic calculator/statistics
    -> answer JSON validation
    -> JSONL log persistence
    -> exact JSON serialization
    -> Telegram reply

Public HTTP service
    -> POST /telegram/<secret>
    -> GET  /healthz
    -> GET  /readyz
    -> GET  /logs/<run_id>.jsonl
```

### Key implementation choices

- Use an async FastAPI service and Telegram webhook in production. Return HTTP 200 after accepting the update, then let the Telegram handler send the answer asynchronously.
- Keep polling as a local-development mode only.
- Use the existing OpenRouter credential through an OpenAI-compatible client. Make the model configurable with `LLM_MODEL`; do not hardcode a provider-specific model throughout the codebase.
- Use Tavily for discovery, then fetch the cited source directly. Search snippets are leads, not evidence.
- Use deterministic code for calculations. The LLM plans the analysis and interprets results; it should not mentally calculate large tables.
- Use DuckDB for model-generated `SELECT` queries over loaded tables. Reject mutation, file-write, extension-install, network, and multi-statement SQL.
- Do not execute unrestricted model-generated Python in the bot process.
- Store conversations and logs in SQLite on a mounted persistent volume for the first production version. Serve logs through the same HTTPS app. If the chosen host cannot guarantee a persistent volume, use an S3-compatible object store instead.
- Add a per-chat lock plus a small global semaphore so simultaneous updates do not reorder messages or exhaust model/API quotas.

## 5. Target project structure

```text
.
├── app/
│   ├── agent.py              # bounded tool-calling loop
│   ├── config.py             # validated environment settings
│   ├── contracts.py          # Pydantic input/output/event models
│   ├── telegram_app.py       # handlers and exact reply logic
│   ├── web.py                # webhook, health, and public log routes
│   ├── sessions.py           # TTL conversation persistence
│   ├── logging_store.py      # JSONL event writer/reader
│   ├── llm.py                # provider client and retry policy
│   └── tools/
│       ├── search.py
│       ├── fetch.py
│       ├── extract.py
│       ├── sql.py
│       └── calculate.py
├── tests/
│   ├── fixtures/
│   ├── test_contracts.py
│   ├── test_agent.py
│   ├── test_sessions.py
│   ├── test_tools.py
│   ├── test_logging.py
│   └── test_telegram_flow.py
├── evals/
│   └── questions.json        # local, non-secret evaluation set
├── main.py                   # process entry point
├── pyproject.toml
├── Dockerfile
├── railway.toml or render.yaml
├── .env.example
└── README.md
```

Names may be consolidated while implementing, but responsibilities should remain separated and testable.

## 6. Work phases

### Phase 0 — Baseline and secrets

- Replace `.env.example` values with placeholders only.
- Expand `.gitignore` for caches, coverage, local databases, run logs, grader-generated keys/data, and editor artifacts.
- Check Git history for accidentally committed secrets.
- Rotate any credential that may have been exposed.
- Change the supported Python range to a deployment-friendly version such as `>=3.11,<3.14`.
- Add missing runtime and development dependencies with locked versions.
- Add a real license or remove the unsupported MIT claim.

Acceptance:

- repository secret scan is clean;
- a fresh `uv sync` succeeds;
- config fails fast with a clear message when a required variable is missing.

### Phase 1 — Contracts, logging, and exact output

- Define JSON-compatible value types and a final reply model.
- Reject NaN, Infinity, non-JSON objects, extra top-level keys, and invalid/publicly unreachable log URLs.
- Add one immutable `run_id` per incoming message.
- Write one valid JSON object per JSONL line.
- Log timestamps, durations, user message, selected model, tool calls, source URLs, compact tool results, retries, validation failures, and final answer.
- Never log tokens, authorization headers, environment values, or hidden chain-of-thought.
- Serialize with `json.dumps(..., ensure_ascii=False, allow_nan=False, separators=(",", ":"))`.

Acceptance:

- every reply parses with `json.loads`;
- the outer object has exactly `answer` and `log_url`;
- the log downloads without authentication and every nonblank line parses independently.

### Phase 2 — Conversation handling

- Persist messages by Telegram chat ID.
- Retain a bounded number of recent turns with a short inactivity TTL (initially 15 minutes).
- Treat a new message after TTL as a new conversation.
- Lock each chat while a turn is running.
- Store only the context needed for analysis; do not feed old JSONL logs back to the model.
- Implement `/start`, `/help`, and `/reset`, but keep grading-message replies JSON-only.

Acceptance:

- a two-message task uses the first message while answering the second;
- unrelated questions after TTL do not inherit stale data;
- rapid duplicate Telegram updates are idempotent by `update_id`.

### Phase 3 — Data tools

- Search with optional trusted-domain preference, not a MOSPI-only allowlist.
- Fetch only public HTTP(S) URLs with redirect, timeout, content-size, and content-type controls.
- Block localhost, link-local, private-network, and metadata-service destinations to prevent SSRF.
- Parse CSV/TSV, JSON, Excel, HTML tables, and text-based PDFs.
- Normalize column names while preserving original labels in metadata.
- Cache downloaded resources by URL and content hash for the duration of a run.
- Expose table summaries and samples to the LLM instead of entire large datasets.
- Execute read-only DuckDB SQL and return compact JSON results.
- Add deterministic calculator/statistics operations for arithmetic, ranking, aggregates, percentages, correlation, and simple regression/forecast tasks.

Acceptance:

- fixture tests cover every supported format;
- a MOSPI-like table can be searched, fetched, filtered, ranked, and cited;
- malicious URLs and non-read-only SQL are rejected;
- tool timeouts leave a valid error event in the run log.

### Phase 4 — Agent loop

- Write a concise system prompt defining the task, evidence rules, current-turn semantics, tool-use policy, and answer-only finalization.
- Give the agent a bounded tool budget and an overall deadline below the grader's 300-second exchange timeout.
- Require source-backed answers for public-dataset questions.
- Retry transient model/tool errors with capped exponential backoff.
- Let the agent finalize through a tool such as `submit_answer(answer_json, evidence)`.
- Parse `answer_json`, validate JSON compatibility, and retry formatting separately from re-running expensive data collection.
- App code injects `log_url`; the model never chooses it.
- If analysis fails, still return one valid JSON object in the required outer contract and record the failure. Avoid Telegram-visible stack traces or prose.

Acceptance:

- inline arithmetic does not trigger unnecessary web search;
- public-data questions include source evidence in the log;
- malformed model output is repaired or rejected before Telegram sees it;
- the loop terminates under tool, token, and wall-clock limits.

### Phase 5 — Telegram and HTTP integration

- Replace the blocking `ai_chat()` call with an awaited async service call.
- Add webhook secret verification and a secret URL path.
- Restrict accepted updates to text messages needed by the project.
- Reply once per incoming grading message.
- Add Telegram retry handling and a Telegram-safe maximum response size.
- Expose lightweight liveness/readiness routes that do not call the LLM.
- Confirm `getWebhookInfo` shows no recent delivery errors.

Acceptance:

- a real user account can message the bot and receive one JSON object;
- webhook requests return promptly;
- two concurrent chats remain isolated;
- restart does not destroy prior public logs or active conversation state.

### Phase 6 — Tests and grader rehearsal

Add local eval questions for:

- inline rows: max/min, grouping, percentages, and exact numeric output;
- JSON embedded in the prompt;
- multi-turn context where the last message depends on the first;
- a public CSV/Excel/HTML/PDF dataset;
- a MOSPI-style state comparison;
- requested answers shaped as object, array, scalar, and nested object;
- missing/slow/broken sources;
- prompt injection inside fetched content;
- exact output formatting and wget-able JSONL.

Test layers:

1. unit tests with no network;
2. mocked LLM/tool-loop integration tests;
3. local webhook/API tests;
4. live Telegram smoke test;
5. exact public grader pipeline with a one-row `students.csv`;
6. repeated and multi-turn runs to expose stale-session and timeout bugs.

Acceptance:

- lint and unit/integration suites pass from a clean checkout;
- every local eval produces exactly the expected JSON value;
- the grader records `status: ok`, not `timeout` or `format_error`;
- final reply and downloaded log are archived as release evidence.

### Phase 7 — Deployment

- Deploy one always-on service with HTTPS and a persistent volume, initially on Railway or a paid Render web service.
- Build from the public GitHub repository using the lockfile.
- Mount persistent storage for SQLite/logs, or configure S3-compatible storage.
- Configure secrets only in the host:
  - `BOT_API_KEY`
  - `TELEGRAM_WEBHOOK_SECRET`
  - `PUBLIC_BASE_URL`
  - `OPENROUTER_API_KEY`
  - `LLM_MODEL`
  - `TAVILY_API_KEY`
  - storage/database settings
- Run database initialization before accepting traffic.
- Register the webhook after the production URL is stable.
- Add an external uptime check for `/healthz`.
- Configure restart policy, one active bot instance, log retention, cost caps, and API usage alerts.
- Perform a cold-start and restart drill.

Acceptance:

- `/healthz` is continuously reachable;
- the Telegram webhook survives redeploys;
- a log URL remains wget-able after restart;
- no secret appears in application logs or the repository;
- the bot answers comfortably within the grader timeout.

### Phase 8 — Documentation and submission

- Rewrite the README to match the actual code.
- Document architecture, local setup, required variables, supported data formats, testing, deployment, health checks, and known limitations.
- Include a sanitized sample question, exact reply, and sample JSONL event shapes.
- Record the deployed revision/tag and test timestamp.
- Keep the repository public.
- Verify the registration row immediately before submission.

Registration value:

```text
https://github.com/dipesh4000/analytiq_bot, analytiq_iitm_bot
```

## 7. Definition of done

The project is complete only when all of the following are true:

- production code contains no placeholder analysis path;
- the public repository builds from a clean checkout;
- secrets are absent from current files and Git history;
- a real Telegram user can complete single-turn and multi-turn tests;
- the final Telegram reply is one JSON object and nothing else;
- `answer` exactly matches the shape requested by the latest message;
- `log_url` downloads publicly with `wget`;
- every downloaded log line is valid JSON and explains the run without exposing secrets or private chain-of-thought;
- public-data answers are based on fetched evidence and deterministic calculations;
- failure, timeout, concurrency, duplicate-update, and restart paths are tested;
- the exact current grader pipeline passes;
- deployment health and webhook status are green;
- the submitted GitHub URL and Telegram username are re-verified.

## 8. Recommended implementation order

Implement Phases 0–2 first, because exact output and state are grading-critical. Then build one complete vertical slice—inline data question through Telegram to public log—before expanding file formats and search. Add deployment immediately after that slice, then improve data coverage while continuously running the grader. This reduces the risk of finishing the agent logic without a reachable, correctly formatted bot.
