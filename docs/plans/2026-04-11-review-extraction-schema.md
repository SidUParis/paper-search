# Review Extraction Schema Design

**Goal:** Define a reusable, topic-extensible extraction schema for a review layer built on top of the existing `paper-search` corpus, Notion databases, full-text cache, and Obsidian export pipeline.

**Design constraints:**
- Must work with the user's already-large local/Notion paper library.
- Must not hardcode one topic forever; future topics may change.
- Must support both `AgentSLR`-style protocol/screening/extraction and `LatteReview`-style multi-reviewer judgment.
- Must separate:
  1. stable cross-topic metadata,
  2. review-workflow state,
  3. topic-specific extraction fields.

---

## 1. Core design principle

Do **not** build one giant monolithic schema tied to `bias-fairness` only.

Instead, define the review schema in **3 layers**:

1. **Paper Identity Layer** — stable identifiers and source metadata
2. **Review Workflow Layer** — screening / decision / extraction state for one review project
3. **Topic Extension Layer** — domain-specific fields for the current review project

This keeps the system reusable when topics evolve from:
- multilingual bias benchmark
- to evaluation methodology
- to debate / sycophancy / summarization
- to any later thesis subproject

---

## 2. Layer A — Paper Identity Layer (stable across all projects)

These fields should stay stable and come from the existing `paper-search` corpus / Notion / Obsidian pipeline.

### Required fields
- `notion_page_id` — canonical paper key inside this workflow
- `paper_id` — existing Obsidian/local stable ID
- `topic_slug` — current corpus/topic source from `topics.json`
- `title`
- `authors`
- `year`
- `venue`
- `source_label` — ACL / arXiv / Scholar / other
- `source_url`
- `resolved_pdf_url`
- `local_fulltext`
- `local_pdf`
- `abstract`
- `summary`
- `zh_brief`
- `paper_limitations` — limitations extracted from the paper itself

### Why this layer exists
This layer makes the review system reuse the current library instead of rebuilding a separate corpus.

---

## 3. Layer B — Review Workflow Layer (project-specific state)

These fields describe **how a paper is treated inside one review project**.
A paper can participate in multiple projects, so this layer should conceptually belong to a `review_project + paper` pair.

### Required fields
- `review_project_id`
- `review_project_name`
- `review_status`
  - `candidate`
  - `screened_include`
  - `screened_exclude`
  - `screened_maybe`
  - `needs_human_review`
  - `extracted`
  - `synthesized`
- `relevance_score` — numeric score for ranking/triage
- `screening_decision`
  - `include`
  - `exclude`
  - `maybe`
- `screening_confidence`
- `screening_rationale`
- `criteria_matched`
- `criteria_failed`
- `human_override`
- `human_notes`
- `extractor_version`
- `screener_version`
- `last_reviewed_at`

### Optional reviewer-style fields
Useful if later adopting a more LatteReview-like multi-agent workflow:
- `reviewer_votes`
- `reviewer_conflicts`
- `consensus_decision`
- `consensus_rationale`
- `uncertainty_flags`

### Why this layer exists
This is the missing layer in the current repository. The current system tracks papers, but not review-state transitions.

---

## 4. Layer C — Topic Extension Layer (schema changes per project)

This layer is where topic-specific extraction happens.

### Design rule
Every review project should declare a `topic_schema` made of:
- `field_name`
- `type`
- `description`
- `required`
- `allowed_values` (if applicable)
- `evidence_source` preference
  - `abstract`
  - `summary`
  - `fulltext`
  - `manual`

### Supported field types
- `text`
- `boolean`
- `integer`
- `float`
- `list[text]`
- `enum`
- `json`

This keeps the schema extensible without rewriting the whole pipeline.

---

## 5. Cross-topic base extraction schema

These fields are useful for almost any research-paper review project and should be available as a reusable base schema.

### Base extraction fields
- `paper_type`
  - benchmark / evaluation / dataset / method / survey / position / other
- `research_problem`
- `task_type`
- `domain`
- `data_type`
- `evaluation_setup`
- `datasets_or_benchmarks`
- `metrics`
- `model_families`
- `main_claim`
- `key_findings`
- `review_relevant_limitations`
- `evidence_strength`
  - weak / medium / strong
- `thesis_relevance`
  - low / medium / high
- `followup_priority`
  - low / medium / high

### Why this base matters
If future topics change, these fields still remain useful. Only the topic extension changes significantly.

---

## 6. Recommended topic extension for the current bias/multilingual direction

This is the first concrete schema to implement because it matches the user's current PhD direction and future multilingual unified BBQ plan.

### Project example
`review_project_id: multilingual-bias-benchmark-landscape`

### Topic-specific fields
- `bias_type`
  - stereotype / toxicity / fairness / cultural_bias / performance_disparity / allocational_harm / representational_harm / other
- `benchmark_name`
- `benchmark_role`
  - introduces_benchmark / uses_existing_benchmark / compares_benchmarks / critique_of_benchmark
- `language_scope`
  - monolingual / multilingual / cross_lingual / code_switching
- `languages`
- `language_count`
- `language_families`
- `english_included`
- `translation_based`
- `native_authored_data`
- `culturally_grounded`
- `protected_attributes`
  - gender / race / religion / nationality / ethnicity / age / disability / socioeconomic_status / other
- `evaluation_target`
  - discriminative / generative / open_ended / preference / ranking / judge_based
- `human_evaluation_used`
- `annotation_source`
  - expert / crowd / synthetic / mixed / unspecified
- `cross_lingual_comparison_present`
- `worst_group_reporting`
- `reported_artifacts`
- `relevance_to_frenchbbq`
  - low / medium / high
- `relevance_to_multilingual_unified_bbq`
  - low / medium / high
- `review_gap_tags`
  - translation_artifact / low_resource_gap / cultural_validity_gap / metric_validity_gap / annotation_bias / english_centric_design / no_human_eval / missing_worst_group / other

### Why these fields
They make the output useful for:
- benchmark landscape mapping
- identifying multilingual blind spots
- deciding whether a paper helps FrenchBBQ / unified multilingual BBQ
- generating synthesis tables and gap analysis later

---

## 7. Example topic extensions for future topic changes

The schema should be able to change topics without changing the whole review pipeline.

### Example A — Conversational summarization
Possible extension fields:
- `conversation_type`
- `speaker_count`
- `meeting_vs_dialogue`
- `summary_granularity`
- `faithfulness_metric`
- `position_bias_discussed`
- `dialog_structure_used`
- `multilingual_setting`

### Example B — Sycophancy
Possible extension fields:
- `sycophancy_setting`
- `rlhf_related`
- `user_agreement_measure`
- `truthfulness_tradeoff`
- `judge_model_used`
- `reward_hacking_signal`
- `alignment_faking_signal`

### Conclusion
The review engine should load a project-specific schema definition rather than hardcoding one extraction class forever.

---

## 8. Recommended storage format for schema definitions

### Suggested config shape
Each review project should define a YAML file like:

```yaml
review_project_id: multilingual-bias-benchmark-landscape
review_project_name: Multilingual Bias Benchmark Landscape
source_topic_slug: bias-fairness

base_schema:
  include_defaults: true

topic_schema:
  - name: bias_type
    type: enum
    required: true
    allowed_values:
      - stereotype
      - toxicity
      - fairness
      - cultural_bias
      - performance_disparity
      - allocational_harm
      - representational_harm
      - other
    description: Main bias construct studied in the paper.
    evidence_source: fulltext

  - name: benchmark_name
    type: text
    required: false
    description: Benchmark or dataset name central to the study.
    evidence_source: fulltext

  - name: translation_based
    type: boolean
    required: false
    description: Whether the benchmark or evaluation setup is translation-based.
    evidence_source: fulltext
```

This format is compatible with:
- future CLI use
- AgentSLR-style extraction schema
- Notion property generation
- Obsidian frontmatter or JSON sidecar export

---

## 9. Output object shape for one extracted review record

Recommended canonical record shape:

```json
{
  "review_project_id": "multilingual-bias-benchmark-landscape",
  "notion_page_id": "...",
  "paper_id": "2025-smith-example-paper",
  "screening": {
    "decision": "include",
    "confidence": 0.92,
    "rationale": "Empirical multilingual benchmark paper with explicit bias evaluation.",
    "criteria_matched": [
      "empirical paper",
      "multilingual setting",
      "benchmark or evaluation focused"
    ],
    "criteria_failed": []
  },
  "extraction": {
    "paper_type": "benchmark",
    "task_type": "question_answering",
    "datasets_or_benchmarks": ["ExampleBench"],
    "metrics": ["accuracy", "bias_gap"],
    "bias_type": "stereotype",
    "benchmark_name": "ExampleBench",
    "language_scope": "multilingual",
    "languages": ["fr", "en", "es", "ar"],
    "language_count": 4,
    "translation_based": true,
    "native_authored_data": false,
    "human_evaluation_used": false,
    "cross_lingual_comparison_present": true,
    "relevance_to_frenchbbq": "high",
    "relevance_to_multilingual_unified_bbq": "high",
    "review_gap_tags": ["translation_artifact", "missing_worst_group"]
  }
}
```

---

## 10. Notion mapping recommendation

Because Notion property sprawl can become unmanageable, split fields into two groups.

### Group A — surfaced in Notion properties
These are useful for filtering and sorting:
- `Review Status`
- `Relevance Score`
- `Review Project`
- `Paper Type`
- `Bias Type`
- `Language Scope`
- `Language Count`
- `Benchmark Name`
- `Translation-based`
- `Human Eval`
- `Thesis Relevance`
- `Followup Priority`

### Group B — stored as JSON blob or markdown block
These are better kept compactly in one property or child block:
- full extraction JSON
- reviewer votes
- criteria matched / failed
- detailed rationale
- gap tags
- long-form evidence notes

This keeps Notion usable even with many future topic changes.

---

## 11. Obsidian mapping recommendation

### For paper notes
Add optional review frontmatter / sections:
- `review_projects`
- `review_status`
- `thesis_relevance`
- `followup_priority`
- `benchmark_name`
- `language_scope`
- `bias_type`

### For review project notes
Create one note per review project containing:
- objective
- inclusion criteria
- exclusion criteria
- extraction schema summary
- included papers
- thematic groups
- gap list
- thesis implications

This makes the review layer useful for writing, not just for storage.

---

## 12. Minimum viable implementation recommendation

For the first implementation, support exactly these topic-specific fields for the current bias/multilingual project:
- `paper_type`
- `bias_type`
- `benchmark_name`
- `language_scope`
- `languages`
- `language_count`
- `translation_based`
- `human_evaluation_used`
- `cross_lingual_comparison_present`
- `relevance_to_frenchbbq`
- `relevance_to_multilingual_unified_bbq`
- `review_gap_tags`
- `key_findings`
- `review_relevant_limitations`

This is small enough to be reliable, but rich enough to be genuinely useful.

---

## 13. Final recommendation

The schema should be **project-configurable, layered, and evidence-aware**.

### Stable rule set
- Use `notion_page_id` as the canonical paper key.
- Keep review state separate from paper identity.
- Use a reusable cross-topic base schema.
- Add topic-specific extension fields via YAML config.
- Expose only a small number of sortable fields in Notion.
- Keep rich extraction details in JSON/markdown for flexibility.

This design is the best fit for the current repository because it leverages the existing large corpus instead of rebuilding the pipeline from scratch.
