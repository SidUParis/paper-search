# arXiv Research Agent — Build Plan

> **Goal**: A self-hosted, 24/7 agent that fetches arXiv papers on configured topics, summarises them with any LLM, deduplicates, and pushes to Notion and/or Obsidian. Runs on a cheap VPS (€3–6/mo).

---

## Phase 0 — Repository & environment bootstrap

### 0.1 Initialise the project

```bash
mkdir arxiv-agent && cd arxiv-agent
git init
python3 -m venv .venv && source .venv/bin/activate
```

### 0.2 Install dependencies

```bash
pip install \
  litellm \
  arxiv \
  httpx \
  apscheduler \
  notion-client \
  pyyaml \
  loguru \
  python-dotenv \
  rich
pip freeze > requirements.txt
```

### 0.3 Directory structure to create

```
arxiv-agent/
├── agent.py               # orchestrator + scheduler entry point
├── fetcher.py             # arXiv query logic
├── summarizer.py          # LLM summarisation via litellm
├── store.py               # SQLite dedup + paper cache
├── outputs/
│   ├── __init__.py
│   ├── notion_writer.py   # push structured summary to Notion DB
│   └── obsidian_writer.py # write .md file to vault folder
├── config.yaml            # user-editable: topics, schedule, model
├── .env                   # API keys (never commit)
├── .env.example           # committed template
├── .gitignore
└── README.md
```

---

## Phase 1 — Configuration files

### 1.1 `config.yaml`

Define all user-tunable parameters here. Claude Code should generate this file with the following fields:

```yaml
schedule:
  cron: "0 8 * * 1"          # every Monday at 08:00 UTC
  max_papers_per_run: 30

arxiv:
  categories:
    - cs.CL
    - cs.AI
    - cs.IR
  keywords:
    - positional bias
    - LLM summarization
    - benchmark evaluation
    - retrieval augmented generation
  date_window_days: 7         # look back N days on each run
  sort_by: "submittedDate"    # or "relevance"

llm:
  provider: "gemini/gemini-2.0-flash"   # litellm model string
  # alternatives:
  #   openai/gpt-4o-mini
  #   anthropic/claude-haiku-4-5
  #   ollama/qwen2.5:7b  (local, no cost)
  temperature: 0.2
  max_tokens: 800
  relevance_threshold: 6      # 0-10; papers below this score are dropped

outputs:
  notion:
    enabled: true
    database_id: "YOUR_NOTION_DATABASE_ID"
  obsidian:
    enabled: true
    vault_path: "/home/user/obsidian-vault/papers"  # absolute path on VPS

logging:
  level: INFO
  file: "logs/agent.log"
```

### 1.2 `.env.example`

```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=
NOTION_TOKEN=
```

---

## Phase 2 — Core modules

### 2.1 `store.py` — SQLite dedup store

Implement a `PaperStore` class with:

- `__init__(db_path="papers.db")` — creates the DB and table if not exists
- Table schema: `papers(arxiv_id TEXT PRIMARY KEY, title TEXT, fetched_at TEXT, relevance_score REAL)`
- `is_seen(arxiv_id: str) -> bool`
- `mark_seen(arxiv_id: str, title: str, relevance_score: float)`
- `count() -> int`

No external dependencies — use `sqlite3` from stdlib.

### 2.2 `fetcher.py` — arXiv query

Implement a `fetch_papers(config: dict) -> list[dict]` function:

- Build an arXiv search query from `config.arxiv.categories` and `config.arxiv.keywords`
- Query using the `arxiv` library with `max_results = config.schedule.max_papers_per_run * 3` (over-fetch before dedup)
- Filter to papers published within `date_window_days`
- Return a list of dicts: `{arxiv_id, title, abstract, authors, published, pdf_url, categories}`

### 2.3 `summarizer.py` — LLM summarisation

Implement `summarize_paper(paper: dict, config: dict) -> dict`:

- Use `litellm.completion()` with the model string from config
- System prompt: instruct the model to act as a research assistant for NLP/AI
- User prompt: provide title + abstract, request JSON output with fields:
  - `tldr` (2 sentences max)
  - `key_contributions` (list of 3 bullet strings)
  - `method_keywords` (list of 5 short terms)
  - `relevance_score` (integer 0–10, based on configured topics)
  - `one_line` (single sentence for digest view)
- Parse the JSON response; on parse failure, retry once with a stricter prompt
- Return the original paper dict merged with the summary fields

### 2.4 `outputs/notion_writer.py` — Notion integration

Implement `push_to_notion(paper: dict, config: dict)`:

- Use `notion_client.Client` authenticated via `NOTION_TOKEN` env var
- Create a new page in the database specified by `config.outputs.notion.database_id`
- Property mapping:
  - `Title` (title) → paper title
  - `TL;DR` (rich_text) → tldr
  - `Score` (number) → relevance_score
  - `Categories` (multi_select) → arxiv categories
  - `Keywords` (multi_select) → method_keywords
  - `Published` (date) → published date
  - `URL` (url) → arxiv abstract URL
- Page body: render `key_contributions` as a bulleted list block

### 2.5 `outputs/obsidian_writer.py` — Obsidian markdown

Implement `write_to_obsidian(paper: dict, config: dict)`:

- Target path: `{vault_path}/{YYYY-MM}/{arxiv_id}.md`
- Create year-month subdirectory if it doesn't exist
- Write a markdown file with YAML frontmatter:
  ```yaml
  ---
  title: "..."
  arxiv_id: "..."
  published: "YYYY-MM-DD"
  score: 8
  tags: [cs.CL, positional-bias, benchmark]
  url: "https://arxiv.org/abs/..."
  ---
  ```
- Body: `## TL;DR`, `## Key contributions` (bulleted), `## Method keywords`, `## Links`
- Append a line to a monthly digest file `{vault_path}/digest-YYYY-MM.md` with the one-liner and a wiki-link to the paper file

---

## Phase 3 — Orchestrator

### 3.1 `agent.py` — main entry point

Implement `run_pipeline(config: dict)`:

1. Load config from `config.yaml` and secrets from `.env`
2. Initialise `PaperStore`
3. Call `fetch_papers(config)` → raw list
4. Filter out already-seen `arxiv_id`s via `store.is_seen()`
5. For each new paper:
   a. Call `summarize_paper(paper, config)`
   b. Drop if `relevance_score < config.llm.relevance_threshold`
   c. Call enabled output writers
   d. Call `store.mark_seen()`
   e. Log result with `loguru`
6. Print a run summary: N fetched, N new, N above threshold, N pushed

Implement `main()`:

- Parse `--run-now` CLI flag for immediate one-shot execution
- Otherwise start `APScheduler` with the cron expression from config
- Keep the process alive with `scheduler.start()` + `Event().wait()`

---

## Phase 4 — VPS deployment

### 4.1 Provision the VPS

Recommended: **Hetzner CAX11** (ARM, €3.29/mo, datacenter EU)

```bash
# on the VPS after SSH login
sudo apt update && sudo apt install -y python3.11 python3.11-venv git
# if using Ollama for local inference:
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b
```

### 4.2 Deploy the agent

```bash
git clone https://github.com/YOUR_USER/arxiv-agent /opt/arxiv-agent
cd /opt/arxiv-agent
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env   # fill in keys
nano config.yaml                    # set your topics and Notion DB ID
python agent.py --run-now           # smoke test
```

### 4.3 Systemd service

Create `/etc/systemd/system/arxiv-agent.service`:

```ini
[Unit]
Description=arXiv Research Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/opt/arxiv-agent
EnvironmentFile=/opt/arxiv-agent/.env
ExecStart=/opt/arxiv-agent/.venv/bin/python agent.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now arxiv-agent
sudo journalctl -u arxiv-agent -f   # follow logs
```

### 4.4 Obsidian sync via Syncthing (optional, free)

If you want Obsidian on your laptop to receive files written by the VPS:

```bash
# on VPS
sudo apt install syncthing
systemctl --user enable --now syncthing
# on your laptop: install Syncthing desktop, pair devices, share the vault folder
```

---

## Phase 5 — Notion database setup

Before running, create the Notion database manually (or via API):

| Property name | Type |
|---|---|
| Title | title |
| TL;DR | rich_text |
| Score | number |
| Categories | multi_select |
| Keywords | multi_select |
| Published | date |
| URL | url |

Then copy the database ID from the Notion URL (the 32-char hex after the last `/` before `?`) into `config.yaml`.

---

## Phase 6 — Testing checklist

- [ ] `python agent.py --run-now` completes without errors
- [ ] SQLite DB created at `papers.db`, rows inserted
- [ ] Second run with same date window produces 0 new papers (dedup works)
- [ ] Notion database shows new entries with all properties populated
- [ ] Obsidian vault folder contains `.md` files with correct frontmatter
- [ ] Monthly digest file `digest-YYYY-MM.md` exists and has entries
- [ ] Systemd service survives a `sudo reboot`
- [ ] Logs appear in `logs/agent.log`

---

## Optional extensions (post-MVP)

| Feature | How |
|---|---|
| Telegram digest bot | Add `outputs/telegram_writer.py` using `python-telegram-bot`; send one message per run with top-5 papers |
| Interactive Q&A on papers | Fetch full PDF, chunk + embed into ChromaDB, expose a `/ask` endpoint with FastAPI |
| Email digest | `outputs/email_writer.py` with `smtplib`; weekly HTML email via any SMTP relay |
| Multi-user topics | Extend `config.yaml` to have a list of topic profiles; run each as a separate pipeline |
| Web dashboard | Simple FastAPI + Jinja2 page showing recent papers and scores |
| Switch to local LLM | Change `llm.provider` to `ollama/qwen2.5:7b` in config; install Ollama on VPS; zero API cost |
