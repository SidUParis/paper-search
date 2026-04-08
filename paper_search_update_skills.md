# Paper Search — Update Log & Roadmap

## What's Been Done

### 1. Semantic Scholar Source (New)
- **`paper_search/scholar_source.py`** — Search FAccT, NeurIPS, ICLR, ICML via Semantic Scholar API
- Venue name normalization: maps full names (e.g. "Conference on Fairness, Accountability and Transparency") to short labels (FAccT, NeurIPS, ICLR, ICML)
- Rate limit handling with retry + exponential backoff
- Integrated into CLI as `--source scholar` (or `--source all`)

### 2. Notion Sync for Scholar Papers
- **`sync_scholar_papers()`** in `notion_sync.py` — pushes Scholar papers with Venue (select), Topics, and deduplication
- Scholar databases created for all 3 topics via Notion MCP

### 3. New Topic: Sycophancy in LLMs
- Notion page + 3 databases (ACL, arxiv, Scholar) created
- Registered in `topics.json` with keywords and queries
- Papers synced: 92 ACL + 78 arxiv + 57 Scholar = **227 papers**

### 4. ACL Venue Fix
- **Problem**: All ACL papers were labeled "ACL" regardless of actual venue
- **Fix**: `acl_source.py` now extracts the real venue (EACL, NAACL, EMNLP, ACL, COLING) from the paper's full_id
- **Findings track**: Papers from `findings-eacl`, `findings-acl`, etc. now get the parent venue as Source and "Findings" added to Topics
- Batch-fixed all existing papers in Notion across all topics

### 5. Comprehensive Search (max_results bump)
- **Problem**: `--max-results` defaulted to 20 per venue/year, hiding most papers (e.g. EMNLP 2025 had 116 matching papers but only 20 returned)
- **Fix**: Default raised to 200; added 2024 to `acl_years`
- Result: bias-fairness ACL went from 37 to **477 papers**

### 6. LLM Model Updates
- `qwen/qwen3.6-plus:free` was deprecated by OpenRouter (404 errors)
- Switched default to `stepfun/step-3.5-flash:free`
- Increased retry to 5 attempts with 15s backoff; inter-paper delay to 3s
- Model configurable via `OPENROUTER_MODEL` env var

### 7. Notion Sync Robustness
- ACL sync: sets Source (select) with real venue, falls back gracefully if property doesn't exist
- arxiv sync: removed hardcoded `arxiv ID` and `Categories` properties that broke on new databases
- All syncs use consistent schema: Title, Authors, URL, Abstract, Status, Published, Topics

---

## Current Paper Counts (as of 2026-04-08)

| Topic | ACL | arxiv | Scholar | Total |
|---|---|---|---|---|
| Bias & Fairness | ~477 | ~29 | ~296 | ~802 |
| Conv Summarization | ~68 | ~49 | ~103 | ~220 |
| Sycophancy | ~92 | ~78 | ~57 | ~227 |

---

## What's Left To Do

### High Priority
- [ ] **Summarize new papers** — hundreds of papers added without summaries; run `paper-search update <topic>` for each topic (will be slow with free model rate limits)
- [ ] **Sycophancy ACL Source fix** — the sycophancy ACL database doesn't have a "Source" select property; papers have venue in Topics but not in a filterable select field
- [ ] **Run sycophancy with `--source all`** to also do arxiv + Scholar search with summarization

### Medium Priority
- [ ] **Paid/local LLM for summarization** — free models are unreliable (deprecated, rate-limited); consider:
  - Paid OpenRouter model (qwen/qwen3.6-plus at ~$0.001/paper)
  - Local Ollama (zero cost, no rate limits)
  - Set via `OPENROUTER_MODEL` in `.env`
- [ ] **Add more Scholar venues** — AAAI, AIES, WWW, CSCW could be relevant for bias/fairness
- [ ] **Year filtering for Scholar** — currently returns all years; add `scholar_years` config to filter
- [ ] **Scheduled daily runs** — automate `paper-search update` via cron or systemd timer

### Low Priority
- [ ] **Batch summarization script** — dedicated command to just summarize unsummarized papers without re-searching
- [ ] **Progress tracking** — show progress bar for large syncs (400+ papers)
- [ ] **Duplicate detection across sources** — same paper may appear in both arxiv and Scholar; currently deduped by title within a run but not across databases
- [ ] **Export/report** — generate weekly digest of new papers across all topics

---

## CLI Quick Reference

```bash
# Activate venv first
source .venv/bin/activate

# Update a topic (all sources + summarize)
paper-search update bias-fairness

# Single source, no summarize (fast)
paper-search update bias-fairness --source acl --no-summarize
paper-search update bias-fairness --source scholar --no-summarize

# Available sources: all, acl, arxiv, scholar
# Topics: bias-fairness, conv-summarization, sycophancy
```

## Adding a New Topic

1. Ask Claude to create the Notion page + databases via MCP
2. Add the topic to `topics.json` with all database/data source IDs
3. Run `paper-search update <new-topic>`
