"""Build-time download of the fastembed models into FASTEMBED_CACHE_PATH (offline runtime)."""

from __future__ import annotations

import os
import sys

#: Same registry as ``app/search/reranker_models.py`` (this script runs before the app code is copied).
CUSTOM_RERANKERS = {
    "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1": {
        "model_file": "onnx/model.onnx",
        "license": "apache-2.0",
        "size_in_gb": 0.47,
        "description": "Multilingual mMARCO MiniLM-L12 cross-encoder.",
    },
}


def main() -> int:
    cache_dir = os.environ.get("FASTEMBED_CACHE_PATH", "/opt/models")
    model_name = os.environ.get(
        "ORBIT_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )

    from fastembed import TextEmbedding

    supported = {m["model"] for m in TextEmbedding.list_supported_models()}
    if model_name not in supported:
        print(f"[preload] unsupported fastembed model: {model_name}", file=sys.stderr)
        return 1
    print(f"[preload] downloading embedding model {model_name} -> {cache_dir}")
    embedder = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
    vector = next(iter(embedder.embed(["Vérification du modèle d'embeddings ORBIT."])))
    print(f"[preload] ok, dim={len(vector)}")

    if os.environ.get("PRELOAD_RERANKER", "true").lower() in {"1", "true", "yes"}:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        reranker_name = os.environ.get("ORBIT_RERANKER_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
        spec = CUSTOM_RERANKERS.get(reranker_name)
        if spec is not None and not any(
            m.get("model") == reranker_name for m in TextCrossEncoder.list_supported_models()
        ):
            from fastembed.common.model_description import ModelSource

            TextCrossEncoder.add_custom_model(
                model=reranker_name, sources=ModelSource(hf=reranker_name), **spec
            )
        print(f"[preload] downloading reranker {reranker_name}")
        encoder = TextCrossEncoder(model_name=reranker_name, cache_dir=cache_dir)
        scores = list(
            encoder.rerank("Quelle base de données ?", ["PostgreSQL a été retenu.", "Budget marketing."])
        )
        print(f"[preload] reranker ok, scores={[round(x, 2) for x in scores]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
