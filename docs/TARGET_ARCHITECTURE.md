# PrepFreeX — Target Architecture Specification

## 1. System Overview & Philosophy

PrepFreeX is an enterprise-grade, autonomous platform engineered to convert unstructured educational PDFs into high-fidelity, canonically tagged questions and deliver them through a high-concurrency, server-authoritative assessment engine.

The platform is designed around six architectural tenets:
1. **Modular Decoupling**: Complete separation between the **Ingestion Engine** (asynchronous batch processing, multimodal extraction, taxonomy tagging) and the **Assessment Engine** (real-time test generation, CBT session management, sub-millisecond scoring, learner mastery calibration).
2. **Canonical Single Source of Truth**: One canonical question entity linked to multiple source occurrences (`question_sources`), preventing duplicate question explosion while preserving full provenance across mock exams, yearbooks, and coaching papers.
3. **Externalized Binary Storage**: Actual PDF files, page renders, and extracted diagram assets are strictly externalized from PostgreSQL into S3-compatible local/cloud object storage (`LocalObjectStorage` / `S3ObjectStorage`). PostgreSQL stores only metadata, SHA-256 hashes, byte sizes, and canonical storage keys.
4. **Token & Cache Efficiency**: Multi-tiered, stage-specific cache invalidation prevents paying for completed LLM tasks twice. Modifying the taxonomy invalidates only subtopic classification without triggering PDF re-extraction. Modifying metadata prompts invalidates only metadata enrichment.
5. **Server-Authoritative Evaluation**: Zero client-side trust. All test timing, answer key comparisons, negative marking, and adaptive branching are computed server-side with strict idempotency keys.
6. **Zero Host Lock-in**: Fully runnable on local Windows native setups (PostgreSQL 18+, local filesystem storage) and effortlessly deployable to cloud Kubernetes, AWS S3/Cloudflare R2, and managed Postgres.

---

## 2. Global Component Topology

```mermaid
graph TD
    subgraph Data Sources & Ingestion
        PDFs["Source PDFs<br/>(Full Mocks / Chapter Tests / Q-Banks)"] --> Inv["PDF Inventory Utility<br/>(qbank inventory-pdfs)"]
        Inv --> Manifest["data/manifests/pdf_inventory.csv"]
        PDFs --> IngestPipeline["13-Stage Ingestion Engine"]
        IngestPipeline --> ObjStore["Local/S3 Object Storage<br/>(PDFs & Diagram PNGs)"]
        IngestPipeline --> StageCache["Persistent Stage Cache<br/>(data/cache/groq)"]
        IngestPipeline --> Staging["Staging Candidates<br/>(ingestion_question_candidates)"]
    end

    subgraph Canonical Data Tier (PostgreSQL)
        Staging --> Review["Human Audit & Review"]
        Review --> CanonicalDB["Canonical Question Bank<br/>(questions, question_options, tags)"]
        CanonicalDB --> TaxDB["Hierarchical Taxonomy<br/>(Subject > Unit > Topic > Subtopic)"]
        CanonicalDB --> ProvenanceDB["Multi-Source Provenance<br/>(question_sources, question_relations)"]
    end

    subgraph Assessment Services & Apps
        CanonicalDB --> SelectionEngine["Assessment Assembly & Rules Engine"]
        SelectionEngine --> AttemptService["Assessment Attempt Manager<br/>(Immutable Snapshots & States)"]
        AttemptService --> ScoringService["Server-Authoritative Scoring Engine"]
        ScoringService --> Analytics["Learner Mastery & IRT Calibration"]
        
        API["FastAPI Core Service (apps/api)"] --> IngestPipeline
        API --> AttemptService
        Web["PrepFreeX Web CBT Interface (apps/web)"] --> API
    end
```

---

## 3. Directory Layout & Package Boundaries

```
PrepFreeX_Ingestion_Engine/
├── apps/
│   ├── api/                       # Core FastAPI application (REST/WebSocket endpoints)
│   │   ├── routes/                # Ingestion, question bank, and assessment routes
│   │   └── main.py
│   └── web/                       # Next.js/React frontend (CBT assessment & audit interface)
├── services/
│   ├── ingestion_engine/          # 13-stage multimodal extraction & tagging engine
│   └── assessment_engine/         # Assessment definitions, CBT sessions & scoring
├── packages/
│   └── shared/                    # Reusable cross-service modules
│       ├── storage.py             # BaseObjectStorage, LocalObjectStorage, S3ObjectStorage
│       ├── stage_cache.py         # Stage-specific persistent LLM cache
│       └── models.py              # Canonical Pydantic data schemas
├── db/
│   ├── migrations/                # Versioned SQL migrations (0001 to 0004)
│   └── seeds/                     # JEE Main 2027 canonical taxonomy seeds (v1 & v2)
├── data/
│   ├── input/pdfs/
│   │   ├── full_tests/            # 75-question full mocks (300 marks)
│   │   ├── chapter_tests/         # Single-chapter topic-wise practice tests
│   │   └── question_banks/        # Multi-year coaching question banks
│   ├── object_store/local/        # S3-style bucket/key directory (external binaries)
│   ├── processed/jobs/            # Ingestion output bundles & extraction artifacts
│   ├── cache/groq/                # Persistent stage-specific LLM disk cache
│   ├── manifests/                 # PDF inventory manifests & duplicate audits
│   └── gold/                      # Human-verified gold benchmark test cases
├── docs/                          # Architectural specifications and diagrams
├── tests/                         # Pytest test suite (22+ unit, integration, DB tests)
└── pyproject.toml                 # Unified project dependencies & CLI scripts
```

---

## 4. Assessment Engine Modalities

The assessment engine supports seven distinct assessment types:
1. **Diagnostic Test**: Initial baseline assessment across subjects to identify student strengths and deficits.
2. **Daily Practice Problem (DPP)**: Short, high-frequency quizzes (5–10 questions) targeting recently completed subtopics.
3. **Chapter Test**: Comprehensive assessment covering all topics within a single unit/chapter.
4. **Part Test**: Multi-unit midterm assessment (e.g. 11th grade Physics Mechanics or Organic Chemistry).
5. **Full Mock Test**: Exact replica of official NTA JEE Main (75 questions, 300 marks, Section A MCQs + Section B optional numericals).
6. **Revision / Weak-Area Drill**: Targeted drills focused on learner-specific low-mastery subtopics.
7. **Adaptive Master Test**: Computerized Adaptive Testing (CAT) where difficulty branches dynamically based on real-time item responses.

