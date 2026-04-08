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

---

## How To: Update Papers

Update fetches new papers from all sources, syncs them to Notion, and optionally generates AI summaries.

```bash
# Always activate venv first
source .venv/bin/activate

# Full update (all sources + summarize) — comprehensive but slow
paper-search update bias-fairness

# Fast update: search + sync only, skip summarization
paper-search update bias-fairness --no-summarize

# Update a single source
paper-search update bias-fairness --source acl --no-summarize
paper-search update bias-fairness --source arxiv --no-summarize
paper-search update bias-fairness --source scholar --no-summarize

# Available sources: all (default), acl, arxiv, scholar
# Available topics: bias-fairness, conv-summarization, sycophancy
```

**What happens during update:**
1. Searches each configured source (ACL Anthology, arxiv API, Semantic Scholar API)
2. Deduplicates by title across sources within the run
3. Saves a local markdown file to `output/<topic>_latest.md`
4. Syncs new papers to the corresponding Notion database (skips existing by URL)
5. If `--summarize` (default): calls LLM to summarize papers without a Summary in Notion

**Safe to run daily** — deduplication ensures no duplicate papers are created.

**Recommended workflow:**
```bash
# Step 1: Fast search + sync for all topics
paper-search update bias-fairness --no-summarize
paper-search update conv-summarization --no-summarize
paper-search update sycophancy --no-summarize

# Step 2: Run summarization separately (slower, rate-limited)
paper-search update bias-fairness --source acl  # will only summarize unsummarized papers
```

---

## How To: Summarization

AI summaries are generated via OpenRouter using a free LLM model. Each paper gets a structured summary with RQ, Idea, Method, Theory, and Results sections.

### Configuration

The model is set in `paper_search/summarizer.py` and can be overridden via `.env`:

```bash
# In .env file (optional)
OPENROUTER_API_KEY=sk-or-v1-...       # required
OPENROUTER_MODEL=stepfun/step-3.5-flash:free  # optional, this is the default
```

### Running summarization

```bash
# Summarize during update (default behavior)
paper-search update bias-fairness

# Only summarize (skip search, just fill in missing summaries)
# Currently no dedicated command — run full update, it will skip existing papers
# and only call the LLM for papers without a Summary field
paper-search update bias-fairness --source acl
```

### Rate limit issues

Free models on OpenRouter have aggressive rate limits:
- **429 errors**: The summarizer retries up to 5 times with 15s exponential backoff
- **404 errors**: The model was deprecated — change `OPENROUTER_MODEL` in `.env` or `summarizer.py`
- **Delay between papers**: 3 seconds by default

**If rate limits are too slow**, consider:
- **Paid model**: Set `OPENROUTER_MODEL=qwen/qwen3.6-plus` (no `:free` suffix) — costs ~$0.001/paper
- **Local Ollama**: Install Ollama, run `ollama pull qwen2.5:7b`, set model to `ollama/qwen2.5:7b`
- **Different free model**: Try `google/gemma-3-12b-it:free` or check OpenRouter for available free models

### Summary format in Notion

Each paper's Summary field contains:
```
**RQ**: The main research question (1-2 sentences)
**Idea**: The core approach (1-2 sentences)
**Method**: Methodology details (2-3 sentences)
**Theory**: Theoretical grounding (1 sentence or N/A)
**Results**: Key findings (2-3 sentences)
```

---

## How To: Create a New Topic

### Step 1: Create Notion databases (via Claude MCP)

Ask Claude to create:
1. A sub-page under Paper Search Hub (page ID: `33bc4b98-a76f-8195-905b-fa7fccf08e75`)
2. Three databases under that page: ACL Papers, arxiv Papers, Scholar Papers

Each database should have this schema:
| Property | Type | Notes |
|---|---|---|
| Title | title | Paper title |
| Authors | rich_text | Comma-separated |
| URL | url | Paper link |
| Abstract | rich_text | Truncated to 2000 chars |
| Summary | rich_text | Filled by AI summarizer |
| Status | select | New, Read, Archived |
| Published | date | Publication date |
| Topics | multi_select | Topic tags |
| Venue | select (Scholar only) | FAccT, NeurIPS, ICLR, ICML |

### Step 2: Register in topics.json

Add a new entry with all IDs from the created databases:

```json
{
  "my-new-topic": {
    "name": "My New Topic",
    "keywords": ["keyword1", "keyword2", "keyword3"],
    "acl_database_id": "<from Notion>",
    "acl_data_source_id": "<from Notion>",
    "arxiv_database_id": "<from Notion>",
    "arxiv_data_source_id": "<from Notion>",
    "arxiv_queries": [
      "search query 1",
      "search query 2"
    ],
    "acl_venues": ["acl", "eacl", "naacl", "emnlp", "findings", "coling"],
    "acl_years": [2024, 2025, 2026],
    "scholar_database_id": "<from Notion>",
    "scholar_data_source_id": "<from Notion>",
    "scholar_venues": ["FAccT", "NeurIPS", "ICLR", "ICML"],
    "scholar_queries": [
      "search query 1",
      "search query 2"
    ],
    "created": "2026-04-08"
  }
}
```

**Key fields:**
- `keywords`: Used to filter ACL papers (any keyword match in title+abstract)
- `arxiv_queries` / `scholar_queries`: Full search queries sent to the API
- `acl_venues`: Which ACL venues to search
- `acl_years`: Which years to include
- `scholar_venues`: Which ML conferences to search on Semantic Scholar

### Step 3: Run the first update

```bash
source .venv/bin/activate

# Fast first run: search + sync without summarization
paper-search update my-new-topic --no-summarize

# Then summarize
paper-search update my-new-topic
```

### Tips for good queries
- **ACL keywords**: Use short terms that match in title/abstract (e.g. "bias", "fairness"); any match counts
- **arxiv queries**: Use full phrases, these are sent as search queries (e.g. "social bias large language model")
- **Scholar queries**: Similar to arxiv, combined with venue filtering
