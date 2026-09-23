"""Object storage for original files (ARCHITECTURE §1: volume ``orbit_objects`` on ``/data/objects``).

Keys are relative POSIX paths (``<project_id>/<document_id>/v<version>/<filename>``, see
:func:`make_key`). Writes are atomic (temporary file + ``os.replace``). All public methods are async
and run blocking I/O in a worker thread. An S3 backend can implement the same :class:`ObjectStore`
protocol later.
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
from typing import Protocol

from slugify import slugify

from app.config import settings

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


_store: LocalObjectStore | None = None


def get_object_store() -> LocalObjectStore:
    global _store
    if _store is None:
        _store = LocalObjectStore(settings.object_store_path)
    return _store


def set_object_store(store: LocalObjectStore | None) -> None:
    """Override the process-wide store (tests)."""
    global _store
    _store = store
