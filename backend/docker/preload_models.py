"""Build-time download of the fastembed models into FASTEMBED_CACHE_PATH (offline runtime)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    cache_dir = os.environ.get("FASTEMBED_CACHE_PATH", "/opt/models")
    model_name = os.environ.get("ORBIT_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

    from fastembed import TextEmbedding

    supported = {m["model"] for m in TextEmbedding.list_supported_models()}
    if model_name not in supported:
        print(f"[preload] unsupported fastembed model: {model_name}", file=sys.stderr)
        return 1
    print(f"[preload] downloading embedding model {model_name} -> {cache_dir}")
    embedder = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
    vector = next(iter(embedder.embed(["Vérification du modèle d'embeddings ORBIT."])))
    print(f"[preload] ok, dim={len(vector)}")

    if os.environ.get("PRELOAD_RERANKER", "false").lower() in {"1", "true", "yes"}:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        reranker_name = os.environ.get("ORBIT_RERANKER_MODEL", "jinaai/jina-reranker-v2-base-multilingual")
        print(f"[preload] downloading reranker {reranker_name}")
        TextCrossEncoder(model_name=reranker_name, cache_dir=cache_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
