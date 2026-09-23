"""Local object store."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.storage.object_store import (
    InvalidObjectKeyError,
    LocalObjectStore,
    ObjectNotFoundError,
    make_key,
    safe_filename,
    sha256_bytes,
)


async def test_put_get_delete(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    key = make_key(uuid.uuid4(), uuid.uuid4(), 1, "Compte rendu Comité.PDF")
    assert key.endswith("/v1/compte-rendu-comite.pdf")
    stored = await store.put(key, b"%PDF-1.7 contenu")
    assert stored.size_bytes == 16
    assert stored.sha256 == sha256_bytes(b"%PDF-1.7 contenu")
    assert await store.exists(key)
    assert await store.get(key) == b"%PDF-1.7 contenu"
    assert await store.size(key) == 16
    assert await store.sha256(key) == stored.sha256
    assert await store.delete(key)
    assert not await store.delete(key)
    with pytest.raises(ObjectNotFoundError):
        await store.get(key)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("key", ["../etc/passwd", "/abs/path", "a//b", "a/../b", "a/b c", ""])
async def test_invalid_keys(tmp_path: Path, key: str) -> None:
    store = LocalObjectStore(tmp_path)
    with pytest.raises(InvalidObjectKeyError):
        await store.put(key, b"x")


def test_safe_filename() -> None:
    assert safe_filename("../../Évaluation finale.docx") == "evaluation-finale.docx"
    assert safe_filename(None) == "fichier"
    assert safe_filename("README") == "readme"
