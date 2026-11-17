from __future__ import annotations

import io
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
import boto3
from botocore.config import Config
import cv2
import numpy as np

from apps.api.db import get_db_cursor
from engines.shared.config import settings

router = APIRouter(prefix="/api/v1/images", tags=["Secure Image Delivery"])


def remove_diagram_watermark(image_bytes: bytes) -> bytes:
    """
    Removes faint, pastel, and gray watermarks (e.g. 'MARKS' overlay) from academic diagrams
    while preserving 100% of black/dark ink lines, mathematical symbols, axes, and chemical bonds.
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Background/watermark whitening mask:
        # Faint luminance (>= 180) or faint pastel where all channels exceed 175
        mask = (gray >= 180) | ((img[:, :, 0] > 175) & (img[:, :, 1] > 175) & (img[:, :, 2] > 175))

        cleaned = img.copy()
        cleaned[mask] = [255, 255, 255]

        success, encoded = cv2.imencode(".png", cleaned)
        if success:
            return encoded.tobytes()
        return image_bytes
    except Exception:
        return image_bytes


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


@router.get("/{asset_id:path}/access")
def get_image_access(asset_id: str):
    """Generates a secure, short-lived presigned URL for an approved canonical image asset."""
    with get_db_cursor() as cur:
        # Check by id, object_key, sha256 or via question_image_links
        cur.execute("""
            SELECT id, object_key, bucket_name, detected_mime_type, width_px, height_px,
                   lifecycle_status, is_production_ready
            FROM public.image_assets
            WHERE (id::text = %s OR object_key = %s OR sha256 = %s)
              AND lifecycle_status = 'ACTIVE';
        """, (asset_id, asset_id, asset_id))
        asset = cur.fetchone()

        if not asset:
            cur.execute("""
                SELECT ia.id, ia.object_key, ia.bucket_name, ia.detected_mime_type, ia.width_px, ia.height_px,
                       ia.lifecycle_status, ia.is_production_ready
                FROM public.question_image_links qil
                JOIN public.image_assets ia ON ia.id = qil.asset_id
                JOIN public.completed_questions q ON q.id = qil.question_id
                WHERE (q.question_uid = %s OR qil.question_id::text = %s OR qil.asset_id::text = %s)
                  AND qil.is_active = true
                  AND ia.lifecycle_status = 'ACTIVE'
                LIMIT 1;
            """, (asset_id, asset_id, asset_id))
            asset = cur.fetchone()

    if not asset:
        raise HTTPException(status_code=404, detail="Approved canonical image asset not found.")

    s3 = get_s3_client()
    try:
        presigned_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": asset["bucket_name"], "Key": asset["object_key"]},
            ExpiresIn=3600  # 1 hour
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate access URL: {e}")

    return {
        "asset_id": str(asset["id"]),
        "object_key": asset["object_key"],
        "url": presigned_url,
        "direct_url": f"/api/v1/images/{asset['id']}/raw",
        "mime_type": asset["detected_mime_type"],
        "width": asset["width_px"],
        "height": asset["height_px"]
    }


@router.get("/{asset_id:path}/raw")
def stream_image(asset_id: str):
    """Directly streams image bytes from private MinIO storage without exposing MinIO credentials."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT id, object_key, bucket_name, detected_mime_type, lifecycle_status
            FROM public.image_assets
            WHERE (id::text = %s OR object_key = %s OR sha256 = %s)
              AND lifecycle_status = 'ACTIVE';
        """, (asset_id, asset_id, asset_id))
        asset = cur.fetchone()

        if not asset:
            cur.execute("""
                SELECT ia.id, ia.object_key, ia.bucket_name, ia.detected_mime_type, ia.lifecycle_status
                FROM public.question_image_links qil
                JOIN public.image_assets ia ON ia.id = qil.asset_id
                JOIN public.completed_questions q ON q.id = qil.question_id
                WHERE (q.question_uid = %s OR qil.question_id::text = %s OR qil.asset_id::text = %s)
                  AND qil.is_active = true
                  AND ia.lifecycle_status = 'ACTIVE'
                LIMIT 1;
            """, (asset_id, asset_id, asset_id))
            asset = cur.fetchone()

        if not asset:
            # Fallback 1: Direct lookup in completed_questions table by diagram_s3_key, question_uid, or ID
            cur.execute("""
                SELECT id, diagram_s3_key as object_key, 'prepfreex-question-assets' as bucket_name,
                       'image/png' as detected_mime_type, 'ACTIVE' as lifecycle_status
                FROM public.completed_questions
                WHERE (diagram_s3_key = %s OR question_uid = %s OR id::text = %s)
                  AND diagram_s3_key IS NOT NULL
                LIMIT 1;
            """, (asset_id, asset_id, asset_id))
            asset = cur.fetchone()

        if not asset and (asset_id.startswith("question-assets/") or "/" in asset_id):
            # Fallback 2: Direct MinIO object key
            asset = {
                "id": asset_id,
                "object_key": asset_id,
                "bucket_name": settings.minio_bucket or "prepfreex-question-assets",
                "detected_mime_type": "image/png",
                "lifecycle_status": "ACTIVE"
            }

    if not asset:
        raise HTTPException(status_code=404, detail="Image asset not found or not active.")

    s3 = get_s3_client()
    try:
        obj = s3.get_object(Bucket=asset["bucket_name"], Key=asset["object_key"])
        data = obj["Body"].read()
        cleaned_data = remove_diagram_watermark(data)
        return StreamingResponse(io.BytesIO(cleaned_data), media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Image could not be retrieved from storage: {e}")
