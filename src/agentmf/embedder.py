"""Pluggable text-embedding adapters for AgentMakefile skill matching.

Provides three things:

  - `Embedder` protocol: anything that maps strings to fixed-dim L2-
    normalised float32 vectors.
  - `HashEmbedder`: a deterministic, zero-extra-deps fallback that
    feature-hashes lowercase unigrams + bigrams. Useful for tests and
    as a baseline; NOT semantically rich.
  - `SentenceTransformerEmbedder`: lazy-imports
    `sentence_transformers` (installed via the `embedding` extra). The
    production choice for semantic matching.
  - `get_default_embedder()`: prefers SentenceTransformerEmbedder when
    its dependency is importable, otherwise returns HashEmbedder.

The compiler stays in pure-python by default; semantic matching is
opt-in via `pip install agentmf[embedding]`.
"""

from __future__ import annotations

import hashlib
import re
from typing import List, Optional, Protocol, Sequence

import numpy as np

DEFAULT_EMBEDDING_DIM = 384
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


class Embedder(Protocol):
    """Map text(s) to L2-normalised float32 vectors of shape (dim,) or
    (n, dim). All implementations MUST be deterministic given identical
    input (per-model-version) so compile output is reproducible.
    """

    @property
    def dim(self) -> int: ...

    @property
    def name(self) -> str: ...

    def embed(self, text: str) -> np.ndarray: ...

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray: ...


def _l2_normalise(vec: np.ndarray) -> np.ndarray:
    if vec.ndim == 1:
        norm = float(np.linalg.norm(vec))
        if norm == 0.0:
            return vec.astype(np.float32, copy=False)
        return (vec / norm).astype(np.float32, copy=False)
    norms = np.linalg.norm(vec, axis=-1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return (vec / norms).astype(np.float32, copy=False)


class HashEmbedder:
    """Deterministic feature-hashing embedder. No external dependencies
    beyond numpy. Maps each token (unigram + bigram) to two positions
    via two hash seeds (signed-hash trick) and accumulates a sparse
    vector, then L2-normalises. Output is reproducible across runs
    because Python's `hashlib.md5` is deterministic.

    Semantically poor — two paraphrases that share no tokens
    ("brainstorm ideas" vs "explore creative directions") will not be
    close — but the architecture wired around it is correct and tests
    can use it without pulling torch.
    """

    def __init__(self, dim: int = DEFAULT_EMBEDDING_DIM) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self._dim = int(dim)

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return f"hash:{self._dim}"

    @staticmethod
    def _tokens(text: str) -> List[str]:
        return [tok.lower() for tok in _TOKEN_PATTERN.findall(text or "")]

    @staticmethod
    def _ngrams(tokens: List[str]) -> List[str]:
        unigrams = list(tokens)
        bigrams = [f"{a}\x1f{b}" for a, b in zip(tokens, tokens[1:])]
        return unigrams + bigrams

    def _hash_to_indices(self, feature: str) -> tuple[int, int]:
        digest = hashlib.md5(feature.encode("utf-8"), usedforsecurity=False).digest()
        primary = int.from_bytes(digest[:8], "big") % self._dim
        sign = 1 if (digest[8] & 1) == 0 else -1
        return primary, sign

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self._dim, dtype=np.float32)
        tokens = self._tokens(text)
        if not tokens:
            return vec
        for feature in self._ngrams(tokens):
            idx, sign = self._hash_to_indices(feature)
            vec[idx] += sign
        return _l2_normalise(vec)

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        return np.stack([self.embed(text) for text in texts]).astype(np.float32, copy=False)


class SentenceTransformerEmbedder:
    """Real semantic embeddings via `sentence_transformers`. Lazy-import
    so installing `agentmf` without the `embedding` extra still loads
    this file. Raises ImportError with a helpful message when the dep
    isn't installed and the embedder is actually used.
    """

    DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(self, model: Optional[str] = None) -> None:
        self._model_name = model or self.DEFAULT_MODEL
        self._model = None  # type: ignore[assignment]
        self._cached_dim: Optional[int] = None

    @property
    def name(self) -> str:
        return f"st:{self._model_name}"

    def _load(self):  # type: ignore[no-untyped-def]
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is not installed. Install with "
                "`pip install agentmf[embedding]` to use "
                "SentenceTransformerEmbedder, or fall back to HashEmbedder."
            ) from exc
        self._model = SentenceTransformer(self._model_name)
        return self._model

    @property
    def dim(self) -> int:
        if self._cached_dim is not None:
            return self._cached_dim
        model = self._load()
        dim = int(model.get_sentence_embedding_dimension())
        self._cached_dim = dim
        return dim

    def embed(self, text: str) -> np.ndarray:
        model = self._load()
        vec = np.asarray(model.encode(text, normalize_embeddings=True), dtype=np.float32)
        # Defensive: re-normalise in case the model returns un-normalised vectors.
        return _l2_normalise(vec.reshape(-1))

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        model = self._load()
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        matrix = np.asarray(
            model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True),
            dtype=np.float32,
        )
        return _l2_normalise(matrix)


def get_default_embedder(dim: int = DEFAULT_EMBEDDING_DIM) -> Embedder:
    """Return SentenceTransformerEmbedder when the dep is importable;
    otherwise a HashEmbedder so the rest of the stack still works.
    """
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return HashEmbedder(dim=dim)
    return SentenceTransformerEmbedder()
