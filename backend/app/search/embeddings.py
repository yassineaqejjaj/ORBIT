"""Embedding providers (interface — implemented by the retrieval teammate).

Contract (ARCHITECTURE §1, §6, §9):

* ``ORBIT_EMBEDDING_PROVIDER``:
  - ``fastembed`` — local ONNX model ``ORBIT_EMBEDDING_MODEL`` (baked in the Docker image, cache
    directory ``settings.model_cache_dir`` or ``FASTEMBED_CACHE_PATH``); inference runs in a thread
    (``asyncio.to_thread``) so the event loop is never blocked;
  - ``openai`` — OpenAI-compatible ``POST {ORBIT_EMBEDDING_BASE_URL}/embeddings`` (TEI, vLLM, LiteLLM),
    bearer ``ORBIT_EMBEDDING_API_KEY``;
  - ``hash`` — deterministic, dependency-free vectors for tests (feature hashing of normalised
    tokens, L2-normalised).
* Vectors have exactly ``ORBIT_EMBEDDING_DIM`` dimensions and are L2-normalised (cosine similarity
  == dot product), matching the ``knn_vector`` mapping (``cosinesimil``).
* ``get_embedder()`` returns a process-wide singleton (model loaded once, lazily).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    model_name: str
    dim: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed passages (batched). Returns one vector per input, same order."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query (may use a query-specific prefix for asymmetric models)."""
        ...


def get_embedder() -> Embedder:
    """Return the configured embedder singleton (see module docstring)."""
    raise NotImplementedError("Le fournisseur d'embeddings n'est pas encore implémenté")
