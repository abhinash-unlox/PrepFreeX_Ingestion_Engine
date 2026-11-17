# Taxonomy Workflow: Build → SME Review → Apply → Retag

This document explains the lifecycle of taxonomy v2 in PrepFreeX: generating candidate topics and subtopics from the JEE Main syllabus, conducting subject-matter expert (SME) review via CSV files, applying review changes to PostgreSQL, and re-tagging waiting questions.

---

## 1. Overview of the Taxonomy Hierarchy

The taxonomy is organized in 4 tiers:
```text
Subject (e.g. PHY)
 └── Unit (e.g. PHY.U14: Electromagnetic Induction and Alternating Currents)
      └── Topic (e.g. PHY.U14.T04: LCR series circuit)
           └── Subtopic (e.g. PHY.U14.T04.S02: LC oscillations)
```
- **Mutual Exclusivity**: Subtopics within a topic must be mutually exclusive and together cover the coaching chapter's taught problem-types.
- **Node Metadata**: Each subtopic includes a 1–2 sentence `description` specifying included and excluded problem types, plus two sample question stems (`example_stems`).
- **Code Stability**: Codes are assigned strictly by code format (e.g. `PHY.U14.T04.S02`) and are NEVER reused or renumbered.
- **Physics Unit 14**: Curated pilot nodes are preserved verbatim.
- **Practical Units**: `PHY.U20` (Experimental Skills) and `CHE.U20` (Practical Chemistry) contain topics only; no subtopics are generated.

---

## 2. Step 1: Building Taxonomy v2

Run the taxonomy builder across all 54 syllabus units:
```bash
qbank taxonomy-build --all
```
For a single unit:
```bash
qbank taxonomy-build --unit PHY.U14
```

### What this produces:
1. `db/seeds/jee_main_2027_taxonomy_v2.json`: The complete canonical seed JSON.
2. `docs/taxonomy_review/<UNIT_CODE>.csv`: 54 review CSV files (one per unit) for SME inspection.

---

## 3. Step 2: Subject-Matter Expert (SME) Review

Each CSV file in `docs/taxonomy_review/<UNIT_CODE>.csv` contains the following columns:
```csv
code,level,name,description,example_stems,action
```

SMEs edit the `action` column using the following allowed verbs:

| Action Verb | Meaning | Behavior |
| :--- | :--- | :--- |
| `keep` (or blank) | Retain node | Marks node `is_reviewed=true`. |
| `rename` | Rename node | Updates the node title in-place; marks `is_reviewed=true`. |
| `merge_into:<code>` | Merge into another node | Sets `is_active=false` and `replaced_by=target_code` on old node. Re-points questions tagged to old node to the target node. |
| `delete` | Deprecate node | Sets `is_active=false`. |
| `add` | Add new subtopic | Assigns the next sequential code (e.g. `S03`), ensuring codes are never reused. |

---

## 4. Step 3: Applying Review Edits

Apply the reviewed CSV back to the taxonomy seed and database:
```bash
qbank taxonomy-apply-review docs/taxonomy_review/PHY.U14.csv
```
This updates `db/seeds/jee_main_2027_taxonomy_v2.json`. If PostgreSQL is connected, it also updates the `taxonomy` table and re-points any existing `question_tags`.

To reload the complete seed into PostgreSQL:
```bash
qbank seed-taxonomy --file db/seeds/jee_main_2027_taxonomy_v2.json --persist
```

---

## 5. Step 4: Resolving Taxonomy Proposals

When the LLM encounters a question that does not fit existing subtopics, it proposes a new subtopic in `taxonomy_proposals` and tags the question at TOPIC level with `flags.needs_subtopic=true`.

1. List open proposals:
   ```bash
   qbank proposals
   ```
2. Accept a proposal with an approved subtopic name:
   ```bash
   qbank proposals --accept 1 --name "RMS value of complex waveforms"
   ```
   This automatically:
   - Allocates a fresh subtopic code under the parent topic.
   - Marks the proposal as accepted.
   - Re-tags all waiting questions and clears `flags.needs_subtopic`.

---

## 6. Step 5: Retagging After Taxonomy Updates

After updating taxonomy nodes, re-tag questions in existing ingestion jobs:
```bash
qbank retag --job <JOB_ID>
```
**Safety Invariant**: Questions tagged with `source='human'` are NEVER overwritten by the retagger.

