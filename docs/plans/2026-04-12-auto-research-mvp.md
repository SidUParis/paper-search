# Auto Research MVP for Sidney's PhD Workflow

## Goal
Build a practical human-in-the-loop auto research system for:
- multilingual bias benchmarks
- conversational summarization
- sycophancy evaluation

The system should help with:
1. finding new papers
2. structuring them into reliable metadata
3. prioritizing what to read next
4. surfacing recurring gaps and candidate research ideas
5. syncing the results into Notion + Obsidian

## Core Product Shape
This MVP is **not** a fully autonomous web agent.
It is a **paper-centric research operations pipeline**.

### Inputs
- arXiv / ACL / Semantic Scholar / Scholar search results
- title / abstract / summary / optional fulltext excerpts
- existing topic configs in `topics.json`
- review-project YAML schemas in `review_projects/examples/*.yaml`

### Outputs
- structured extraction rows in `cache/reviews/*/extractions.jsonl`
- updated Notion metadata via existing review writeback flow
- Obsidian notes / wiki pages
- daily/weekly digest and research-gap summaries
- ranked reading queues per topic

## Recommended Architecture

### Layer 1 — Discovery
Use the existing `paper-search update ...` commands as the ingestion layer.
Keep new papers flowing into topic-specific review queues.

### Layer 2 — Structured Extraction
Use a hybrid extraction stack:
1. fast heuristic extractor
2. optional LLM fallback for selected fields / uncertain cases
3. schema normalization to allowed enum values

Current best practical fallback model:
- `qwen/qwen-2.5-72b-instruct`

Avoid for current production extraction:
- `glm-4.5-air` (too many parse failures in benchmark)
- `minimax/minimax-m2.5:free` as sole model (latency too unstable)
- tiny local models as sole extractor (too weak on difficult semantic fields)

### Layer 3 — Triage / Priority
Each paper should receive derived flags such as:
- relevance_to_frenchbbq
- relevance_to_multilingual_unified_bbq
- relevance_to_conversational_summarization_work
- relevance_to_sycophancy_work
- likely benchmark paper
- likely method paper
- likely review / survey

This enables reading queues like:
- top 3 papers to read today
- top 5 benchmark-design papers this week
- low-priority backlog

### Layer 4 — Synthesis
Generate topic-level summaries from structured extractions:
- benchmark families
- language coverage gaps
- evaluation setup distribution
- recurring limitations
- candidate research gaps

### Layer 5 — Research Idea Support
Only after structured extraction is stable, generate:
- idea slates
- benchmark extension opportunities
- contradiction notes
- literature gap memos

## Immediate MVP Deliverables

### Deliverable A — Hybrid extraction in repo
Implement:
- heuristics first
- optional Qwen72B fallback
- schema normalization
- safe merge back into extraction rows

### Deliverable B — Daily/weekly auto research summaries
Produce per-topic summaries containing:
- new papers
- top priority papers
- recurring gaps
- candidate follow-up questions

### Deliverable C — Reading queue generation
Sort papers by:
- topic relevance
- benchmark novelty
- direct usefulness for current thesis milestones

## Current model choice guidance

### Best current fallback
`qwen/qwen-2.5-72b-instruct`
- fast enough (~3s/sample in benchmark)
- cheap enough for production extraction
- stable JSON-ish output after normalization
- strongest practical cloud option tested so far

### Rejected for current extraction MVP
`glm-4.5-air`
- strong small single-example behavior
- but failed to return parseable JSON for most real benchmark items
- too much reasoning / formatting instability for current pipeline

## Recommended operating mode
Default mode should be conservative:
- keep heuristics as the base extractor
- call cloud fallback only for configured review projects
- normalize all fallback outputs before saving
- preserve existing deterministic fields unless fallback is explicitly enabled

## Next implementation steps
1. add hybrid extraction helpers in `paper_search/review_extraction.py`
2. allow model override via environment variable for extraction fallback
3. write unit tests for normalization and fallback merge behavior
4. run review-layer tests
5. rerun targeted 12-paper benchmark after integration

## Success criterion for the MVP
Tomorrow-morning useful outcome means:
- repo contains a documented architecture
- hybrid extraction is implemented in code
- tests pass
- benchmark evidence exists showing the chosen fallback is usable

## Future upgrades
- fallback only on low-confidence / ambiguous records
- add field-level confidence scores
- automatic weekly topic dossier generation
- contradiction mining across papers
- auto-generated idea slates from review clusters
