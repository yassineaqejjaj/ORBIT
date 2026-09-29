"""Embedding providers.

Contract (ARCHITECTURE §1, §6, §9):

* ``ORBIT_EMBEDDING_PROVIDER``:
  - ``fastembed`` — local ONNX model ``ORBIT_EMBEDDING_MODEL`` (baked in the Docker image, cache
    directory ``settings.model_cache_dir`` or ``FASTEMBED_CACHE_PATH``); inference runs in a thread
    (``asyncio.to_thread``) so the event loop is never blocked;
  - ``openai`` — OpenAI-compatible ``POST {ORBIT_EMBEDDING_BASE_URL}/embeddings`` (TEI, vLLM, LiteLLM),
    bearer ``ORBIT_EMBEDDING_API_KEY``;
  - ``hash`` — deterministic, dependency-free vectors for tests (feature hashing of normalised
    word unigrams + bigrams with accent folding, L2-normalised). Lexically meaningful: texts sharing
    words have a positive cosine similarity.
* Vectors have exactly ``ORBIT_EMBEDDING_DIM`` dimensions and are L2-normalised (cosine similarity
  == dot product), matching the ``knn_vector`` mapping (``cosinesimil``).
* ``get_embedder()`` returns a process-wide singleton (model loaded once). Loading a local model is
  blocking: async callers should use :func:`aget_embedder` (or ``asyncio.to_thread(get_embedder)``).
* :func:`check_embedder` embeds a probe and validates the dimension (called at startup through
  ``app.search.opensearch.ensure_indices``).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
import unicodedata
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

import httpx
import numpy as np

from app.config import settings

logger = logging.getLogger("orbit.embeddings")

FASTEMBED_BATCH_SIZE = 32
OPENAI_BATCH_SIZE = 64
OPENAI_MAX_RETRIES = 3
#: Characters kept per text before embedding (models truncate anyway; avoids huge payloads).
MAX_EMBED_CHARS = 8000
PROBE_TEXT = "Vérification du modèle d'embeddings ORBIT."


class EmbeddingError(RuntimeError):
    """The embedding provider failed or returned unusable vectors."""


class EmbeddingDimensionError(EmbeddingError):
    """The provider's vector size does not match ``ORBIT_EMBEDDING_DIM``."""


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


# --- Helpers --------------------------------------------------------------------------------------


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation (zero rows stay zero)."""
    array = np.asarray(matrix, dtype=np.float32)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return array / norms


def _prepare(text: str) -> str:
    cleaned = (text or "").strip()
    return cleaned[:MAX_EMBED_CHARS] if cleaned else " "


def _dimension_error(provider: str, model: str, actual: int) -> EmbeddingDimensionError:
    return EmbeddingDimensionError(
        f"Le modèle d'embeddings « {model} » ({provider}) produit des vecteurs de dimension {actual}, "
        f"mais ORBIT_EMBEDDING_DIM={settings.embedding_dim}. Corrigez ORBIT_EMBEDDING_DIM "
        "(et recréez les index OpenSearch) ou choisissez un modèle compatible."
    )


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two vectors (works for non-normalised inputs)."""
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


# --- Hash embedder (tests, offline fallback) ---------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+")
#: Very frequent French/English function words: ignored as unigrams (still used inside bigrams).
_STOPWORDS = frozenset(
    """
    a au aux avec ce ces cet cette dans de des du elle en et est il ils je la le les leur lui ma mais me
    mes meme moi mon ne nos notre nous on ou par pas pour qu que qui sa se ses son sont sur ta te tes toi
    ton tu un une vos votre vous y d l j m n s t c the of and to in is it for on be as at by an or
    """.split()
)


def fold_accents(text: str) -> str:
    """Lower-case and strip diacritics (``Décision`` → ``decision``)."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _light_stem(token: str) -> str:
    """Tiny French/English plural folding so that ``décisions`` and ``décision`` share a feature."""
    if len(token) > 4 and token.endswith(("s", "x")) and not token.endswith("ss"):
        return token[:-1]
    return token


def hash_tokens(text: str) -> list[str]:
    return [_light_stem(t) for t in _WORD.findall(fold_accents(text))]


class HashEmbedder:
    """Deterministic feature-hashing embedder (unigrams weight 1, bigrams weight 0.5, signed buckets)."""

    def __init__(self, dim: int) -> None:
        if dim <= 0:
            raise ValueError("La dimension des embeddings doit être positive")
        self.dim = dim
        self.model_name = f"hash-bow-{dim}"

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        return value % self.dim, (1.0 if (value >> 63) & 1 else -1.0)

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        tokens = hash_tokens(text)
        for token in tokens:
            if token in _STOPWORDS or len(token) < 2:
                continue
            index, sign = self._bucket(f"u:{token}")
            vector[index] += sign
        for left, right in zip(tokens, tokens[1:], strict=False):
            index, sign = self._bucket(f"b:{left}_{right}")
            vector[index] += 0.5 * sign
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            # Empty / stop-word-only text: a stable non-zero vector keeps kNN well defined.
            index, sign = self._bucket("empty")
            vector[index] = sign
            return vector
        return vector / norm

    def embed_sync(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text).tolist() for text in texts]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self.embed_sync(list(texts))

    async def embed_query(self, text: str) -> list[float]:
        return self.embed_sync([text])[0]


# --- fastembed (local ONNX) -----------------------------------------------------------------------------


def _fastembed_cache_dir() -> str | None:
    return settings.model_cache_dir or os.environ.get("FASTEMBED_CACHE_PATH") or None


class FastEmbedEmbedder:
    """Local ONNX embeddings with fastembed. The model is loaded in ``__init__`` (blocking)."""

    def __init__(self, model_name: str, dim: int, cache_dir: str | None = None) -> None:
        from fastembed import TextEmbedding

        self.model_name = model_name
        self.dim = dim
        supported = {m.get("model"): m for m in TextEmbedding.list_supported_models()}
        info = supported.get(model_name)
        if info is None:
            raise EmbeddingError(
                f"Modèle d'embeddings « {model_name} » non pris en charge par fastembed "
                "(vérifiez ORBIT_EMBEDDING_MODEL)."
            )
        declared_dim = info.get("dim")
        if isinstance(declared_dim, int) and declared_dim != dim:
            raise _dimension_error("fastembed", model_name, declared_dim)
        try:
            self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        except Exception as exc:
            raise EmbeddingError(
                f"Impossible de charger le modèle d'embeddings « {model_name} » "
                f"(cache : {cache_dir or 'par défaut'}) : {exc}"
            ) from exc
        # Serialise inference: the API and the worker are separate processes and a single ONNX
        # session already uses every core; parallel calls would only thrash the CPU.
        self._lock = threading.Lock()
        probe = self._embed_sync([PROBE_TEXT])
        if len(probe[0]) != dim:
            raise _dimension_error("fastembed", model_name, len(probe[0]))

    def _embed_sync(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        prepared = [_prepare(t) for t in texts]
        with self._lock:
            if query and hasattr(self._model, "query_embed"):
                raw = list(self._model.query_embed(prepared))
            else:
                raw = list(self._model.embed(prepared, batch_size=FASTEMBED_BATCH_SIZE))
        if not raw:
            return []
        return l2_normalize(np.vstack(raw)).tolist()

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        items = list(texts)
        if not items:
            return []
        return await asyncio.to_thread(self._embed_sync, items)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await asyncio.to_thread(self._embed_sync, [text], query=True)
        return vectors[0]


# --- OpenAI-compatible HTTP API (TEI, vLLM, LiteLLM, OpenAI) -------------------------------------------------


def _embeddings_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/embeddings"):
        return base
    if re.search(r"/v\d+$", base):
        return f"{base}/embeddings"
    return f"{base}/v1/embeddings"


class OpenAIEmbedder:
    """``POST /v1/embeddings`` on an OpenAI-compatible server."""

    def __init__(self, base_url: str, model_name: str, dim: int, api_key: str = "") -> None:
        if not base_url:
            raise EmbeddingError(
                "ORBIT_EMBEDDING_BASE_URL est requis avec ORBIT_EMBEDDING_PROVIDER=openai"
            )
        self.model_name = model_name
        self.dim = dim
        self.url = _embeddings_url(base_url)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._headers = headers
        self._clients: dict[int, httpx.AsyncClient] = {}

    def _client(self) -> httpx.AsyncClient:
        # One client per event loop (the API and tests may run several loops over time).
        loop_id = id(asyncio.get_running_loop())
        client = self._clients.get(loop_id)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(headers=self._headers, timeout=httpx.Timeout(60.0, connect=5.0))
            self._clients[loop_id] = client
        return client

    async def _post(self, inputs: list[str]) -> list[list[float]]:
        body: dict[str, Any] = {"model": self.model_name, "input": inputs}
        last_error: Exception | None = None
        for attempt in range(1, OPENAI_MAX_RETRIES + 1):
            try:
                response = await self._client().post(self.url, json=body)
                if response.status_code >= 500 or response.status_code == 429:
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code}", request=response.request, response=response
                    )
                response.raise_for_status()
                payload = response.json()
                data = sorted(payload["data"], key=lambda item: item.get("index", 0))
                vectors = [item["embedding"] for item in data]
                if len(vectors) != len(inputs):
                    raise EmbeddingError(
                        f"Réponse d'embeddings incomplète ({len(vectors)} vecteurs pour {len(inputs)} textes)"
                    )
                return vectors
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                last_error = exc
                if status < 500 and status != 429:
                    raise EmbeddingError(
                        f"Le service d'embeddings a refusé la requête (HTTP {status}) : "
                        f"{exc.response.text[:300]}"
                    ) from exc
            except (httpx.TransportError, ValueError, KeyError, TypeError) as exc:
                last_error = exc
            if attempt < OPENAI_MAX_RETRIES:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
        raise EmbeddingError(f"Service d'embeddings indisponible ({self.url}) : {last_error}")

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        items = [_prepare(t) for t in texts]
        vectors: list[list[float]] = []
        for start in range(0, len(items), OPENAI_BATCH_SIZE):
            batch = await self._post(items[start : start + OPENAI_BATCH_SIZE])
            for vector in batch:
                if len(vector) != self.dim:
                    raise _dimension_error("openai", self.model_name, len(vector))
            vectors.extend(batch)
        if not vectors:
            return []
        return l2_normalize(np.asarray(vectors, dtype=np.float32)).tolist()

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()


# --- Singleton ------------------------------------------------------------------------------------------

_embedder: Embedder | None = None
_embedder_lock = threading.Lock()


def build_embedder() -> Embedder:
    """Instantiate the embedder configured by ``ORBIT_EMBEDDING_PROVIDER`` (not cached)."""
    provider = settings.embedding_provider
    if provider == "hash":
        return HashEmbedder(settings.embedding_dim)
    if provider == "openai":
        return OpenAIEmbedder(
            settings.embedding_base_url,
            settings.embedding_model,
            settings.embedding_dim,
            settings.embedding_api_key,
        )
    if provider == "fastembed":
        return FastEmbedEmbedder(settings.embedding_model, settings.embedding_dim, _fastembed_cache_dir())
    raise EmbeddingError(f"Fournisseur d'embeddings inconnu : {provider}")


def get_embedder() -> Embedder:
    """Return the configured embedder singleton (see module docstring). May block on first call."""
    global _embedder
    if _embedder is not None:
        return _embedder
    with _embedder_lock:
        if _embedder is None:
            embedder = build_embedder()
            logger.info(
                "Embedding provider ready: %s (model=%s, dim=%d)",
                settings.embedding_provider,
                embedder.model_name,
                embedder.dim,
            )
            _embedder = embedder
    return _embedder


async def aget_embedder() -> Embedder:
    """Async-friendly :func:`get_embedder` (loads the model in a thread on first call)."""
    if _embedder is not None:
        return _embedder
    return await asyncio.to_thread(get_embedder)


def set_embedder(embedder: Embedder | None) -> None:
    """Override the process-wide embedder (tests)."""
    global _embedder
    _embedder = embedder


async def check_embedder() -> dict[str, Any]:
    """Embed a probe text and validate the vector size against ``ORBIT_EMBEDDING_DIM``."""
    embedder = await aget_embedder()
    vector = await embedder.embed_query(PROBE_TEXT)
    if len(vector) != settings.embedding_dim:
        raise _dimension_error(settings.embedding_provider, embedder.model_name, len(vector))
    return {"provider": settings.embedding_provider, "model": embedder.model_name, "dim": len(vector)}


def embedding_model_label() -> str:
    """Model name shown in ``/meta`` and context packages (without loading the model)."""
    if _embedder is not None:
        return _embedder.model_name
    if settings.embedding_provider == "hash":
        return f"hash-bow-{settings.embedding_dim}"
    return settings.embedding_model
