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

The index is NOT serialised here — `agentmf compile` with the
`embedding-index` backend (not yet wired) is the future place for that.
For now we rebuild on demand.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np

from agentmf.embedder import Embedder, get_default_embedder
from agentmf.loader import load_source_with_diagnostics
from agentmf.models import AgentMakefileSource


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
