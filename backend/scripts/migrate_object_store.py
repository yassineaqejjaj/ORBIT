"""Copy the objects of a local volume to the S3 backend (docs/OBJECT_STORAGE.md).

    ORBIT_OBJECT_STORE_S3_BUCKET=... uv run python -m scripts.migrate_object_store --dry-run
    ORBIT_OBJECT_STORE_S3_BUCKET=... uv run python -m scripts.migrate_object_store

The S3 target comes from the ``ORBIT_OBJECT_STORE_S3_*`` variables, the source from ``--source`` (default
``ORBIT_OBJECT_STORE_PATH``). Idempotent: an object already in S3 with the same SHA-256 is skipped, so the
script can be re-run to catch up. Nothing is ever deleted from either side. Exit code 1 if any copy failed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import Settings
from app.storage.object_store import (
    InvalidObjectKeyError,
    LocalObjectStore,
    ObjectNotFoundError,
    ObjectStore,
    ObjectStoreError,
    S3ObjectStore,
    build_object_store,
    sha256_bytes,
)


def local_keys(root: Path) -> list[str]:
    """Keys of every stored file (temporary ``.tmp-*`` files of interrupted writes excluded)."""
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.name.startswith(".tmp-")
    )


async def migrate(source: LocalObjectStore, target: ObjectStore, *, dry_run: bool = False) -> dict[str, int]:
    counts = {"copied": 0, "skipped": 0, "failed": 0}
    for key in local_keys(source.root):
        try:
            data = await source.get(key)
            try:
                if sha256_bytes(await target.get(key)) == sha256_bytes(data):
                    counts["skipped"] += 1
                    continue
            except ObjectNotFoundError:
                pass
            if not dry_run:
                await target.put(key, data)
                if sha256_bytes(await target.get(key)) != sha256_bytes(data):
                    raise ObjectStoreError("checksum mismatch after copy")
            counts["copied"] += 1
        except (ObjectStoreError, InvalidObjectKeyError, OSError) as exc:
            counts["failed"] += 1
            print(f"FAILED {key}: {exc}", file=sys.stderr)
    return counts


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--source", help="local volume (default: ORBIT_OBJECT_STORE_PATH)")
    parser.add_argument("--dry-run", action="store_true", help="list what would be copied, write nothing")
    args = parser.parse_args(argv)
    settings = Settings(object_store_backend="s3")  # refuses a missing bucket / half-set keys
    target = build_object_store(settings)
    assert isinstance(target, S3ObjectStore)
    target.prepare()
    source = LocalObjectStore(args.source or settings.object_store_path)
    counts = await migrate(source, target, dry_run=args.dry_run)
    label = "would copy" if args.dry_run else "copied"
    print(f"{label} {counts['copied']}, already in S3 {counts['skipped']}, failed {counts['failed']}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
