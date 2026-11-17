from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.db import get_db_cursor
from engines.shared.asset_manager import AssetManager
from engines.shared.config import settings
from engines.shared.storage import (
    BaseObjectStorage,
    LocalObjectStorage,
    S3ObjectStorage,
    get_storage,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    """Create a minimal valid 1x1 PNG file for testing."""
    # Minimal 1x1 transparent PNG bytes
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00"
        b"\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    p = tmp_path / "test_diagram.png"
    p.write_bytes(png_bytes)
    return p


def test_fastapi_storage_health(client: TestClient):
    """Test 1 & 2: Connect from FastAPI using application credentials & verify bucket health."""
    resp = client.get("/api/v1/storage/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["backend"] == "minio"
    assert data["accessible"] is True
    assert data["bucket"] == "prepfreex-question-assets"


def test_minio_upload_download_sha256(sample_png: Path):
    """Test 3, 4, 5, 6, 7: Upload PNG, list, download, compare SHA-256, presigned URL."""
    storage = get_storage("minio")
    bucket = settings.minio_bucket
    key = f"test-fixtures/{uuid.uuid4()}/test_diagram.png"

    orig_bytes = sample_png.read_bytes()
    orig_sha256 = hashlib.sha256(orig_bytes).hexdigest()

    # 1. Upload
    meta = storage.put_object(bucket, key, orig_bytes, content_type="image/png")
    assert meta.bucket == bucket
    assert meta.key == key
    assert meta.size_bytes == len(orig_bytes)
    assert meta.sha256 == orig_sha256

    # 2. List
    objs = storage.list_objects(bucket, prefix="test-fixtures/")
    assert any(o.key == key for o in objs)

    # 3. Head & Exists
    assert storage.exists(bucket, key) is True
    head = storage.head_object(bucket, key)
    assert head.size_bytes == len(orig_bytes)

    # 4. Download & verify SHA-256
    downloaded = storage.get_object(bucket, key)
    downloaded_sha256 = hashlib.sha256(downloaded).hexdigest()
    assert downloaded_sha256 == orig_sha256

    # 5. Presigned URL
    url = storage.get_url(bucket, key, expires_in=300)
    assert "http://127.0.0.1:9000" in url
    assert key in url
    assert "X-Amz-Signature" in url

    # Cleanup test object
    storage.delete_object(bucket, key)
    assert storage.exists(bucket, key) is False


def test_unauthenticated_anonymous_rejection():
    """Test 8: Verify the bucket rejects unauthenticated / anonymous access."""
    import urllib.request
    import urllib.error

    url = f"http://127.0.0.1:9000/prepfreex-question-assets/test-nonexistent.png"
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(url)
    assert exc_info.value.code in (403, 400)


def test_invalid_credentials_handling():
    """Test 9: Test incorrect-credential handling."""
    from botocore.exceptions import ClientError

    bad_storage = S3ObjectStorage(
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id="wrong_user",
        aws_secret_access_key="wrong_password",
        region_name="us-east-1",
        use_ssl=False,
        addressing_style="path",
    )
    with pytest.raises(ClientError) as exc_info:
        bad_storage.head_object(settings.minio_bucket, "any-key")
    error_code = exc_info.value.response.get("Error", {}).get("Code")
    assert error_code in ("InvalidAccessKeyId", "AccessDenied", "SignatureDoesNotMatch", "403")


def test_existing_local_storage_unaffected(tmp_path: Path):
    """Test 10: Verify that existing local storage functionality still works."""
    local_storage = get_storage("local", root_dir=tmp_path / "local_store")
    test_key = "diagrams/math_circuit.png"
    payload = b"LOCAL_STORAGE_BINARY_PAYLOAD_12345"

    meta = local_storage.put_object("local-bucket", test_key, payload, content_type="image/png")
    assert meta.size_bytes == len(payload)
    assert local_storage.exists("local-bucket", test_key) is True
    retrieved = local_storage.get_object("local-bucket", test_key)
    assert retrieved == payload


def test_aws_s3_configuration_switching():
    """Test 11: Verify that switching to an AWS-style endpoint is configuration-driven."""
    s3_storage = get_storage("aws_s3")
    assert isinstance(s3_storage, S3ObjectStorage)
    assert s3_storage.endpoint_url is None  # standard AWS endpoint
    assert s3_storage.addressing_style == "auto"
    assert s3_storage.use_ssl is True


def test_asset_manager_lifecycle_and_idempotency(tmp_path: Path):
    """Test 12: Full lifecycle (EXTRACTED -> UPLOADED -> VERIFIED) with DB persistence."""
    mgr = AssetManager()

    # Create a fresh unique PNG payload for this test invocation
    unique_marker = uuid.uuid4().bytes
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00"
        b"\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
    ) + unique_marker
    fresh_png = tmp_path / f"diagram_{uuid.uuid4().hex[:8]}.png"
    fresh_png.write_bytes(png_bytes)

    # Pick an existing question from canonical DB to test association
    with get_db_cursor() as cur:
        cur.execute("SELECT id, public_id FROM questions LIMIT 1;")
        q = cur.fetchone()

    q_id = q["id"] if q else None
    q_pub_id = q["public_id"] if q else "Q00000001"

    # Upload & verify asset (First time: fresh upload)
    result = mgr.upload_and_verify_asset(
        local_path=fresh_png,
        question_public_id=q_pub_id,
        question_id=q_id,
        role="stem",
        variant_type="original",
        alt_text="Test circuit diagram",
        extraction_method="smoke_test",
    )

    assert result["status"] == "VERIFIED"
    assert result["idempotent"] is False
    assert result["storage_bucket"] == "prepfreex-question-assets"
    assert f"question-assets/{q_pub_id}/" in result["storage_key"]
    assert result["storage_key"].endswith("/original.png")

    # Verify recorded in DB
    asset_id = result["asset_id"]
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM question_assets WHERE id = %s;", (asset_id,))
        db_rec = cur.fetchone()
        assert db_rec is not None
        assert db_rec["upload_status"] == "VERIFIED"
        assert db_rec["validation_status"] == "MACHINE_VERIFIED"
        assert db_rec["sha256"] == result["sha256"]
        assert db_rec["role"] == "stem"

    # Test idempotency (re-uploading identical file returns existing without error)
    retry_result = mgr.upload_and_verify_asset(
        local_path=fresh_png,
        question_public_id=q_pub_id,
        question_id=q_id,
        role="stem",
        variant_type="original",
    )
    assert retry_result["idempotent"] is True
    assert retry_result["asset_id"] == asset_id
