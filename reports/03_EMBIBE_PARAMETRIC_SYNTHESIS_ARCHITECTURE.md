# PrepFreeX — Embibe-Inspired Parametric Synthesis Architecture
**Component:** Dual-Agent Offline Generation & Verification Engine  
**Implementation File:** `engines/synthesis/embibe_variant_engine.py`  
**Test Suite:** `tests/test_embibe_engine.py`  
**Batch Runner:** `scripts/run_embibe_synthesis_batch.py`  

---

## 1. Architectural Philosophy
Standard LLM question generators frequently suffer from **arithmetic hallucinations**, **intermediate calculation drift**, and **semantic degradation**. When an AI changes numerical values in a physics or chemistry problem, it often retains the original answer key or miscalculates intermediate exponents, producing unanswerable questions.

Inspired by Embibe's patented academic authoring pipeline, PrepFreeX implements a **Dual-Agent Architecture with Independent Blind Solver Parity**:
No AI-generated question is ever written to the database until an independent, unassisted solver solves the candidate question from scratch and agrees with the author's answer key.

```
       ┌────────────────────────┐
       │ Seed Question from DB  │
       │ (Canonical Exemplar)   │
       └───────────┬────────────┘
                   │
                   ▼
       ┌────────────────────────┐
       │   Agent 1: SME Author   │
       │  (Mutates Parameters & │
       │   Formulates Candidate)│
       └───────────┬────────────┘
                   │ Candidate Stem & Options
                   ▼
       ┌────────────────────────┐
       │  Agent 2: Blind Solver │
       │   (AIR 1 Exam Solver)  │
       │ *Has NO access to key* │
       └───────────┬────────────┘
                   │ Derived Independent Key & Derivation
                   ▼
       ┌────────────────────────┐
       │     Parity Arbiter     │
       │  (Mathematical & Key   │
       │     Congruence Check)  │
       └───────────┬────────────┘
            Matches?
          /          \
     YES /            \ NO
        ▼              ▼
┌──────────────┐  ┌─────────────────────┐
│ Ingest into  │  │ REJECT CANDIDATE    │
│  PostgreSQL  │  │ (Block from DB, Log │
│ (completed_q)│  │  Mismatch Reason)   │
└──────────────┘  └─────────────────────┘
```

---

## 2. Core Engine Components

### Module 1: SME Variant Generator (`generate_variant_candidate`)
- **Role:** Subject Matter Expert / JEE Exam Author.
- **Task:** Takes a clean canonical seed question and generates a new candidate variant by:
  - Modifying numerical parameters, geometries, or chemical variants while preserving the core underlying syllabus concept.
  - Ensuring physical realism (e.g. positive masses, speeds below $c$, realistic temperatures).
  - Computing a clean step-by-step derivation and generating 4 distinct options (1 correct, 3 plausible distractors).
- **Output:** Structured candidate JSON containing `question_text_latex`, `options`, `correct_option`, `solution_text_latex`.

### Module 2: AIR-1 Blind Solver (`blind_solve_candidate`)
- **Role:** Independent All-India Rank 1 Exam Candidate.
- **Critical Isolation Rule:** The blind solver is presented **only** with the candidate question stem and option text. The author's answer key, options mappings, and solution derivation are completely hidden.
- **Task:** Solves the problem purely from first principles, carries out the calculations, and selects the correct option key (`A`, `B`, `C`, or `D`) or derives the numerical target value.
- **Output:** Independent derivation and `derived_correct_option`.

### Module 3: Parity Arbiter (`ParityArbiter`)
- **Rule 1 (Single-Choice MCQ):** The Author's `correct_option` must match the Blind Solver's `derived_correct_option` exactly (e.g. `'B' == 'B'`).
- **Rule 2 (Numerical Questions):** The Author's `numerical_target` and Blind Solver's numerical value must fall within $\pm 1\%$ relative tolerance:
  $$\frac{|V_{\text{author}} - V_{\text{solver}}|}{\max(|V_{\text{author}}|, 10^{-6})} \le 0.01$$
- **Rule 3 (Option Uniqueness):** All 4 options must be distinct and non-empty.
- **Failure Handling:** If parity fails, the engine raises a `BlindSolveParityError`, discarding the candidate and preventing corrupt data from ever touching PostgreSQL.

### Module 4: Sequence-Backed Database Ingestion
- Database target: `public.completed_questions` in `jee_mains_assesment_work`.
- Table sequence: Automatically advances `completed_questions_id_seq` on `id`.
- Tagging: Ingested rows carry `generation_source: 'EMBIBE_DUAL_AGENT'`, linked `parent_question_id`, and `academic_status: 'EMBIBE_VERIFIED'`.

---

## 3. Real-World Failure Prevention Proof
During unit testing of Seed ID `2168` (Gravitation escape velocity):
- **Author Candidate Attempt:** The generator mutated radius and mass parameters, but slipped on an arithmetic power ($10^6$ vs $10^7$), concluding Option `A`.
- **Blind Solver Action:** Independently calculated $\sqrt{\frac{2GM}{R}}$ and arrived at Option `C`.
- **Arbiter Decision:** Mismatch caught (`Author 'A' != Blind Solver 'C'`). Candidate was immediately blocked.
- **Subsequent Pass:** Re-prompted generator produced a mathematically sound variant; Blind Solver agreed (`'B' == 'B'`); question was verified and ingested as ID `18717`.

---

## 4. How to Run Batch Synthesis

To generate verified variants for a specific subtopic:
```bash
python -m scripts.run_embibe_synthesis_batch --topic PHYS_U01_T01 --count 5
```

To automatically find and backfill all sparse subtopics across the curriculum:
```bash
python -m scripts.run_embibe_synthesis_batch --fill-sparse --min-count 5
```

