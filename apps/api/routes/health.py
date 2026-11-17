from __future__ import annotations

from fastapi import APIRouter
from apps.api.db import check_db_health
from engines.shared.config import settings

router = APIRouter(prefix="/api/v1/health", tags=["Health & Readiness"])


@router.get("/live")
def liveness():
    """Kubernetes / container liveness probe."""
    return {"status": "live", "service": "prepfreex-backend"}


@router.get("/ready")
def readiness():
    """Readiness probe verifying PostgreSQL and MinIO connectivity."""
    db_res = check_db_health()
    
    # Check MinIO
    minio_ok = False
    try:
        import boto3
        from botocore.config import Config
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        s3.head_bucket(Bucket=settings.minio_bucket)
        minio_ok = True
    except Exception as e:
        minio_error = str(e)
    
    is_ready = db_res.get("database_connected", False) and minio_ok
    
    return {
        "status": "ready" if is_ready else "degraded",
        "database": db_res,
        "object_storage": {
            "connected": minio_ok,
            "endpoint": settings.minio_endpoint,
            "bucket": settings.minio_bucket,
        },
        "llm_provider": {
            "provider": settings.llm_provider,
            "model": settings.groq_model,
        }
    }
