"""Build-time download of the fastembed models into FASTEMBED_CACHE_PATH (offline runtime).

Models are fetched at a pinned Hugging Face revision (reproducible, auditable builds): the snapshot is
downloaded with ``revision=<sha>`` and ``refs/main`` is pointed at that sha, so fastembed's offline
lookup (``HF_HUB_OFFLINE=1`` at runtime) resolves exactly the pinned files.

Environment:
  ORBIT_EMBEDDING_MODEL / ORBIT_EMBEDDING_MODEL_REVISION   embedding model and its HF commit sha
  PRELOAD_RERANKER                                         true to also bake the cross-encoder
  ORBIT_RERANKER_MODEL / ORBIT_RERANKER_MODEL_REVISION     cross-encoder and its HF commit sha
  ALLOW_NONCOMMERCIAL_MODELS                               true to accept a non-commercial licence
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

#: Licences that forbid commercial use: refused unless explicitly allowed (THIRD_PARTY_NOTICES.md).
NONCOMMERCIAL_LICENCES = frozenset({"cc-by-nc-4.0", "cc-by-nc-sa-4.0", "cc-by-nc-nd-4.0"})


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _describe(models: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for model in models:
        if model["model"] == name:
            return model
    raise SystemExit(f"[preload] model not supported by fastembed: {name}")


def _pin_snapshot(description: dict[str, Any], revision: str, cache_dir: str) -> None:
    """Download the HF snapshot at ``revision`` and make it the one fastembed resolves offline."""
    from huggingface_hub import snapshot_download

    sources = description.get("sources") or {}
    repo = sources.get("hf") if isinstance(sources, dict) else None
    if not repo:
        print(f"[preload] {description['model']}: no Hugging Face source, revision pin skipped")
        return
    if not revision:
        raise SystemExit(f"[preload] a pinned revision is required for {repo}")
    patterns = [
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "preprocessor_config.json",
        description["model_file"],
        *description.get("additional_files", []),
    ]
    path = Path(snapshot_download(repo_id=repo, revision=revision, allow_patterns=patterns, cache_dir=cache_dir))
    refs = Path(cache_dir) / f"models--{repo.replace('/', '--')}" / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(revision, encoding="utf-8")
    model_file = path / description["model_file"]
    digest = hashlib.sha256(model_file.read_bytes()).hexdigest()
    print(f"[preload] {repo}@{revision}: {description['model_file']} sha256={digest}")


def _check_licence(description: dict[str, Any]) -> None:
    licence = str(description.get("license") or "unknown").lower()
    print(f"[preload] {description['model']}: licence {licence}")
    if licence in NONCOMMERCIAL_LICENCES and not _truthy(os.environ.get("ALLOW_NONCOMMERCIAL_MODELS")):
        raise SystemExit(
            f"[preload] {description['model']} is licensed {licence} (non-commercial). Choose a permissive "
            "model or set ALLOW_NONCOMMERCIAL_MODELS=true once a commercial licence has been obtained."
        )


def main() -> int:
    cache_dir = os.environ.get("FASTEMBED_CACHE_PATH", "/opt/models")
    model_name = os.environ.get("ORBIT_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    model_revision = os.environ.get("ORBIT_EMBEDDING_MODEL_REVISION", "")

    from fastembed import TextEmbedding

    description = _describe(TextEmbedding.list_supported_models(), model_name)
    _check_licence(description)
    _pin_snapshot(description, model_revision, cache_dir)
    # fastembed checks the local cache first: it now loads the pinned snapshot without re-resolving "main".
    os.environ["HF_HUB_OFFLINE"] = "1"
    embedder = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
    vector = next(iter(embedder.embed(["Vérification du modèle d'embeddings ORBIT."])))
    print(f"[preload] embedding model ok, dim={len(vector)}")

    if _truthy(os.environ.get("PRELOAD_RERANKER")):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        reranker_name = os.environ.get("ORBIT_RERANKER_MODEL", "BAAI/bge-reranker-base")
        reranker_revision = os.environ.get("ORBIT_RERANKER_MODEL_REVISION", "")
        reranker = _describe(TextCrossEncoder.list_supported_models(), reranker_name)
        _check_licence(reranker)
        os.environ.pop("HF_HUB_OFFLINE", None)
        _pin_snapshot(reranker, reranker_revision, cache_dir)
        os.environ["HF_HUB_OFFLINE"] = "1"
        scores = list(TextCrossEncoder(model_name=reranker_name, cache_dir=cache_dir).rerank("test", ["test"]))
        print(f"[preload] reranker ok ({len(scores)} score)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
