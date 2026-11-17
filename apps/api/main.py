from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes.health import router as health_router
from apps.api.routes.auth import router as auth_router
from apps.api.routes.taxonomy import router as taxonomy_router
from apps.api.routes.assessment_engine import router as assessment_engine_router
from apps.api.routes.students import router as students_router
from apps.api.routes.images import router as images_router

from apps.api.routes.assessment import router as assessment_router
from apps.api.routes.ingestion import router as ingestion_router
from apps.api.routes.questions import router as questions_router
from apps.api.routes.taxonomy_review import router as taxonomy_review_router
from apps.api.routes.question_variation import router as question_variation_router
from apps.api.routes.storage import router as storage_router

app = FastAPI(
    title="PrepFreeX Core Assessment & Ingestion API",
    description="Unified API for PrepFreeX JEE Assessment Platform, Question Variation Engine, and Private MinIO Image Delivery",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "*",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core Platform v1 Routers
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(taxonomy_router)
app.include_router(assessment_engine_router)
app.include_router(students_router)
app.include_router(images_router)

# Administrative & Ingestion Routers
app.include_router(ingestion_router)
app.include_router(assessment_router)
app.include_router(questions_router)
app.include_router(taxonomy_review_router)
app.include_router(question_variation_router)
app.include_router(storage_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "prepfreex-api", "version": "2.0.0"}
