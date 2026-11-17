from __future__ import annotations

import uuid
from typing import Any
from fastapi import APIRouter, HTTPException, Query

from apps.api.db import get_db_cursor
from engines.shared.asset_manager import AssetManager
from engines.shared.config import settings
from engines.shared.storage import get_storage

router = APIRouter(prefix="/api/v1/storage", tags=["Object Storage"])


@router.get("/health")
def storage_health() -> dict[str, Any]:
    """Check object storage connectivity and bucket health."""
    try:
        storage = get_storage()
        bucket = settings.minio_bucket
        exists = storage.exists(bucket, "non-existent-probe-key-123")
        return {
            "status": "healthy",
            "backend": settings.object_storage_backend,
            "endpoint": settings.minio_endpoint if settings.object_storage_backend == "minio" else "aws-s3-default",
            "bucket": bucket,
            "accessible": True,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "backend": settings.object_storage_backend,
            "error": str(e),
            "accessible": False,
        }


@router.get("/assets")
def list_question_assets(
    question_public_id: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List assets associated with questions, including presigned URLs."""
    mgr = AssetManager()
    with get_db_cursor() as cur:
        if question_public_id:
            cur.execute("""
                SELECT qa.*, q.public_id AS question_public_id
                FROM question_assets qa
                LEFT JOIN questions q ON qa.question_id = q.id
                WHERE q.public_id = %s
                ORDER BY qa.created_at DESC
                LIMIT %s OFFSET %s;
            """, (question_public_id, limit, offset))
        else:
            cur.execute("""
                SELECT qa.*, q.public_id AS question_public_id
                FROM question_assets qa
                LEFT JOIN questions q ON qa.question_id = q.id
                ORDER BY qa.created_at DESC
                LIMIT %s OFFSET %s;
            """, (limit, offset))
        rows = cur.fetchall()

        cur.execute("SELECT COUNT(*) FROM question_assets;")
        total = cur.fetchone()["count"]

    results = []
    for r in rows:
        d = dict(r)
        # Generate short-lived presigned URL if verified
        if d.get("upload_status") == "VERIFIED" and d.get("storage_key"):
            try:
                d["presigned_url"] = mgr.get_presigned_url(d["storage_key"], expires_in=1800)
            except Exception:
                d["presigned_url"] = None
        results.append(d)

    return {"total": total, "assets": results}


@router.get("/assets/{asset_id}/url")
def get_asset_url(asset_id: uuid.UUID, expires_in: int = Query(3600, ge=60, le=86400)) -> dict[str, Any]:
    """Retrieve presigned GET URL for an asset."""
    with get_db_cursor() as cur:
        cur.execute("SELECT storage_bucket, storage_key, upload_status FROM question_assets WHERE id = %s;", (asset_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Asset not found")

    mgr = AssetManager(bucket=row["storage_bucket"])
    url = mgr.get_presigned_url(row["storage_key"], expires_in=expires_in)
    return {
        "asset_id": asset_id,
        "storage_key": row["storage_key"],
        "storage_bucket": row["storage_bucket"],
        "presigned_url": url,
        "expires_in_seconds": expires_in,
    }

