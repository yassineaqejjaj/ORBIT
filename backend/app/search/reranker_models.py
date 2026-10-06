"""Cross-encoder rerankers usable with fastembed (docs/AI_CONTEXT_ENGINEERING.md §B2).

The default model is **multilingual and permissively licensed**:
``cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`` (Apache-2.0, mMARCO — 14 languages incl. French,
ONNX export ``onnx/model.onnx``, ~470 MB, HF commit ``1427fd65`` when pinned). It is not in the
fastembed catalogue, so it is registered as a custom model before loading. ``jinaai/jina-reranker-v2-base-
multilingual`` (the former default) is **CC-BY-NC-4.0** — not permissive, hence no longer the default.

``docker/preload_models.py`` duplicates :data:`CUSTOM_MODELS` (it runs before the application code is
copied into the image): keep both in sync.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("orbit.search.reranker")

DEFAULT_RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

#: Licences accepted for a reranker baked into the images (``ORBIT_RERANKER_MODEL``).
PERMISSIVE_LICENSES = frozenset({"apache-2.0", "mit", "bsd-3-clause"})

#: model -> registration kwargs of ``TextCrossEncoder.add_custom_model``.
CUSTOM_MODELS: dict[str, dict[str, Any]] = {
    DEFAULT_RERANKER_MODEL: {
        "model_file": "onnx/model.onnx",
        "license": "apache-2.0",
        "size_in_gb": 0.47,
        "description": "Multilingual mMARCO MiniLM-L12 cross-encoder (FR/EN and 12 other languages).",
    },
}


def ensure_registered(model_name: str) -> None:
    """Register ``model_name`` with fastembed when it is one of :data:`CUSTOM_MODELS` (idempotent)."""
    spec = CUSTOM_MODELS.get(model_name)
    if spec is None:
        return
    from fastembed.common.model_description import ModelSource
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    if any(m.get("model") == model_name for m in TextCrossEncoder.list_supported_models()):
        return
    TextCrossEncoder.add_custom_model(model=model_name, sources=ModelSource(hf=model_name), **spec)
    logger.debug("Custom cross-encoder %s registered with fastembed", model_name)


def license_of(model_name: str) -> str | None:
    """Licence of a known model (custom registry, then the fastembed catalogue)."""
    if model_name in CUSTOM_MODELS:
        return str(CUSTOM_MODELS[model_name]["license"])
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
    except ImportError:
        return None
    for model in TextCrossEncoder.list_supported_models():
        if model.get("model") == model_name:
            return model.get("license")
    return None


__all__ = [
    "CUSTOM_MODELS",
    "DEFAULT_RERANKER_MODEL",
    "PERMISSIVE_LICENSES",
    "ensure_registered",
    "license_of",
]
