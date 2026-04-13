# Review Layer MVP Plan for `paper-search`

**Goal:** Add a review orchestration layer on top of the existing `paper-search` corpus so the system can support `AgentSLR`-style protocol/screening/extraction/synthesis and `LatteReview`-style reviewer workflows without replacing the current retrieval/full-text/Notion/Obsidian foundation.

**Key decision:** `paper-search` remains the **Corpus Layer**. The new work is a **Review Layer**, not a replacement search engine.

---

## 1. Why this is the right architecture

The current repository already provides strong infrastructure:
- topic-based retrieval from ACL / arXiv / Scholar
- Notion sync
- full-text fetch and local cache
- full-text summary generation
- Chinese brief + limitations extraction
- Obsidian export with stable `paper_id` and `notion_page_id`

Therefore the missing capability is not paper ingestion. The missing capability is:
- review project definition
- screening state
- structured extraction
- cross-paper synthesis
- human-review checkpoints

This MVP should only add that layer.

---

## 2. Product framing

### Current state
`paper-search` is a strong **paper discovery + enrichment + library sync** system.

### Desired next state
`paper-search` becomes a **paper discovery + enrichment + review orchestration** system.

### Resulting 3-layer architecture
1. **Corpus Layer**
   - existing retrieval/fulltext/summary/Notion/Obsidian
2. **Review Layer**
   - new project configs, screening, extraction, synthesis
3. **Writing Layer**
   - review notes, evidence tables, thesis-facing memos

---

## 3. MVP scope

The MVP should support one concrete but extensible workflow:

> Create a review project from the existing corpus, screen candidate papers, extract structured fields for included papers, and generate a synthesis note.

### Explicit non-goals for MVP
- replacing current search pipelines
- building a complete PRISMA production system
- implementing full multi-agent debate from day one
- supporting every topic schema perfectly
- full Notion schema migration automation

---

## 4. Proposed repo additions

### New files
- `paper_search/review_projects.py`
- `paper_search/review_screening.py`
- `paper_search/review_extraction.py`
- `paper_search/review_synthesis.py`
- `paper_search/review_store.py`
- `paper_search/review_notion.py`

### New config directory
- `review_projects/`
  - one YAML file per review project

### New docs/examples
- `review_projects/examples/multilingual-bias-benchmark-landscape.yaml`

### Optional future consolidation
If the implementation should start simpler, phase 1 can begin with a single file:
- `paper_search/review_pipeline.py`

But the module split above is preferable once the MVP is stable.

---

## 5. Canonical data model

### 5.1 Review project
A review project is the top-level object.

Recommended fields:
- `review_project_id`
- `review_project_name`
- `source_topic_slug`
- `objective`
- `research_questions`
- `inclusion_criteria`
- `exclusion_criteria`
- `screening_prompt_profile`
- `extraction_schema`
- `created_at`
- `updated_at`

### 5.2 Review record
A review record represents one paper inside one review project.

Recommended fields:
- `review_project_id`
- `notion_page_id`
- `paper_id`
- `screening_decision`
- `screening_confidence`
- `screening_rationale`
- `criteria_matched`
- `criteria_failed`
- `human_override`
- `review_status`
- `extraction_json`
- `synthesis_tags`
- `updated_at`

### Important rule
A paper can appear in multiple review projects. Therefore review data should **not** be modeled as a single global status on the paper object.

---

## 6. Storage recommendation

### Recommended MVP storage
Use a local JSON/JSONL/SQLite review store inside the repo.

Suggested path:
- `cache/reviews/<review_project_id>/records.jsonl`
- `cache/reviews/<review_project_id>/state.json`

### Why local review storage first
- avoids immediate Notion schema explosion
- supports multiple review projects cleanly
- easier iteration while prompts/schema change
- easier debugging and re-running

### Notion for surfaced metadata only
Write only a compact subset back to Notion, such as:
- `Review Project`
- `Review Status`
- `Relevance Score`
- `Thesis Relevance`
- maybe `Paper Type`, `Language Scope`, `Bias Type`

This keeps Notion usable while the richer extraction lives locally.

---

## 7. How the review layer plugs into the existing corpus

## Step 1 — Candidate loading
Input source should be the existing Notion paper databases referenced in `topics.json`.

The review loader should:
- read the review project's `source_topic_slug`
- iterate the relevant topic databases (ACL / arXiv / Scholar)
- reuse current helper logic from `fulltext_pipeline.py` for reading page properties
- emit candidate paper objects with:
  - title
  - abstract
  - summary
  - zh_brief
  - limitations
  - local_fulltext path if available
  - page id / page url

### Design choice
This replaces AgentSLR's own search step with the user's already-curated corpus.

---

## Step 2 — Coverage/enrichment check
Before screening, the review layer should check whether a paper has enough evidence.

### Evidence preference order
1. `Summary`
2. `zh_brief`
3. extracted `paper_limitations`
4. `local_fulltext`
5. abstract only as fallback

### Behavior
If a candidate lacks summary/fulltext enrichment, the pipeline may:
- either skip and flag `needs_enrichment`
- or call the existing full-text enrichment flow

### Recommendation for MVP
For reliability, MVP should first operate on already-enriched papers and skip the rest with a clear reason.

---

## Step 3 — Screening
This is the first new major review capability.

### Inputs for screening
- review objective
- research questions
- inclusion criteria
- exclusion criteria
- paper title
- abstract
- summary
- zh_brief
- paper limitations

### Output
- `include` / `exclude` / `maybe`
- confidence score
- rationale
- matched criteria
- failed criteria

### AgentSLR influence
This stage mirrors the protocol-first screening stage.

### LatteReview influence
Later enhancement can add multi-reviewer votes, but MVP should start with one screener plus optional human override.

---

## Step 4 — Structured extraction
Run only on included papers.

### Inputs
- the review project's extraction schema
- title
- abstract
- summary
- zh_brief
- limitations
- optionally a clipped fulltext excerpt

### Output
- one structured extraction object per paper

### Design choice
Unlike the current AgentSLR skeleton, this MVP should not rely only on title+abstract. It should leverage the existing enrichment outputs to improve extraction quality.

---

## Step 5 — Synthesis
Generate a project-level synthesis from included paper extractions.

### Expected outputs
- key themes
- benchmark/method/language clusters
- gap list
- shortlist of most relevant papers
- thesis implications
- follow-up reading priorities

### Output destinations
- local markdown file
- Obsidian review note
- optional Notion review page later

---

## 8. Proposed CLI surface

### Phase 1 commands
- `paper-search review-init <config.yaml>`
- `paper-search review-screen <review_project_id>`
- `paper-search review-extract <review_project_id>`
- `paper-search review-synthesize <review_project_id>`
- `paper-search review-run <review_project_id>`

### Suggested behavior
#### `review-init`
- validates config
- creates local review project directory/state

#### `review-screen`
- loads candidates from topic corpus
- writes review records with decisions

#### `review-extract`
- processes only included papers
- writes `extraction_json`

#### `review-synthesize`
- builds markdown synthesis note

#### `review-run`
- runs screen -> extract -> synthesize in sequence

---

## 9. Review project config format

Recommended YAML shape:

```yaml
review_project_id: multilingual-bias-benchmark-landscape
review_project_name: Multilingual Bias Benchmark Landscape
source_topic_slug: bias-fairness
objective: >
  Build a structured review of multilingual bias benchmark papers relevant to
  future unified multilingual BBQ design.

research_questions:
  - What multilingual bias benchmarks currently exist?
  - Which languages are covered, and how are they selected?
  - Are benchmarks translation-based or natively constructed?
  - Which bias dimensions and evaluation protocols are used?

inclusion_criteria:
  - empirical paper
  - benchmark or evaluation focused
  - multilingual or cross-lingual setting

exclusion_criteria:
  - purely English-only papers
  - opinion pieces without empirical evaluation
  - papers unrelated to bias/fairness evaluation

screening:
  confidence_threshold_for_human_review: 0.8

schema:
  use_base_schema: true
  topic_schema_file: review_projects/schemas/multilingual-bias-benchmark.yaml
```

---

## 10. Output files for one review project

Suggested structure:

```text
cache/reviews/<review_project_id>/
  state.json
  candidates.jsonl
  records.jsonl
  extractions.jsonl
  synthesis.md
```

### Meaning
- `state.json` — progress and counters
- `candidates.jsonl` — frozen candidate snapshot for reproducibility
- `records.jsonl` — screening decisions
- `extractions.jsonl` — structured extraction output
- `synthesis.md` — final review memo

This gives you resumability and auditability without overcomplicating Notion first.

---

## 11. Obsidian integration plan

### New review note path
- `papers/` stays for paper notes
- add `reviews/` for project-level synthesis notes

Suggested output:
- `reviews/<review_project_id>.md`

### Review note contents
- objective
- research questions
- inclusion/exclusion criteria
- top included papers
- thematic groupings
- evidence table summary
- gap analysis
- relevance to thesis
- next actions

### Why this matters
This turns the system into something you can directly use for:
- thesis writing
- meeting prep
- Xiaohongshu content planning
- literature map updates

---

## 12. Notion integration plan

### MVP Notion behavior
Do **not** immediately try to mirror the full review JSON in Notion.
Instead, write only light-touch properties back to the existing paper DB where possible.

### Recommended surfaced properties
- `Review Project`
- `Review Status`
- `Relevance Score`
- `Thesis Relevance`
- `Followup Priority`

### Optional second wave
Once the schema stabilizes, add a dedicated Notion review database storing one row per:
- `review_project_id + notion_page_id`

That would be the cleanest long-term model.

---

## 13. MVP implementation order

### Task 1 — Project config loader
Create:
- `review_projects.py`

Responsibilities:
- load YAML config
- validate project fields
- load topic schema definition

### Task 2 — Candidate loader
Create:
- `review_store.py`
- helper reuse from `fulltext_pipeline.py`

Responsibilities:
- query topic Notion DBs
- emit normalized candidate objects
- persist candidate snapshot

### Task 3 — Screening stage
Create:
- `review_screening.py`

Responsibilities:
- build screening prompt
- score decision
- write review records
- mark human-review-needed cases

### Task 4 — Extraction stage
Create:
- `review_extraction.py`

Responsibilities:
- load included records
- apply schema-based extraction
- save extraction JSON

### Task 5 — Synthesis stage
Create:
- `review_synthesis.py`

Responsibilities:
- cluster extracted records
- build markdown synthesis
- generate review note in Obsidian

### Task 6 — CLI integration
Modify:
- `paper_search/cli.py`

Responsibilities:
- expose review commands
- print progress and summary stats

---

## 14. Minimal prompt strategy for MVP

### Screening prompt
Should explicitly ask the model to decide against project criteria using only provided evidence.

### Extraction prompt
Should require structured JSON only, aligned to the project's schema.

### Synthesis prompt
Should summarize only from extracted records, not from hidden prior knowledge.

### Reliability rule
Prefer using:
- title
- abstract
- existing full-text summary
- zh_brief
- limitations

before feeding raw full text again. This keeps cost and prompt size manageable.

---

## 15. Human-in-the-loop policy

MVP should not aim for fully autonomous review.

### Human review triggers
- screening confidence below threshold
- conflicting cues in rationale
- extraction contains too many `unknown`/`N/A` values
- paper marked `high thesis relevance`

### Why this matters
This preserves quality while still reducing the mechanical workload substantially.

---

## 16. Recommended first real project

Start with exactly one review project:

### `multilingual-bias-benchmark-landscape`
Why:
- directly tied to current PhD direction
- supports future unified multilingual BBQ work
- likely to produce high-value synthesis quickly
- schema is already well-motivated

### MVP success criteria
- run on the existing `bias-fairness` corpus
- produce a screened candidate set
- extract structured fields from included papers
- generate one synthesis markdown note
- identify top papers relevant to multilingual unified BBQ

---

## 17. Risks and mitigations

### Risk 1 — Topic DB too noisy
Mitigation:
- screening stage with confidence threshold
- human review on borderline cases

### Risk 2 — Notion schema gets bloated
Mitigation:
- keep rich extraction local first
- only surface compact properties in Notion

### Risk 3 — Extraction too tied to one topic
Mitigation:
- layered schema design
- project-specific YAML files

### Risk 4 — Prompt cost grows too much
Mitigation:
- reuse current summaries/zh briefs before raw fulltext
- process only included papers deeply

### Risk 5 — Review data collides across projects
Mitigation:
- use `review_project_id + notion_page_id` as the review key

---

## 18. Final recommendation

The best way to incorporate `AgentSLR` and `LatteReview` ideas is:

### Reuse from current system
- retrieval
- corpus management
- full-text enrichment
- Notion IDs
- Obsidian notes

### Borrow from AgentSLR
- review project abstraction
- protocol-first workflow
- screening/extraction/synthesis stages
- human checkpoints

### Borrow from LatteReview
- reviewer-style rationale
- optional multi-reviewer or consensus later
- stronger paper triage logic

### Do not do
- do not replace the existing search pipeline
- do not build a second independent paper database
- do not force all review data directly into the existing paper properties on day one

This MVP design is the lowest-friction path from the current paper library into a true review engine.
