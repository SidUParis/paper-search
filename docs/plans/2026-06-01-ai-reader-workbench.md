# AI Paper Reader Workbench Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Upgrade the current private static reader from a Notion/Obsidian browser into a full Daily Paper Reader-style AI reading workbench with Read in Context, Ask While Reading, AI paper Q&A, LLM refine/ranking, figure/table extraction, model-provider settings, and one-click paper-search update controls.

**Architecture:** Keep Notion as source-of-truth, Obsidian/local cache as durable asset layer, and paper-search as the ingestion/summarization backend. Replace the temporary `python -m http.server` origin with a private local Reader Server behind Cloudflare Access; the server hosts the reader UI and provides authenticated JSON APIs for chat, model settings, paper context retrieval, figure/table assets, job dispatch, and sync status.

**Tech Stack:** Python stdlib HTTP server or small ASGI later, OpenAI-compatible client (`openai>=1.0`), existing `paper_search` modules, local JSON config/state under `.reader/`, generated HTML/CSS/JS, Cloudflare Tunnel + Access, pytest + Click CliRunner. Avoid storing API keys in browser JS.

---

## Non-negotiable requirements

1. **Security:** LLM keys must stay server-side in local config/env. Frontend never receives raw keys. `private` profile stays behind Cloudflare Access.
2. **Provider flexibility:** UI can configure OpenAI-compatible providers: provider name, base URL, model name, API key, enabled flag, default chat/refine/ranking model.
3. **Global and per-paper AI:** Provide both a ChatGPT/Claude-like global terminal and embedded per-paper Ask panel.
4. **Read in Context:** LLM answers must cite/use the selected paper context: metadata, summary, zh brief, fulltext excerpts, extracted figures/tables when available, and related papers when requested.
5. **Sync controls:** UI must cover every configured topic/source in `topics.json`, including ACL, arXiv, Scholar/Semantic Scholar venues such as FAccT, NeurIPS/NIPS, ICLR, ICML, AAAI. Buttons call existing `paper-search` commands.
6. **Observability:** Background jobs must show status/logs in the UI and write durable state files.
7. **TDD:** Each implementation task begins with failing tests, then minimal code, then refactor.

---

## Current baseline

- Current repo: `/home/orange/paper-search-reader-site`
- Current branch: `feat/deep-reader-site`
- Current static exporter: `paper_search/reader_site.py`
- Current CLI: `paper-search export-reader-site --profile private|public`
- Current private output: `private-reader-site/`
- Current Cloudflare host: `https://reader.xfairllm.com`
- Current tunnel target: `http://127.0.0.1:8765`
- Current issue: served by static `http.server`, so no `/api/chat`, no job controls, no model settings, incomplete topic/source surface.

---

## Proposed phases

### Phase 0 — Lock down current deployment and runtime handoff

**Objective:** Ensure we can safely swap the origin server without exposing the private site.

**Files:**
- Modify: `/home/orange/.cloudflared/config.yml` only if port changes.
- Create: `scripts/run_reader_server.sh`
- Create: `docs/reader-workbench-ops.md`

**Acceptance criteria:**
- `reader.xfairllm.com` still shows Cloudflare Access login to unauthenticated requests.
- Local server healthcheck passes on `127.0.0.1:8765/health`.
- Tunnel origin can be restarted without changing Cloudflare DNS.

---

### Phase 1 — Reader Server API foundation

**Objective:** Replace static `http.server` with a local Python server that serves static files plus JSON APIs.

**Files:**
- Create: `paper_search/reader_server.py`
- Create: `tests/test_reader_server.py`
- Modify: `paper_search/cli.py` add `serve-reader-site`
- Create: `scripts/run_reader_server.sh`

**API endpoints:**
- `GET /health` → `{status:"ok", profile:"private", site_dir:"..."}`
- `GET /api/config/public` → safe runtime flags only, no secrets
- `GET /api/papers` → list from `data/papers.json`
- `GET /api/papers/<slug>` → one paper record + safe context metadata
- Static fallback: `/`, `/assets/*`, `/papers/*`, `/data/*`

**Test first:**
- `test_health_endpoint_returns_ok`
- `test_static_index_is_served`
- `test_api_config_does_not_expose_secret_strings`
- `test_unknown_api_returns_json_404`

**Verification command:**
```bash
pytest tests/test_reader_server.py -q
pytest tests/test_reader_site.py -q
paper-search serve-reader-site --site-dir private-reader-site --host 127.0.0.1 --port 8765
```

---

### Phase 2 — Server-side model/provider registry

**Objective:** Add backend-managed OpenAI-compatible provider settings inspired by Daily Paper Reader, but safer.

**Files:**
- Create: `paper_search/reader_models.py`
- Create: `tests/test_reader_models.py`
- Modify: `paper_search/reader_server.py`
- Add local state dir: `.reader/providers.json` (gitignored)
- Modify: `.gitignore` add `.reader/`

**Data model:**
```json
{
  "providers": [
    {
      "id": "deepseek",
      "label": "DeepSeek",
      "base_url": "https://api.deepseek.com",
      "api_key_env": "DEEPSEEK_API_KEY",
      "api_key_ref": "env:DEEPSEEK_API_KEY",
      "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
      "default_model": "deepseek-v4-flash",
      "enabled": true
    },
    {
      "id": "openai",
      "label": "OpenAI",
      "base_url": "https://api.openai.com/v1",
      "api_key_ref": "local:<encrypted-or-redacted>",
      "models": ["gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"],
      "default_model": "gpt-4.1-mini",
      "enabled": false
    },
    {
      "id": "custom",
      "label": "Custom OpenAI-compatible",
      "base_url": "https://openrouter.ai/api/v1",
      "models": ["qwen/qwen3.6-plus"],
      "default_model": "qwen/qwen3.6-plus",
      "enabled": true
    }
  ],
  "defaults": {
    "chat": "deepseek/deepseek-v4-flash",
    "paper_qa": "deepseek/deepseek-v4-flash",
    "refine": "deepseek/deepseek-v4-pro",
    "ranking": "qwen/qwen3.6-plus"
  }
}
```

**Security rule:** store API key values only server-side. `GET /api/models` returns `has_key: true/false`, never the key. `POST /api/models/<id>/key` accepts a key and writes local secret state.

**API endpoints:**
- `GET /api/models`
- `POST /api/models`
- `PATCH /api/models/<provider_id>`
- `POST /api/models/<provider_id>/test`
- `POST /api/models/<provider_id>/key`

**Test first:**
- provider config redacts keys
- provider config supports custom base URL/model
- OpenAI-compatible request builder uses `base_url`, `api_key`, `model`
- missing key returns actionable error

---

### Phase 3 — Paper context builder: Read in Context substrate

**Objective:** Build a reusable context retrieval layer for one paper and for top-k related papers.

**Files:**
- Create: `paper_search/reader_context.py`
- Create: `tests/test_reader_context.py`
- Modify: `paper_search/reader_site.py` to export stronger `data/papers.json` fields.

**Functions:**
- `load_reader_index(site_dir) -> dict[str, ReaderPaperLike]`
- `build_paper_context(slug, mode="balanced") -> PaperContext`
- `find_local_fulltext(paper) -> Path | None`
- `make_head_tail_excerpt(text, max_chars=24000) -> str`
- `related_papers(query_or_paper, top_k=5) -> list[PaperSnippet]` using local metadata/summary lexical search first.

**Context modes:**
- `quick`: title/abstract/summary/zh brief/limitations
- `balanced`: quick + head/tail fulltext excerpt
- `deep`: fulltext if token budget allows + figures/tables captions

**Test first:**
- local paths are resolved only under allowed directories
- missing fulltext gracefully falls back to summary
- head/tail excerpt preserves ending section marker
- public profile never leaks private local paths into context API

---

### Phase 4 — Global LLM terminal UI

**Objective:** Add a beautiful integrated chat terminal similar to ChatGPT/Claude, available from every page.

**Files:**
- Modify: `paper_search/reader_site.py` templates
- Create: `paper_search/static/reader-chat.js` or inline generated `assets/reader-chat.js`
- Create: `paper_search/static/reader-chat.css` or append to `assets/style.css`
- Add tests in `tests/test_reader_site.py`

**UI features:**
- Floating bottom-right `AI` button.
- Full-height side panel / modal with conversation list.
- Provider/model selector.
- Context mode selector: `Global`, `Current paper`, `Selected papers`, `Library search`.
- Prompt box supports Enter/send, Shift+Enter newline.
- Streaming-like incremental display if easy; otherwise normal response first.
- Chinese-first quick prompts:
  - “用中文解释这篇论文”
  - “和我的 LLM bias / FrenchBBQ / MultilingualBBQ 有什么关系？”
  - “Related work 怎么引用它？”
  - “指出局限性和可能复现实验”

**API endpoints:**
- `POST /api/chat`
- `GET /api/chat/sessions`
- `GET /api/chat/sessions/<id>`
- `DELETE /api/chat/sessions/<id>`

**Storage:**
- `.reader/chat_sessions/<session_id>.json`
- Optional later: sync selected Q&A to Obsidian note.

**Test first:**
- rendered index includes global terminal launcher
- `/api/chat` rejects empty prompt
- `/api/chat` includes selected paper context when paper_slug provided
- sessions persist and can be reloaded

---

### Phase 5 — Per-paper Ask While Reading panel

**Objective:** Each paper detail page gets an embedded reading assistant.

**Files:**
- Modify: `_detail_page()` in `paper_search/reader_site.py`
- Modify frontend JS/CSS from Phase 4
- Tests: `tests/test_reader_site.py`, `tests/test_reader_server.py`

**UI features per paper:**
- Inline `Ask this paper` panel under title or sticky right column.
- Buttons:
  - `中文速读`
  - `核心贡献`
  - `方法/实验拆解`
  - `局限性`
  - `和我的 PhD 关系`
  - `生成 related work 段落`
- Conversation tied to paper slug.
- Button to save answer to Obsidian/Notion later.

**API:** same `/api/chat` with `paper_slug` required for per-paper mode.

**Test first:**
- each detail page contains `data-paper-slug`
- per-paper quick prompts call `/api/chat` with correct slug
- server prompt includes paper title and not arbitrary other private files

---

### Phase 6 — AI paper Q&A with citations and source-grounding

**Objective:** Make answers grounded, not generic chat.

**Files:**
- Modify: `paper_search/reader_context.py`
- Modify: `paper_search/reader_models.py`
- Tests: `tests/test_reader_context.py`, `tests/test_reader_server.py`

**Prompt policy:**
- “Use only provided paper context unless user asks for general brainstorming.”
- “Cite context sections: [Abstract], [Summary], [Fulltext excerpt], [Figure N], [Table N].”
- “If missing, say not available.”
- Chinese-first by default for explanations.

**Answer format options:**
- default markdown answer
- structured JSON for refine/ranking jobs

**Test first:**
- prompt builder contains grounding instruction
- answer parser preserves markdown safely
- no arbitrary local file reading via prompt injection

---

### Phase 7 — Figure/table extraction pipeline

**Objective:** Match Daily Paper Reader’s ability to extract and display figures/tables from PDFs.

**Files:**
- Create: `paper_search/figure_extraction.py`
- Create: `tests/test_figure_extraction.py`
- Modify: `paper_search/fulltext.py` if needed to reuse cached PDF path
- Modify: `paper_search/reader_site.py` to render media gallery
- Add output dirs under repo cache and Obsidian:
  - `cache/figures/<paper-key>/figure-*.png`
  - `cache/figures/<paper-key>/manifest.json`
  - optional Obsidian copy: `papers/figures/<paper-id>/...`

**Implementation choices:**
1. Start simple and robust with PyMuPDF image/block extraction.
2. Extract page screenshots around image/table blocks when available.
3. Record manifest with page number, bbox, caption text guess, image path.
4. Do not add Java/pdffigures2 dependency initially.
5. OCR fallback later if needed.

**CLI/API:**
- `paper-search extract-figures <topic> --source all --limit N`
- `POST /api/jobs/extract-figures` with topic/source/limit

**Test first:**
- manifest format test with a small synthetic PDF fixture
- extractor returns empty manifest gracefully for text-only PDFs
- reader detail page renders gallery when `figures` present

---

### Phase 8 — LLM refine / ranking pipeline exposed in UI

**Objective:** Add Daily Paper Reader-like ranking/refine over newly found papers.

**Files:**
- Create: `paper_search/reader_refine.py`
- Create: `tests/test_reader_refine.py`
- Modify: `paper_search/reader_server.py`
- Modify UI: add “AI Refine / Rank” panel.

**Features:**
- Rank papers by relevance to configured research intents:
  - FrenchBBQ
  - MultilingualBBQ
  - LLM social bias / fairness evaluation
  - Audio BBQ / memory bias later
- Let user edit intent query in UI.
- Call selected provider/model.
- Save scores/rationales into local state and optionally Notion fields.
- Display score badges on cards: relevance, novelty, actionability.

**API:**
- `POST /api/refine/rank`
- `GET /api/refine/runs`
- `GET /api/refine/runs/<id>`

**Test first:**
- scoring prompt includes user intent and paper summaries
- parsed ranking rejects invalid JSON
- UI filter can sort by AI score

---

### Phase 9 — One-click paper-search update dashboard

**Objective:** Expose existing paper-search update functionality in the UI: update arXiv, ACL, Scholar/venue sources; then regenerate reader site.

**Files:**
- Create: `paper_search/reader_jobs.py`
- Create: `tests/test_reader_jobs.py`
- Modify: `paper_search/reader_server.py`
- Modify UI: add Admin/Sync page.

**Dashboard sections:**
1. Topics table from `topics.json`:
   - bias-fairness
   - conv-summarization
   - sycophancy
   - any future topic automatically
2. Source buttons per topic:
   - Update arXiv
   - Update ACL
   - Update Scholar
   - Update All
3. Venue display for Scholar:
   - FAccT, NeurIPS, NIPS, ICLR, ICML, AAAI when configured
4. Post-update actions:
   - Summarize new papers? default off for safety
   - Extract fulltext? optional
   - Extract figures? optional
   - Regenerate private reader site
5. Job log viewer.

**Important config fix:** Update `topics.json` scholar venues to include `AAAI` and `NIPS` for all main topics unless user narrows them.

**Job runner:**
- Run subprocess with repo venv:
```bash
cd /home/orange/paper-search-reader-site
source .venv/bin/activate || true
paper-search update <topic> --source <source> --max-results <n> --no-summarize
paper-search export-reader-site --profile private --output private-reader-site --source all --topic all --limit <n>
```
- Store job state in `.reader/jobs/<job_id>.json`.
- Never run arbitrary shell from user input; topic/source must be whitelisted.

**API:**
- `GET /api/topics`
- `POST /api/jobs/update`
- `GET /api/jobs`
- `GET /api/jobs/<id>`
- `POST /api/jobs/<id>/cancel`

**Test first:**
- topics endpoint returns all configured topics and sources
- job request rejects unknown source/topic
- command builder uses list argv, not shell string
- job state records start/end/exit code/log path

---

### Phase 10 — Notion/Obsidian sync correctness and full source coverage

**Objective:** Fix the current mismatch where the reader site does not cover all source/topic data.

**Files:**
- Modify: `paper_search/reader_site.py`
- Modify: `tests/test_reader_site.py`
- Modify: `topics.json`

**Required changes:**
- `collect_reader_papers(topic="all", source="all")` must iterate every topic and all available data source IDs:
  - ACL
  - arXiv
  - Scholar
- Preserve source label accurately.
- UI filters must show all topics and all source labels actually present.
- Limit behavior must be explicit:
  - `--limit-per-source` vs global `--limit`
  - default for private server should include full library or a high safe limit, not silently only 50.
- Add “Last sync / Notion updated_at / Obsidian asset status” badges.

**Test first:**
- fake topics with 2 topics x 3 sources returns all six source groups
- source filter includes Scholar when scholar records exist
- `limit_per_source` does not starve later sources
- missing source data source ID is skipped with warning, not crash

---

### Phase 11 — Settings UI for providers, keys, models, base URLs

**Objective:** Make model backend settings editable from the private web UI.

**Files:**
- Modify UI assets
- Modify: `paper_search/reader_server.py`
- Modify: `paper_search/reader_models.py`

**UI fields:**
- Provider label
- Provider type: OpenAI-compatible
- Base URL
- API key secret input
- Models list textarea
- Default model select
- Test connection button
- Defaults: chat, paper Q&A, refine/ranking, summary

**Provider presets:**
- OpenAI: `https://api.openai.com/v1`
- DeepSeek: `https://api.deepseek.com`
- OpenRouter: `https://openrouter.ai/api/v1`
- Custom: user-provided

**Test first:**
- settings page never renders existing key value
- `test connection` uses selected provider/model
- invalid base URL rejected

---

### Phase 12 — Save AI reading notes back to Obsidian / Notion

**Objective:** Reading conversations become durable research notes.

**Files:**
- Create: `paper_search/reader_notes.py`
- Create: `tests/test_reader_notes.py`
- Modify server/UI

**Features:**
- “Save answer to Obsidian” button.
- Append to corresponding paper note under heading:
```markdown
## AI Reading Notes
### 2026-06-01 — question
...
```
- Optional “write summary back to Notion” with explicit confirmation.
- Never auto-overwrite Notion Summary from casual chat unless user selects that action.

**Test first:**
- appends markdown safely
- creates paper note if missing using existing convention
- rejects path traversal

---

### Phase 13 — Deployment hardening

**Objective:** Keep reader server alive and protected.

**Files:**
- Create: `scripts/install_reader_server_user_service.sh`
- Create: `scripts/restart_reader_stack.sh`
- Create: `docs/reader-workbench-ops.md`

**Actions:**
- Create user-level systemd service if available, or Hermes background process fallback.
- Healthcheck local server and Cloudflare Access behavior.
- Ensure unauthenticated external request gets Access login, not private content.
- Document restart commands.

**Test/verification:**
```bash
curl -I http://127.0.0.1:8765/health
python scripts/check_cloudflare_access_guard.py https://reader.xfairllm.com
```

---

## Implementation order recommendation

Do not try to build everything in one giant patch. Implement in this order:

1. Phase 1 Reader Server API foundation
2. Phase 2 provider registry
3. Phase 3 context builder
4. Phase 4 global LLM terminal
5. Phase 5 per-paper Ask panel
6. Phase 9 sync dashboard skeleton
7. Phase 10 full source coverage fix
8. Phase 7 figure/table extraction
9. Phase 8 refine/ranking
10. Phase 11 settings UI polish
11. Phase 12 Obsidian/Notion note save
12. Phase 13 service hardening

This gives useful functionality quickly while keeping security intact.

---

## First MVP milestone

**MVP target:** within the first implementation cycle, `https://reader.xfairllm.com` should have:

- Cloudflare Access protection still active.
- Reader Server serving the private site.
- Global AI terminal button.
- Per-paper Ask panel.
- Server-side provider config using existing DeepSeek/OpenRouter env keys.
- `/api/chat` answering using paper context.
- `/api/topics` showing all topics/sources.
- Admin Sync page with buttons wired to dry-run/job-state first.

**MVP tests:**
```bash
pytest tests/test_reader_server.py tests/test_reader_models.py tests/test_reader_context.py tests/test_reader_site.py -q
python -m py_compile paper_search/reader_server.py paper_search/reader_models.py paper_search/reader_context.py
```

---

## Risks and mitigations

1. **Private leak through tunnel:** Always test unauthenticated `reader.xfairllm.com` before leaving tunnel running.
2. **API key leak:** Frontend only sees `has_key`; tests scan rendered HTML/JSON for key-like patterns.
3. **Long-running update jobs:** Use job state files and subprocess argv lists; no shell interpolation.
4. **Model cost explosions:** Default chat to cheap model; require confirmation for bulk refine/ranking over many papers.
5. **Notion write accidents:** Update/sync may write to Notion; UI labels must distinguish safe read-only site regeneration from external write-back.
6. **Source coverage mismatch:** Add tests around `topics.json` iteration and limit-per-source semantics.
7. **Figure extraction quality:** Start with robust PyMuPDF fallback, then improve later; do not block chat MVP on perfect figure extraction.

---

## Definition of done for the full project

- User can open `https://reader.xfairllm.com` from company computer, pass Cloudflare Access, and use an integrated AI terminal.
- User can ask questions globally and per paper, with grounded answers from paper context.
- UI can configure OpenAI/DeepSeek/OpenRouter/custom OpenAI-compatible providers without exposing keys.
- UI shows all Notion topics and all sources from `topics.json`.
- UI has one-click update buttons for arXiv, ACL, Scholar/all configured venues and can regenerate the private reader.
- Reader pages display extracted figures/tables when cached.
- LLM refine/ranking can score and sort papers by the user's research interests.
- Important answers can be saved to Obsidian, and explicit actions can write selected fields back to Notion.
- Test suite passes and Cloudflare Access guard check confirms no unauthenticated private content leak.
