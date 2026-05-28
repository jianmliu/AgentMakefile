"""Embedding-based skill index.

Builds dense vector representations of every skill in an AgentMakefile
module (using an `Embedder`) and supports cosine-similarity top-K
queries against a free-text request. The corpus text per skill is:

    "{description}\\n\\n{user_intent terms joined}"

so the embedder gets the skill's narrative description first (the
strongest signal) followed by any author-provided routing keywords.

The index is intentionally a flat numpy matrix — at 544 skills × 384
dim (~0.8 MB) cosine is a single matmul and finishes in <1 ms. We can
swap in HNSW/FAISS later if the corpus grows past ~50K skills, but the
current shape doesn't need it.

Persisted indexes are written as a single JSON file with the matrix
encoded as base64 raw float32 bytes — readable text envelope, compact
payload (~25% larger than raw NPZ but no binary tooling needed). The
file records the embedder's `name` so future loads can detect
mismatches and rebuild instead of returning silently-wrong rankings.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np

from agentmf.embedder import Embedder, get_default_embedder
from agentmf.loader import load_source_with_diagnostics
from agentmf.models import AgentMakefileSource

INDEX_FILE_VERSION = 1
DEFAULT_INDEX_PATH = ".agentmf/skills.embed.json"


@dataclass(frozen=True)
class IndexedSkill:
    skill_name: str
    target_name: str
    description: str
    text: str  # the corpus text actually fed to the embedder


@dataclass(frozen=True)
class SkillMatch:
    rank: int
    skill_name: str
    target_name: str
    score: float
    description: str


@dataclass
class SkillIndex:
    embedder: Embedder
    skills: List[IndexedSkill]
    matrix: np.ndarray  # shape (n_skills, dim), L2-normalised rows

    @classmethod
    def from_source(
        cls,
        source: AgentMakefileSource,
        embedder: Optional[Embedder] = None,
    ) -> "SkillIndex":
        emb = embedder or get_default_embedder()
        indexed: List[IndexedSkill] = []
        corpus_texts: List[str] = []
        for skill_name in sorted(source.skills):
            skill = source.skills[skill_name]
            target_name = f"skill.{skill_name}"
            text = _corpus_text_for_skill(skill_name, skill)
            indexed.append(
                IndexedSkill(
                    skill_name=skill_name,
                    target_name=target_name,
                    description=str(skill.description or ""),
                    text=text,
                )
            )
            corpus_texts.append(text)
        if not corpus_texts:
            matrix = np.zeros((0, emb.dim), dtype=np.float32)
        else:
            matrix = emb.embed_batch(corpus_texts)
        return cls(embedder=emb, skills=indexed, matrix=matrix)

    @classmethod
    def from_path(
        cls,
        path: Union[Path, str],
        embedder: Optional[Embedder] = None,
    ) -> "SkillIndex":
        source, diagnostics = load_source_with_diagnostics(Path(path))
        if source is None:
            raise ValueError(
                f"failed to load AgentMakefile at {path}: {diagnostics.format()}"
            )
        return cls.from_source(source, embedder=embedder)

    def save(self, path: Union[Path, str]) -> Path:
        """Persist the index to a JSON file (with base64-encoded float32
        matrix). Returns the absolute path written.
        """
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        matrix_f32 = self.matrix.astype(np.float32, copy=False)
        envelope = {
            "version": INDEX_FILE_VERSION,
            "embedder": {
                "name": self.embedder.name,
                "dim": self.embedder.dim,
            },
            "matrix_shape": list(matrix_f32.shape),
            "matrix_dtype": "float32",
            "matrix_base64": base64.b64encode(matrix_f32.tobytes()).decode("ascii"),
            "skills": [
                {
                    "skill_name": skill.skill_name,
                    "target_name": skill.target_name,
                    "description": skill.description,
                    "text": skill.text,
                }
                for skill in self.skills
            ],
        }
        out.write_text(json.dumps(envelope, indent=2, sort_keys=True))
        return out

    @classmethod
    def load(
        cls,
        path: Union[Path, str],
        embedder: Optional[Embedder] = None,
    ) -> "SkillIndex":
        """Reload a previously-saved index. When `embedder` is provided
        and its `name` doesn't match what was saved, raises ValueError —
        a silent mismatch would route queries through one embedding
        space while ranking corpus rows from another.
        """
        envelope = json.loads(Path(path).read_text())
        if envelope.get("version") != INDEX_FILE_VERSION:
            raise ValueError(
                f"unsupported skill index version: {envelope.get('version')}"
            )
        saved_embedder = envelope.get("embedder") or {}
        saved_name = saved_embedder.get("name")
        saved_dim = int(saved_embedder.get("dim", 0))
        if embedder is None:
            embedder = _embedder_for_saved_name(saved_name, saved_dim)
        elif embedder.name != saved_name:
            raise ValueError(
                f"embedder mismatch: cached index uses {saved_name!r} "
                f"but caller supplied {embedder.name!r}; rebuild with --rebuild"
            )
        shape = tuple(envelope.get("matrix_shape", []))
        if len(shape) != 2:
            raise ValueError(f"matrix_shape must be 2-D, got {shape!r}")
        n_rows, dim = shape
        if dim != embedder.dim:
            raise ValueError(
                f"matrix dim {dim} does not match embedder dim {embedder.dim}"
            )
        raw = base64.b64decode(envelope.get("matrix_base64", "").encode("ascii"))
        expected_bytes = n_rows * dim * 4
        if len(raw) != expected_bytes:
            raise ValueError(
                f"matrix payload size {len(raw)} != expected {expected_bytes}"
            )
        matrix = np.frombuffer(raw, dtype=np.float32).reshape(shape).copy()
        skills = [
            IndexedSkill(
                skill_name=str(entry.get("skill_name", "")),
                target_name=str(entry.get("target_name", "")),
                description=str(entry.get("description", "")),
                text=str(entry.get("text", "")),
            )
            for entry in (envelope.get("skills") or [])
        ]
        if len(skills) != n_rows:
            raise ValueError(
                f"skill list length {len(skills)} != matrix rows {n_rows}"
            )
        return cls(embedder=embedder, skills=skills, matrix=matrix)

    def query(self, request: str, top_k: int = 5) -> List[SkillMatch]:
        if not self.skills:
            return []
        query_vec = self.embedder.embed(request).reshape(-1)
        if query_vec.size != self.matrix.shape[1]:
            raise ValueError(
                f"embedder dim mismatch: query has {query_vec.size}, "
                f"matrix has {self.matrix.shape[1]}"
            )
        # Both query and matrix rows are L2-normalised so dot == cosine.
        # A skill whose corpus text is empty (description + intents both
        # dropped) becomes a zero row — its score is 0 and ranks at the
        # bottom, which is the right behaviour.
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            scores = self.matrix @ query_vec.astype(np.float32, copy=False)
        scores = np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0)
        k = min(int(top_k), len(self.skills))
        if k <= 0:
            return []
        # Argpartition for speed; final ordering of the top-k needs argsort.
        top_idx = np.argpartition(-scores, kth=k - 1)[:k] if len(scores) > k else np.arange(len(scores))
        top_idx = top_idx[np.argsort(-scores[top_idx])]
        results: List[SkillMatch] = []
        for rank, idx in enumerate(top_idx, start=1):
            skill = self.skills[int(idx)]
            results.append(
                SkillMatch(
                    rank=rank,
                    skill_name=skill.skill_name,
                    target_name=skill.target_name,
                    score=float(scores[int(idx)]),
                    description=skill.description,
                )
            )
        return results


def _corpus_text_for_skill(skill_name: str, skill_spec) -> str:
    """Compose the per-skill text we feed to the embedder. Order
    matters: description first (the strongest semantic signal), then
    the skill's identifier, then any author-provided user_intent
    routing terms. We drop OpenClaw bucket-suffix artifacts because
    they're noise from the keyword regime — embedding wouldn't benefit
    from them.
    """
    parts: List[str] = []
    description = str(getattr(skill_spec, "description", "") or "").strip()
    if description:
        parts.append(description)
    # Use the human-readable name (replace separators with spaces) so the
    # tokeniser sees the words rather than `skills.subagent-driven-development`.
    pretty_name = skill_name.replace(".", " ").replace("-", " ").replace("_", " ").strip()
    if pretty_name:
        parts.append(pretty_name)
    match = getattr(skill_spec, "match", None)
    if match is not None:
        user_intent = match.get("user_intent") if isinstance(match, dict) else None
        if user_intent is None and hasattr(match, "get"):
            user_intent = match.get("user_intent")  # IRTarget-style mapping
        if user_intent:
            terms = _filter_user_intent_terms(user_intent)
            if terms:
                parts.append(" ".join(terms))
    return "\n".join(parts)


def _embedder_for_saved_name(name: Optional[str], dim: int) -> Embedder:
    """Reconstruct the embedder that was used to build a saved index.
    Only encodes/decodes the two embedder families we ship; future
    embedders need to extend this switch.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("saved index has no embedder.name; cannot reconstruct")
    if name.startswith("hash:"):
        # hash:<dim> — Recreate with the saved dim for byte-for-byte
        # reproducibility regardless of the caller's default.
        from agentmf.embedder import HashEmbedder
        try:
            saved_dim = int(name.split(":", 1)[1])
        except (IndexError, ValueError) as exc:
            raise ValueError(f"invalid hash embedder name: {name!r}") from exc
        return HashEmbedder(dim=saved_dim or dim)
    if name.startswith("st:"):
        from agentmf.embedder import SentenceTransformerEmbedder
        model = name.split(":", 1)[1]
        return SentenceTransformerEmbedder(model=model)
    raise ValueError(f"unknown saved embedder family: {name!r}")


_BUCKET_SUFFIXES = {".tmp", "plugins", "skills", "vendor_imports", "uncategorized"}


def _filter_user_intent_terms(terms: Iterable[str]) -> List[str]:
    cleaned: List[str] = []
    for raw in terms:
        text = str(raw).strip()
        if not text:
            continue
        tokens = text.split()
        if len(tokens) >= 2 and tokens[-1] in _BUCKET_SUFFIXES:
            continue  # bucket-suffix artefact
        cleaned.append(text)
    return cleaned
