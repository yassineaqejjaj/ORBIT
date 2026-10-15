"""Object storage for original files (ARCHITECTURE §1: volume ``orbit_objects`` on ``/data/objects``).

Keys are relative POSIX paths (``<project_id>/<document_id>/v<version>/<filename>``, see
:func:`make_key`). Two backends implement the :class:`ObjectStore` protocol, chosen by
``ORBIT_OBJECT_STORE_BACKEND``: :class:`LocalObjectStore` (default; atomic writes: temporary file +
``os.replace``) and :class:`S3ObjectStore` (S3 or any S3-compatible service). All public methods are
async and run blocking I/O in a worker thread; both raise :class:`ObjectNotFoundError` for a missing
key and :class:`ObjectStoreError` for any other backend failure.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from slugify import slugify

from app.config import Settings, settings

_KEY_PART = re.compile(r"^[A-Za-z0-9._\-]+$")


class ObjectStoreError(Exception):
    pass


class ObjectNotFoundError(ObjectStoreError, FileNotFoundError):
    pass


class InvalidObjectKeyError(ObjectStoreError, ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    sha256: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def safe_filename(filename: str | None, default: str = "fichier") -> str:
    """Filesystem-safe file name preserving the extension (``Compte rendu.PDF`` → ``compte-rendu.pdf``)."""
    name = PurePosixPath((filename or "").replace("\\", "/")).name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    clean_stem = slugify(stem, max_length=120) or default
    clean_ext = re.sub(r"[^a-z0-9]", "", ext.lower())[:12]
    return f"{clean_stem}.{clean_ext}" if clean_ext else clean_stem


def make_key(
    project_id: uuid.UUID | str, document_id: uuid.UUID | str, version: int, filename: str | None
) -> str:
    return f"{project_id}/{document_id}/v{int(version)}/{safe_filename(filename)}"


def validate_key(key: str) -> str:
    if not key or key.startswith("/") or "\\" in key:
        raise InvalidObjectKeyError(f"Clé d'objet invalide : {key!r}")
    parts = key.split("/")
    if any(part in ("", ".", "..") or not _KEY_PART.match(part) for part in parts):
        raise InvalidObjectKeyError(f"Clé d'objet invalide : {key!r}")
    return key


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes) -> StoredObject: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> bool: ...

    async def exists(self, key: str) -> bool: ...

    async def size(self, key: str) -> int: ...

    def prepare(self) -> None:
        """Make the store usable at start-up (create the directory, check the bucket); may raise."""
        ...


class LocalObjectStore:
    """Filesystem implementation rooted at ``root``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    # -- paths ---------------------------------------------------------------------------------------
    def path_for(self, key: str) -> Path:
        """Absolute path of ``key`` (validated, guaranteed to stay under ``root``)."""
        path = (self.root / validate_key(key)).resolve()
        if self.root not in path.parents:
            raise InvalidObjectKeyError(f"Clé d'objet invalide : {key!r}")
        return path

    def ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def prepare(self) -> None:
        self.ensure_root()

    # -- sync primitives -------------------------------------------------------------------------------
    def _put_sync(self, key: str, data: bytes) -> StoredObject:
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return StoredObject(key=key, size_bytes=len(data), sha256=sha256_bytes(data))

    def _get_sync(self, key: str) -> bytes:
        path = self.path_for(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(key) from exc

    def _delete_sync(self, key: str) -> bool:
        path = self.path_for(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        # Remove now-empty parent directories up to the root.
        parent = path.parent
        while parent != self.root and self.root in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        return True

    # -- async API ---------------------------------------------------------------------------------------
    async def put(self, key: str, data: bytes) -> StoredObject:
        return await asyncio.to_thread(self._put_sync, key, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get_sync, key)

    async def delete(self, key: str) -> bool:
        return await asyncio.to_thread(self._delete_sync, key)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self.path_for(key).is_file)

    async def size(self, key: str) -> int:
        path = self.path_for(key)
        try:
            return (await asyncio.to_thread(path.stat)).st_size
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(key) from exc

    async def sha256(self, key: str) -> str:
        return sha256_bytes(await self.get(key))


_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


class S3ObjectStore:
    """S3 / S3-compatible implementation (boto3 in worker threads); keys live under ``prefix``."""

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str = "",
        region: str = "",
        access_key: str = "",
        secret_key: str = "",
        prefix: str = "",
        path_style: bool = True,
    ) -> None:
        if not bucket:
            raise ObjectStoreError("Bucket S3 non configuré (ORBIT_OBJECT_STORE_S3_BUCKET).")
        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region or None,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            config=BotoConfig(
                s3={"addressing_style": "path" if path_style else "virtual"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=60,
            ),
        )

    def _name(self, key: str) -> str:
        return self.prefix + validate_key(key)

    def _call(self, operation: str, key: str | None = None, **kwargs: Any) -> Any:
        """One boto3 call; backend errors are normalised (never leaks credentials or endpoint details)."""
        params = {"Bucket": self.bucket, **kwargs}
        if key is not None:
            params["Key"] = self._name(key)
        try:
            return getattr(self._client, operation)(**params)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in _NOT_FOUND_CODES and key is not None:
                raise ObjectNotFoundError(key) from exc
            raise ObjectStoreError(
                f"Stockage S3 : {operation} refusé ou impossible ({code or 'erreur'})"
            ) from exc
        except BotoCoreError as exc:
            raise ObjectStoreError(f"Stockage S3 : {operation} impossible ({type(exc).__name__})") from exc

    def prepare(self) -> None:
        self._call("head_bucket")

    async def put(self, key: str, data: bytes) -> StoredObject:
        await asyncio.to_thread(self._call, "put_object", key, Body=data)
        return StoredObject(key=key, size_bytes=len(data), sha256=sha256_bytes(data))

    async def get(self, key: str) -> bytes:
        def read() -> bytes:
            body = self._call("get_object", key)["Body"]
            try:
                return bytes(body.read())
            except (BotoCoreError, OSError) as exc:
                raise ObjectStoreError(f"Stockage S3 : lecture interrompue ({type(exc).__name__})") from exc
            finally:
                body.close()

        return await asyncio.to_thread(read)

    async def delete(self, key: str) -> bool:
        # S3 deletes are idempotent and do not say whether the key existed: ask first.
        if not await self.exists(key):
            return False
        await asyncio.to_thread(self._call, "delete_object", key)
        return True

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._call, "head_object", key)
        except ObjectNotFoundError:
            return False
        return True

    async def size(self, key: str) -> int:
        head = await asyncio.to_thread(self._call, "head_object", key)
        return int(head["ContentLength"])

    async def sha256(self, key: str) -> str:
        return sha256_bytes(await self.get(key))


def build_object_store(config: Settings) -> ObjectStore:
    """The store selected by ``ORBIT_OBJECT_STORE_BACKEND`` (default: local volume)."""
    if config.object_store_backend == "s3":
        return S3ObjectStore(
            config.object_store_s3_bucket.strip(),
            endpoint_url=config.object_store_s3_endpoint,
            region=config.object_store_s3_region,
            access_key=config.object_store_s3_access_key,
            secret_key=config.object_store_s3_secret_key,
            prefix=config.object_store_s3_prefix,
            path_style=config.object_store_s3_path_style,
        )
    return LocalObjectStore(config.object_store_path)


_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    global _store
    if _store is None:
        _store = build_object_store(settings)
    return _store


def set_object_store(store: ObjectStore | None) -> None:
    """Override the process-wide store (tests)."""
    global _store
    _store = store
