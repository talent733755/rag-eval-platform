from __future__ import annotations

import hashlib
import io
import os
import time
from pathlib import Path

import pytest

from rag_eval_api.storage.errors import (
    BlobAlreadyExists,
    BlobChecksumMismatch,
    BlobKeyError,
    BlobNotFound,
    BlobSecurityError,
    BlobSizeExceeded,
)
from rag_eval_api.storage.local import LocalBlobStore


def test_local_blob_store_writes_private_opaque_key_and_round_trips(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = LocalBlobStore(tmp_path / "blobs", max_bytes=32)

    stored = store.put(io.BytesIO(b"hello"))

    assert stored.byte_size == 5
    assert stored.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert stored.storage_key.count("/") == 1
    assert "hello" not in stored.storage_key
    assert store.exists(stored.storage_key)
    with store.open(stored.storage_key) as handle:
        assert handle.read() == b"hello"
    assert (tmp_path / "blobs").stat().st_mode & 0o077 == 0
    assert (tmp_path / "blobs" / stored.storage_key).stat().st_mode & 0o077 == 0
    assert str(tmp_path) not in caplog.text


def test_local_blob_store_rejects_traversal_absolute_and_symlink_keys(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")

    for key in ("../outside.txt", "/etc/passwd", "a/../../outside", "a/b/c"):
        with pytest.raises(BlobKeyError) as error:
            store.exists(key)
        assert error.value.code == "invalid_storage_key"

    link = tmp_path / "blobs" / "aa"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(tmp_path)
    with pytest.raises(BlobKeyError):
        store.exists("aa/outside.txt")


def test_local_blob_store_enforces_size_checksum_and_cleans_temporary_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "blobs"
    store = LocalBlobStore(root, max_bytes=4)

    with pytest.raises(BlobSizeExceeded):
        store.put(io.BytesIO(b"12345"))
    with pytest.raises(BlobChecksumMismatch):
        store.put(io.BytesIO(b"1234"), expected_sha256="0" * 64)

    assert list(root.rglob(".upload-*")) == []
    assert list(root.rglob("*")) == []


def test_local_blob_store_does_not_overwrite_or_follow_existing_storage_path(
    tmp_path: Path,
) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    first = store.put(io.BytesIO(b"one"))
    target = store._path_for_key(first.storage_key)

    with pytest.raises(BlobAlreadyExists) as error:
        store._publish_temp_file(store._write_temp(io.BytesIO(b"two")), target)
    assert error.value.code == "blob_already_exists"

    assert target.read_bytes() == b"one"
    store.delete(first.storage_key)
    with pytest.raises(BlobNotFound), store.open(first.storage_key):
        pass


def test_local_blob_store_temp_file_is_removed_when_source_fails(tmp_path: Path) -> None:
    class BrokenSource:
        def read(self, _: int) -> bytes:
            raise RuntimeError("source failed")

    root = tmp_path / "blobs"
    store = LocalBlobStore(root)

    with pytest.raises(RuntimeError, match="source failed"):
        store.put(BrokenSource())  # type: ignore[arg-type]

    assert not any(path.name.startswith(".upload-") for path in root.rglob("*"))


def test_local_blob_store_rejects_symlinked_root_and_existing_parent(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    (tmp_path / "root-link").symlink_to(real_root, target_is_directory=True)
    with pytest.raises(Exception, match="symlink"):
        LocalBlobStore(tmp_path / "root-link")

    parent = tmp_path / "parent"
    parent.mkdir()
    (tmp_path / "parent-link").symlink_to(parent, target_is_directory=True)
    with pytest.raises(Exception, match="symlink"):
        LocalBlobStore(tmp_path / "parent-link" / "blobs")


@pytest.mark.parametrize("root", ["/", "//", "////", "/./", "/tmp/.."])
def test_local_blob_store_rejects_all_system_root_aliases(root: str) -> None:
    with pytest.raises(BlobSecurityError, match="root"):
        LocalBlobStore(root)


def test_local_blob_store_rejects_parent_replacement_without_following_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "blobs"
    store = LocalBlobStore(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    prefix = "a" * 16
    store._new_key = lambda: f"{prefix}/{'b' * 32}"  # type: ignore[method-assign]
    (root / prefix).symlink_to(outside, target_is_directory=True)

    with pytest.raises(Exception, match="symlink|safe"):
        store.put(io.BytesIO(b"must not escape"))
    assert list(outside.iterdir()) == []


def test_local_blob_store_reaps_only_stale_private_upload_files(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    store = LocalBlobStore(root, stale_upload_ttl_seconds=60)
    stale = root / ".upload-stale"
    fresh = root / ".upload-fresh"
    stale.write_bytes(b"old")
    fresh.write_bytes(b"new")
    old_time = time.time() - 3600
    os.utime(stale, (old_time, old_time))

    assert store.reap_stale_uploads(ttl_seconds=60) == 1
    assert not stale.exists()
    assert fresh.exists()


def test_local_blob_store_iterates_only_published_opaque_objects(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    store = LocalBlobStore(root)
    stored = store.put(io.BytesIO(b"published"))
    (root / ".upload-crashed").write_bytes(b"temporary")
    invalid_bucket = root / ("a" * 16)
    invalid_bucket.mkdir()
    (invalid_bucket / "not-an-opaque-key").write_bytes(b"invalid")

    objects = list(store.iter_objects())

    assert [obj.storage_key for obj in objects] == [stored.storage_key]
    assert objects[0].byte_size == stored.byte_size
    assert objects[0].modified_at.tzinfo is not None
