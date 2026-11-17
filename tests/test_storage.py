import pytest
from pathlib import Path
from engines.shared.storage import LocalObjectStorage


def test_local_object_storage_lifecycle(tmp_path: Path):
    storage = LocalObjectStorage(root_dir=tmp_path)
    bucket = "test-bucket"
    key = "docs/sample.txt"
    content = b"Sample binary payload for PrepFreeX"

    # Put
    meta = storage.put_object(bucket, key, content, content_type="text/plain")
    assert meta.bucket == bucket
    assert meta.key == key
    assert meta.size_bytes == len(content)
    assert meta.content_type == "text/plain"

    # Exists & Head
    assert storage.exists(bucket, key)
    head_meta = storage.head_object(bucket, key)
    assert head_meta.sha256 == meta.sha256
    assert head_meta.size_bytes == len(content)

    # Get
    retrieved = storage.get_object(bucket, key)
    assert retrieved == content

    # Stream
    streamed = b"".join(list(storage.get_object_stream(bucket, key, chunk_size=8)))
    assert streamed == content

    # List
    items = storage.list_objects(bucket, prefix="docs/")
    assert len(items) == 1
    assert items[0].key == key

    # Delete
    assert storage.delete_object(bucket, key)
    assert not storage.exists(bucket, key)
    assert storage.list_objects(bucket) == []

