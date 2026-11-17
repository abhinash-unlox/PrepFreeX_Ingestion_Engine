# PrepFreeX — Question Metadata Specification

This document defines the authoritative data contract for canonical questions stored in PrepFreeX.

---

## 1. Field Specification & Data Types

| Field Name | Type | Nullable | Default | Description / Allowed Values |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | No | `gen_random_uuid()` | Primary internal immutable identifier. |
| `public_id` | `text` | No | `Q00000001` | Human-facing sequential identifier (e.g. `Q00001045`). |
| `version` | `int` | No | `1` | Incremental revision counter. |
| `source_doc_id` | `uuid` | No | - | Foreign key to `source_documents.id` (primary origin). |
| `subject` | `text` | No | - | `mathematics`, `physics`, `chemistry`. |
| `question_type` | `text` | No | - | `mcq_single`, `mcq_multi`, `numerical`, `assertion_reason`, `statement_based`, `match_list`. |
| `language` | `text` | No | `'en'` | ISO-639-1 code. |
| `stem_md` | `text` | No | - | Markdown problem statement with KaTeX LaTeX formulas. |
| `stem_plain` | `text` | Yes | `NULL` | Plain text stripped of LaTeX for full-text search indexing. |
| `answer` | `jsonb` | No | - | Answer structure (option positions or numeric tolerance). |
| `explanation_md` | `text` | Yes | `NULL` | Step-by-step explanatory walkthrough. |
| `source_explanation_md` | `text` | Yes | `NULL` | Unaltered verbatim solution as printed in the source. |
| `explanation_source` | `text` | Yes | `NULL` | `source`, `ai`, `human`. |
| `answer_key_verified` | `boolean` | No | `false` | True when answer key matches independent audit. |
| `explanation_verified` | `boolean` | No | `false` | True when solution explanation is verified sound. |
| `difficulty` | `smallint` | Yes | `NULL` | 1 (Elementary) to 5 (Olympiad/Hard JEE Advanced). |
| `cognitive_level` | `text` | Yes | `NULL` | Bloom's taxonomy: `recall`, `understand`, `apply`, `analyze`. |
| `estimated_time_sec` | `int` | Yes | `NULL` | Expected solution time in seconds (e.g. 90 or 120). |
| `formulas_used` | `text[]` | No | `'{}'` | LaTeX formulas required to solve the question. |
| `keywords` | `text[]` | No | `'{}'` | Core technical keywords. |
| `concept_tags` | `text[]` | No | `'{}'` | Conceptual skills (e.g. `["Kirchhoff's Laws", "Energy Conservation"]`). |
| `skill_tags` | `text[]` | No | `'{}'` | Cognitive tasks (e.g. `["calculation", "graphical_interpretation"]`). |
| `has_figure` | `boolean` | No | `false` | Indicates whether the question references a figure/diagram. |
| `figure_status` | `text` | No | `'none'` | `none`, `pending`, `attached`. |
| `figure_description` | `text` | Yes | `NULL` | Textual description of the required diagram. |
| `status` | `text` | No | `'draft'` | `draft`, `needs_review`, `verified`, `rejected`, `retired`. |
| `extraction_method` | `text` | Yes | `NULL` | `text_regex`, `visual_assisted_text`, `multimodal_llm`. |
| `content_hash` | `text` | No | - | SHA-256 of normalized stem + sorted option texts. |

---

## 2. Answer JSON Schemas

### Single-Choice MCQ (`mcq_single`)
```json
{
  "type": "option",
  "positions": [2]
}
```

### Multi-Choice MCQ (`mcq_multi`)
```json
{
  "type": "option",
  "positions": [1, 3]
}
```

### Numerical (`numerical`)
```json
{
  "type": "numeric",
  "value": 50.0,
  "tolerance": 0.0,
  "unit": "μF"
}
```

### Match-List (`match_list`)
```json
{
  "type": "match",
  "pairs": {
    "P": "2",
    "Q": "4",
    "R": "1",
    "S": "3"
  }
}
```

---

## 3. LaTeX and Math Conventions
1. Inline math expressions must be enclosed in single dollar delimiters: `$E = mc^2$`.
2. Display (block) math equations must be enclosed in double dollar delimiters:
   ```
   $$\omega = \frac{1}{\sqrt{LC}}$$
   ```
3. Literal currency dollar signs must be escaped as `\$` in prose.
4. Mathematical functions and operators must use standard LaTeX macros: `\sin`, `\cos`, `\log`, `\ln`, `\sqrt`, `\dfrac`, `\int`.
5. Units should be enclosed in `\mathrm{...}` or `\text{...}`: `$100\,\Omega$`, `$50\,\mathrm{mA}$`.

---

## 4. Multi-Source Provenance (`question_sources`)
When the same question appears in multiple documents (e.g. 2026 Shift-1 paper, a coaching full test, and a multi-year question bank):
- One **canonical question** row is preserved in `questions`.
- Each physical appearance is recorded in `question_sources`:
  - `source_doc_id`: ID of the PDF document.
  - `relationship`: `origin` (primary source paper), `reprint` (coaching compilation), `mock_inclusion` (full test paper).
  - `source_local_number`: Question number within that PDF section (e.g. Q2).
  - `source_global_number`: Global sequential question number (e.g. Q27).
  - `source_page_start` / `source_page_end`: Page range in that specific PDF.

