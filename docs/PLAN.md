# Phase 1 Implementation Plan

1. Inspect the supplied syllabus and test PDFs; distinguish selectable-text documents from scanned/image-based papers.
2. Build a deterministic syllabus parser for the three subject hierarchies and 54 unit nodes. Generate candidate topic/subtopic nodes as unreviewed taxonomy vocabulary and preserve the supplied Physics Unit 14 structure.
3. Build a PDF reader using PyMuPDF with low-resolution OCR fallback for scanned documents, plus source-page snapshots for visual review.
4. Implement a known-layout MathonGo pilot extractor and a generic line/state-machine question segmenter for other papers.
5. Build a conservative taxonomy rules classifier and a configurable OpenAI-compatible LLM adapter. Constrain all classification output to existing taxonomy codes.
6. Create the PostgreSQL schema for source documents, ingestion jobs, pages, candidate staging, taxonomy, canonical questions, options, tags, assets, revisions, classification runs and review records.
7. Add CLI and FastAPI upload entry points. Keep extracted candidates in staging and never auto-publish.
8. Validate the MathonGo five-question pilot and inspect the ALLEN scanned-paper OCR result; report missing/duplicate numbering rather than fabricating content.
9. Add automated tests and documentation. PostgreSQL execution is intended to be run locally with Docker; it is not available in the current build environment.
