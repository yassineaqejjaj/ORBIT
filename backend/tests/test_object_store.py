"""Object stores: one conformance suite run against the local and the (simulated) S3 backend."""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import boto3
import pytest
from moto import mock_aws
from pydantic import ValidationError

from app.config import Settings
from app.storage.object_store import (
    InvalidObjectKeyError,
    LocalObjectStore,
    ObjectNotFoundError,
    ObjectStore,
    ObjectStoreError,
    S3ObjectStore,
    build_object_store,
    make_key,
    safe_filename,
    sha256_bytes,
)

BUCKET = "orbit-test-bucket"


@pytest.fixture(params=["local", "s3"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[ObjectStore]:
    if request.param == "local":
        yield LocalObjectStore(tmp_path)
        return
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield S3ObjectStore(bucket=BUCKET, region="us-east-1", prefix="orbit/")


async def test_put_get_delete(store: ObjectStore) -> None:
    key = make_key(uuid.uuid4(), uuid.uuid4(), 1, "Compte rendu Comité.PDF")
    assert key.endswith("/v1/compte-rendu-comite.pdf")
    assert not await store.exists(key)
    stored = await store.put(key, b"%PDF-1.7 contenu")
    assert stored.key == key
    assert stored.size_bytes == 16
    assert stored.sha256 == sha256_bytes(b"%PDF-1.7 contenu")
    assert await store.exists(key)
    assert await store.get(key) == b"%PDF-1.7 contenu"
    assert await store.size(key) == 16
    assert await store.delete(key)
    assert not await store.delete(key)
    assert not await store.exists(key)
    with pytest.raises(ObjectNotFoundError):
        await store.get(key)
    with pytest.raises(ObjectNotFoundError):
        await store.size(key)


async def test_put_overwrites_and_keeps_keys_apart(store: ObjectStore) -> None:
    one, other = f"{uuid.uuid4()}/d/v1/a.txt", f"{uuid.uuid4()}/d/v1/a.txt"
    await store.put(one, b"first")
    await store.put(one, b"second version")
    await store.put(other, b"")
    assert await store.get(one) == b"second version"
    assert await store.size(one) == len(b"second version")
    assert await store.get(other) == b""
    assert await store.delete(one)
    assert await store.exists(other)


async def test_not_found_is_a_file_not_found_error(store: ObjectStore) -> None:
    with pytest.raises(FileNotFoundError):
        await store.get("p/d/v1/missing.txt")


@pytest.mark.parametrize("key", ["../etc/passwd", "/abs/path", "a//b", "a/../b", "a/b c", ""])
async def test_invalid_keys(store: ObjectStore, key: str) -> None:
    for call in (store.put(key, b"x"), store.get(key), store.delete(key), store.exists(key), store.size(key)):
        with pytest.raises(InvalidObjectKeyError):
            await call


async def test_local_store_leaves_no_empty_directory(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    key = make_key(uuid.uuid4(), uuid.uuid4(), 1, "a.txt")
    await store.put(key, b"x")
    assert await store.sha256(key) == sha256_bytes(b"x")
    await store.delete(key)
    assert list(tmp_path.iterdir()) == []


async def test_s3_prefix_isolates_keys_and_errors_are_normalised() -> None:
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        prefixed = S3ObjectStore(bucket=BUCKET, region="us-east-1", prefix="env-a")
        bare = S3ObjectStore(bucket=BUCKET, region="us-east-1")
        await prefixed.put("p/d/v1/x.txt", b"x")
        assert not await bare.exists("p/d/v1/x.txt")
        assert await bare.exists("env-a/p/d/v1/x.txt")
        missing_bucket = S3ObjectStore(bucket="no-such-bucket", region="us-east-1")
        with pytest.raises(ObjectStoreError) as excinfo:
            await missing_bucket.put("p/d/v1/x.txt", b"x")
        assert not isinstance(excinfo.value, ObjectNotFoundError)
        with pytest.raises(ObjectStoreError):
            missing_bucket.prepare()


def test_factory_defaults_to_the_local_store(tmp_path: Path) -> None:
    store = build_object_store(Settings(object_store_path=str(tmp_path)))
    assert isinstance(store, LocalObjectStore) and store.root == tmp_path.resolve()


def test_factory_builds_s3_and_refuses_a_missing_bucket() -> None:
    settings = Settings(object_store_backend="s3", object_store_s3_bucket=BUCKET, object_store_s3_prefix="x")
    assert isinstance(build_object_store(settings), S3ObjectStore)
    with pytest.raises(ValidationError, match="ORBIT_OBJECT_STORE_S3_BUCKET"):
        Settings(object_store_backend="s3")
    with pytest.raises(ValidationError, match="ORBIT_OBJECT_STORE_S3_SECRET_KEY"):
        Settings(object_store_backend="s3", object_store_s3_bucket=BUCKET, object_store_s3_access_key="AK")
    with pytest.raises(ValidationError):
        Settings(object_store_backend="gcs")  # type: ignore[arg-type]


def test_safe_filename() -> None:
    assert safe_filename("../../Évaluation finale.docx") == "evaluation-finale.docx"
    assert safe_filename(None) == "fichier"
    assert safe_filename("README") == "readme"


def _load_migration_script() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "scripts" / "migrate_object_store.py"
    spec = importlib.util.spec_from_file_location("migrate_object_store", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_migration_copies_local_objects_to_s3_idempotently(tmp_path: Path) -> None:
    module = _load_migration_script()
    local = LocalObjectStore(tmp_path)
    keys = [make_key(uuid.uuid4(), uuid.uuid4(), 1, name) for name in ("a.txt", "b.pdf")]
    for key, data in zip(keys, (b"alpha", b"beta"), strict=True):
        await local.put(key, data)
    (tmp_path / ".tmp-interrupted").write_bytes(b"partial")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        target = S3ObjectStore(bucket=BUCKET, region="us-east-1")
        assert await module.migrate(local, target, dry_run=True) == {"copied": 2, "skipped": 0, "failed": 0}
        assert not await target.exists(keys[0])  # dry run writes nothing
        assert await module.migrate(local, target) == {"copied": 2, "skipped": 0, "failed": 0}
        assert await target.get(keys[0]) == b"alpha" and await target.get(keys[1]) == b"beta"
        assert await module.migrate(local, target) == {"copied": 0, "skipped": 2, "failed": 0}
        await local.put(keys[0], b"alpha v2")  # changed since the last run: copied again
        assert await module.migrate(local, target) == {"copied": 1, "skipped": 1, "failed": 0}
        assert await local.exists(keys[0])  # the source is never touched
