# Adding and Ingesting PDFs

## 1. Prepare the environment

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[test]"
```

Tesseract OCR is optional but recommended for scanned papers. Install the Tesseract binary and English language data on the host.

## 2. Generate taxonomy

```bash
qbank seed-taxonomy --syllabus data/input/SYLLABUS.PDF
```

Review `db/seeds/jee_main_2027_taxonomy.json`. Candidate topics are unreviewed. Do not treat them as final until a subject-matter expert confirms them.

## 3. Inspect a PDF

```bash
qbank inspect "data/input/your-paper.pdf"
```

The command reports page count, extracted text lengths, OCR/text mode, embedded images and drawings.

## 4. Run ingestion

```bash
qbank ingest "data/input/your-paper.pdf" --taxonomy db/seeds/jee_main_2027_taxonomy.json
```

Each job creates an artifact folder containing:

- `report.json`
- `question_import.json`
- `document_pages.json`
- `classifications.json`
- page images where rendered

Inspect all questions, equations, options, diagrams and source page references before approval.

## 5. Configure an LLM classifier (optional)

Set in `.env`:

```env
CLASSIFIER_PROVIDER=openai_compatible
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-key
LLM_MODEL=your-model
```

Use a provider endpoint that implements OpenAI-compatible `/chat/completions`. Verify its data-processing terms before sending coaching PDFs or licensed material. The classifier can only select codes already present in the taxonomy seed.

## 6. Start PostgreSQL and store extraction candidates

```bash
docker compose up -d
qbank migrate
qbank seed-taxonomy --persist
qbank ingest "data/input/your-paper.pdf" --persist
qbank report
```

All uploaded candidates are staged with `needs_review`. They are not automatically added to the canonical question bank.

## 7. Canonical import

After a human has reviewed the question, options, answer, explanation, taxonomy tags, figure state and licensing status, create/approve the import JSON and run:

```bash
qbank validate data/import/approved-questions.json
qbank import data/import/approved-questions.json
```

Do not set source licensing to `cleared` without documenting a valid right to use the material.
