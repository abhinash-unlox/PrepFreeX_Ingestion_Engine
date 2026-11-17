from __future__ import annotations

import hashlib
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from apps.api.db import get_db_cursor
from engines.shared.config import settings
from engines.shared.storage import BaseObjectStorage, ObjectMetadata, get_storage


class AssetManager:
    """Manages question assets and their upload lifecycle between local disk,

    object storage (MinIO/S3), and PostgreSQL.
    """

    def __init__(self, storage: BaseObjectStorage | None = None, bucket: str | None = None):
        self.storage = storage or get_storage()
        self.bucket = bucket or settings.minio_bucket

    @staticmethod
    def calculate_sha256(data: bytes | Path) -> str:
        """Compute SHA-256 hex digest of file or bytes."""
        hasher = hashlib.sha256()
        if isinstance(data, Path):
            with data.open("rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
        else:
            hasher.update(data)
        return hasher.hexdigest()

    @staticmethod
    def generate_object_key(
        asset_id: str | uuid.UUID,
        question_public_id: str | None = None,
        candidate_id: str | None = None,
        variant_type: str = "original",
        extension: str = "png",
    ) -> str:
        """Generate structured, immutable object key according to Phase 5 specification.

        Examples:
        - Canonical: question-assets/Q00000050/3fa85f64.../original.png
        - Derived:   question-assets/Q00000050/3fa85f64.../thumbnail.webp
        - Candidate: question-assets/candidates/cand_123/3fa85f64.../original.png
        """
        ext = extension.lstrip(".")
        filename = f"{variant_type}.{ext}" if variant_type else f"original.{ext}"
        if question_public_id:
            return f"question-assets/{question_public_id}/{asset_id}/{filename}"
        elif candidate_id:
            return f"question-assets/candidates/{candidate_id}/{asset_id}/{filename}"
        return f"question-assets/unassigned/{asset_id}/{filename}"

    def upload_and_verify_asset(
        self,
        local_path: Path,
        question_public_id: str | None = None,
        question_id: uuid.UUID | None = None,
        candidate_id: str | None = None,
        role: str = "stem",
        variant_type: str = "original",
        option_position: int | None = None,
        alt_text: str | None = None,
        source_document_id: str | None = None,
        source_page_number: int | None = None,
        extraction_method: str | None = "manual_test",
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        """Execute full upload lifecycle:

        EXTRACTED -> ASSOCIATED -> VALIDATED -> UPLOAD_PENDING -> UPLOADING -> UPLOADED -> VERIFIED
        Never deletes local source file.
        Idempotent: verifies against existing records.
        """
        if not local_path.is_file():
            raise FileNotFoundError(f"Local asset source not found: {local_path}")

        file_bytes = local_path.read_bytes()
        file_size = len(file_bytes)
        local_sha256 = self.calculate_sha256(file_bytes)
        mime = mimetypes.guess_type(local_path.name)[0] or "image/png"
        ext = local_path.suffix.lstrip(".") or "png"

        # Check idempotency: does this question already have an asset with this sha256?
        with get_db_cursor() as cur:
            if question_id:
                cur.execute(
                    "SELECT id, storage_key, storage_bucket, upload_status FROM question_assets WHERE question_id = %s AND sha256 = %s;",
                    (question_id, local_sha256),
                )
            elif candidate_id:
                cur.execute(
                    "SELECT id, storage_key, storage_bucket, upload_status FROM question_assets WHERE candidate_id = %s AND sha256 = %s;",
                    (candidate_id, local_sha256),
                )
            else:
                cur.execute(
                    "SELECT id, storage_key, storage_bucket, upload_status FROM question_assets WHERE sha256 = %s;",
                    (local_sha256,),
                )
            existing = cur.fetchone()

        if existing and existing["upload_status"] == "VERIFIED" and self.storage.exists(existing["storage_bucket"], existing["storage_key"]):
            # Already uploaded and verified
            return {
                "asset_id": str(existing["id"]),
                "storage_key": existing["storage_key"],
                "storage_bucket": existing["storage_bucket"],
                "sha256": local_sha256,
                "size_bytes": file_size,
                "status": "VERIFIED",
                "idempotent": True,
            }

        asset_id = uuid.uuid4()
        storage_key = self.generate_object_key(
            asset_id=asset_id,
            question_public_id=question_public_id,
            candidate_id=candidate_id,
            variant_type=variant_type,
            extension=ext,
        )

        backend_name = settings.object_storage_backend

        # Record UPLOAD_PENDING in PostgreSQL
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO question_assets (
                    id, question_id, candidate_id, role, option_position,
                    storage_backend, storage_bucket, storage_key, mime,
                    width, height, file_size_bytes, alt_text, sha256,
                    source_document_id, source_page_number, extraction_method,
                    upload_status, validation_status, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    'UPLOADING', 'STRUCTURALLY_VALID', NOW(), NOW()
                );
            """, (
                asset_id, question_id, candidate_id, role, option_position,
                backend_name, self.bucket, storage_key, mime,
                width, height, file_size, alt_text, local_sha256,
                source_document_id, source_page_number, extraction_method
            ))

        # Perform Object Storage Put
        try:
            meta = self.storage.put_object(
                bucket=self.bucket,
                key=storage_key,
                data=file_bytes,
                content_type=mime,
                custom_metadata={
                    "sha256": local_sha256,
                    "asset_id": str(asset_id),
                    "role": role,
                },
            )

            # Verification 1: Object exists
            if not self.storage.exists(self.bucket, storage_key):
                raise RuntimeError(f"Object does not exist after put: {storage_key}")

            # Verification 2: Check content length
            head = self.storage.head_object(self.bucket, storage_key)
            if head.size_bytes != file_size:
                raise ValueError(f"Content length mismatch: expected {file_size}, got {head.size_bytes}")

            # Verification 3: Verify SHA-256 against downloaded payload
            downloaded = self.storage.get_object(self.bucket, storage_key)
            downloaded_sha256 = self.calculate_sha256(downloaded)
            if downloaded_sha256 != local_sha256:
                raise ValueError(f"SHA-256 mismatch! local: {local_sha256}, downloaded: {downloaded_sha256}")

            # Mark VERIFIED in DB
            with get_db_cursor() as cur:
                cur.execute("""
                    UPDATE question_assets
                    SET upload_status = 'VERIFIED',
                        validation_status = 'MACHINE_VERIFIED',
                        updated_at = NOW()
                    WHERE id = %s;
                """, (asset_id,))

            return {
                "asset_id": str(asset_id),
                "storage_key": storage_key,
                "storage_bucket": self.bucket,
                "storage_backend": backend_name,
                "size_bytes": file_size,
                "sha256": local_sha256,
                "mime": mime,
                "status": "VERIFIED",
                "idempotent": False,
            }

        except Exception as e:
            with get_db_cursor() as cur:
                cur.execute("""
                    UPDATE question_assets
                    SET upload_status = 'FAILED',
                        updated_at = NOW()
                    WHERE id = %s;
                """, (asset_id,))
            raise RuntimeError(f"Asset upload/verification failed: {e}") from e

    def get_presigned_url(self, storage_key: str, expires_in: int = 3600) -> str:
        """Generate short-lived presigned URL for secure asset retrieval."""
        return self.storage.get_url(bucket=self.bucket, key=storage_key, expires_in=expires_in)
