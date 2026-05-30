from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from agentmf.diagnostics import Diagnostics
from agentmf.ir import normalize
from agentmf.loader import load_source_with_diagnostics
from agentmf.matcher import RequestProfile, build_request_profile, match_term
from agentmf.models import IRModel, IRTarget

FRAGMENT_BACKEND_DIRS = {
    "agents-fragments": "agents",
    "claude-fragments": "claude",
}


@dataclass
class LinkPlanResult:
    diagnostics: Diagnostics
    plan: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


DEFAULT_N_BEST = 3
DEFAULT_HYBRID_TOP_K = 10
SUPPORTED_MATCHERS = ("keyword", "embedding", "hybrid")


def create_link_plan(
    path: Union[Path, str],
    request: Optional[str] = None,
    target_names: Optional[List[str]] = None,
    backend: str = "agents-fragments",
    n_best: int = DEFAULT_N_BEST,
    *,
    matcher: str = "keyword",
    embedder: Optional[Any] = None,
    embedder_cache_path: Optional[Union[Path, str]] = None,
    embedder_top_k: int = DEFAULT_HYBRID_TOP_K,
) -> LinkPlanResult:
    diagnostics = Diagnostics()
    if backend not in FRAGMENT_BACKEND_DIRS:
        diagnostics.error(
            "AMF115",
            f"unsupported fragment backend {backend}",
            "backend",
            f"choose one of: {', '.join(sorted(FRAGMENT_BACKEND_DIRS))}",
        )
        return LinkPlanResult(diagnostics)
    if matcher not in SUPPORTED_MATCHERS:
        diagnostics.error(
            "AMF117",
            f"unsupported matcher {matcher}",
            "matcher",
            f"choose one of: {', '.join(SUPPORTED_MATCHERS)}",
        )
        return LinkPlanResult(diagnostics)

    source, load_diagnostics = load_source_with_diagnostics(path)
    diagnostics.extend(load_diagnostics.items)
    if source is None or diagnostics.has_errors:
        return LinkPlanResult(diagnostics)

    ir = normalize(source, diagnostics)
    if ir is None or diagnostics.has_errors:
        return LinkPlanResult(diagnostics)

    targets_by_name = {target.name: target for target in ir.targets}
    requested_targets = list(target_names or [])
    selection_trace: Dict[str, Any]
    if requested_targets:
        selected_targets = _explicit_targets(requested_targets, targets_by_name, diagnostics)
        selection_mode = "explicit_target"
        selection_trace = _explicit_selection_trace(selected_targets, requested_targets)
    elif request:
        if matcher == "keyword":
            selected_targets, selection_trace = _targets_for_request(request, ir.targets, diagnostics)
        elif matcher == "embedding":
            selected_targets, selection_trace = _targets_for_request_embedding(
                request, source, ir.targets,
                embedder=embedder,
                cache_path=Path(embedder_cache_path) if embedder_cache_path else None,
                top_k=embedder_top_k,
                diagnostics=diagnostics,
            )
        else:  # hybrid
            selected_targets, selection_trace = _targets_for_request_hybrid(
                request, source, ir.targets,
                embedder=embedder,
                cache_path=Path(embedder_cache_path) if embedder_cache_path else None,
                top_k=embedder_top_k,
                diagnostics=diagnostics,
            )
        selection_mode = "request"
    else:
        diagnostics.error("AMF116", "select requires a request or at least one explicit target", "select")
        return LinkPlanResult(diagnostics)

    if diagnostics.has_errors:
        return LinkPlanResult(diagnostics)

    closure = _target_closure(selected_targets, targets_by_name)
    selection_trace = _with_dependency_closure(selection_trace, selected_targets, closure)
    target_pipelines = [target.pipeline for target in closure]
    fragment_dir = FRAGMENT_BACKEND_DIRS[backend]
    alternatives = _alternatives_from_trace(
        selection_trace,
        n_best,
        primary_target=selected_targets[0] if selected_targets else None,
        targets_by_name=targets_by_name,
    )
    plan = {
        "version": 1,
        "backend": backend,
        "selection": {
            "mode": selection_mode,
            "request": request if selection_mode == "request" else None,
            "targets": requested_targets,
        },
        "selection_trace": selection_trace,
        "selected_targets": [target.name for target in selected_targets],
        "recommended_model": _recommend_model(ir.models, request),
        "alternatives": alternatives,
        "target_closure": [target.name for target in closure],
        "target_pipelines": target_pipelines,
        "pipeline_trace": _pipeline_trace(selected_targets, closure),
        "fragments": [
            {
                "backend": backend,
                "target": target.name,
                "path": f".agentmf/fragments/{fragment_dir}/{_fragment_file_name(target.name)}.md",
            }
            for target in closure
        ],
    }
    return LinkPlanResult(diagnostics, plan)


def _alternatives_from_trace(
    selection_trace: Dict[str, Any],
    n_best: int,
    *,
    primary_target: Optional[IRTarget] = None,
    targets_by_name: Optional[Dict[str, IRTarget]] = None,
) -> List[Dict[str, Any]]:
    """Top-(n_best - 1) candidates ranked below the selected target.

    Auxiliary signal for downstream agents. Two sources, in order:

    1. Author-declared fallbacks on the selected target (Makefile-style
       intent encoded in `target.fallback`). These take priority slots
       because the user explicitly wrote them.
    2. Matcher-scored neighbours from selection_trace.candidates.

    A target that appears in both sources is emitted once with
    source="declared_fallback" (intent wins over score). Each entry
    carries a compact dict so consumers can render uniformly.
    """
    if n_best <= 1:
        return []
    alternatives: List[Dict[str, Any]] = []
    seen_targets: set[str] = set()

    if primary_target is not None and primary_target.fallback:
        for condition in sorted(primary_target.fallback):
            for entry in primary_target.fallback[condition]:
                target_name = _fallback_entry_target(entry)
                if not target_name or target_name in seen_targets:
                    continue
                if primary_target.name == target_name:
                    continue
                if targets_by_name is not None and target_name not in targets_by_name:
                    continue
                alternatives.append(
                    {
                        "rank": len(alternatives) + 1,
                        "target": target_name,
                        "source": "declared_fallback",
                        "condition": condition,
                        "match_score": None,
                        "matched_terms": [],
                        "reason": f"declared fallback for {primary_target.name} under condition '{condition}'",
                    }
                )
                seen_targets.add(target_name)
                if len(alternatives) >= n_best - 1:
                    return alternatives

    candidates = selection_trace.get("candidates") if isinstance(selection_trace, dict) else None
    if isinstance(candidates, list):
        scored_candidates = [
            cand for cand in candidates
            if isinstance(cand, dict) and not cand.get("selected") and cand.get("target") not in seen_targets
        ]
        # Re-rank matcher-scored alternatives with closure-proximity as an
        # additional tie-breaker: when two candidates tie on score, the one
        # whose deps include the selected target ranks ahead (it would
        # extend the selected pipeline rather than replace it).
        scored_candidates.sort(key=lambda cand: _alternative_sort_key(cand, primary_target, targets_by_name))
        for candidate in scored_candidates:
            target_name = candidate.get("target")
            alternatives.append(
                {
                    "rank": len(alternatives) + 1,
                    "target": target_name,
                    "source": "matcher_score",
                    "match_score": candidate.get("match_score"),
                    "matched_terms": list(candidate.get("matched_terms") or []),
                    "reason": candidate.get("reason"),
                }
            )
            seen_targets.add(target_name)
            if len(alternatives) >= n_best - 1:
                break
    return alternatives


def _alternative_sort_key(
    candidate: Dict[str, Any],
    primary_target: Optional[IRTarget],
    targets_by_name: Optional[Dict[str, IRTarget]],
) -> tuple:
    score = candidate.get("match_score") or 0
    target_name = candidate.get("target") or ""
    proximity = _closure_proximity(target_name, primary_target, targets_by_name)
    match_details = candidate.get("match_details") if isinstance(candidate.get("match_details"), list) else []
    term_length = max(
        (len(detail.get("term", "")) for detail in match_details if detail.get("score") == score),
        default=0,
    )
    return (-score, -proximity, -term_length, target_name)


def _closure_proximity(
    candidate_name: str,
    primary_target: Optional[IRTarget],
    targets_by_name: Optional[Dict[str, IRTarget]],
) -> int:
    """1 when the candidate's deps include the primary target (candidate is
    a causally-adjacent extender), else 0. Only the reverse direction
    matters here: forward deps (primary -> candidate) already pull the
    candidate into target_closure, so it's not really an "alternative"
    the LLM would choose instead.
    """
    if primary_target is None or not targets_by_name or not candidate_name:
        return 0
    candidate_target = targets_by_name.get(candidate_name)
    if candidate_target is None:
        return 0
    if primary_target.name in candidate_target.deps:
        return 1
    return 0


def _fallback_entry_target(entry: Any) -> Optional[str]:
    """Extract a target name from one fallback list entry (string or dict)."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        candidate = entry.get("fallback") or entry.get("target") or entry.get("name")
        if isinstance(candidate, str):
            return candidate
    return None


def _explicit_targets(
    target_names: List[str],
    targets_by_name: Dict[str, IRTarget],
    diagnostics: Diagnostics,
) -> List[IRTarget]:
    selected = []
    for name in target_names:
        target = targets_by_name.get(name)
        if target is None:
            diagnostics.error("AMF117", f"unknown target {name}", "target")
            continue
        selected.append(target)
    return selected


def _recommend_model(models: List[IRModel], request: Optional[str]) -> Optional[Dict[str, Any]]:
    """Advisory model routing: pick the best-matching model for the request.

    Reuses the same keyword match machinery as target routing (a model is just
    another selectable resource with `match` terms + priority). When no model's
    match terms hit the request, fall back to the `default: true` model (or the
    highest-priority one). Returns None when no `models:` block is defined, so
    existing modules are unaffected. This is advisory only — the host still owns
    the actual model call.
    """
    if not models:
        return None

    def pack(model: IRModel, reason: str, details: List[dict]) -> Dict[str, Any]:
        return {
            "model": model.name,
            "family": model.family,
            "cost": model.cost,
            "capabilities": list(model.capabilities),
            "priority": model.priority,
            "reason": reason,
            "matched_terms": [detail["term"] for detail in details],
            "match_score": _match_score(details),
        }

    matches = []
    if request:
        profile = build_request_profile(request)
        for model in models:
            details: List[dict] = []
            seen: set = set()
            _append_match_details(details, seen, model.match.values(), profile, source=None)
            if details:
                matches.append(
                    (_candidate_source_rank(details), model.priority, _match_score(details), model.name, model, details)
                )
    if matches:
        matches.sort(key=lambda item: (item[0], -item[1], -item[2], item[3]))
        *_, model, details = matches[0]
        return pack(model, "matched", details)

    pool = [model for model in models if model.default] or list(models)
    pool.sort(key=lambda model: (-model.priority, model.name))
    return pack(pool[0], "default", [])


def _targets_for_request(
    request: str,
    targets: List[IRTarget],
    diagnostics: Diagnostics,
) -> tuple[List[IRTarget], Dict[str, Any]]:
    profile = build_request_profile(request)
    matches = []
    for target in targets:
        match_details = _match_details(target, profile)
        if match_details:
            score = _match_score(match_details)
            matches.append(
                (
                    _candidate_source_rank(match_details),
                    target.priority,
                    score,
                    _best_term_length(match_details, score),
                    target.name,
                    target,
                    match_details,
                )
            )
    if not matches:
        diagnostics.error("AMF118", "no target matched request", "request")
        return [], {}
    matches.sort(key=lambda item: (item[0], -item[1], -item[2], -item[3], item[4]))
    selected_target = matches[0][5]
    selected_name = selected_target.name
    candidates = [
        {
            "rank": index,
            "target": target.name,
            "priority": priority,
            "matched_terms": [detail["term"] for detail in match_details],
            "match_details": match_details,
            "match_score": score,
            "selected": target.name == selected_name,
            "reason": _reason(match_details),
        }
        for index, (_source_rank, priority, score, _best_term_length, _name, target, match_details)
        in enumerate(matches, start=1)
    ]
    trace = {
        "mode": "request",
        "algorithm": "normalize_translate_semantic_priority_score_term-length_name",
        "request": request,
        "normalized_request": profile.normalized,
        "expanded_request_terms": profile.expanded_terms,
        "requested_targets": [],
        "selected": {
            "target": selected_target.name,
            "priority": selected_target.priority,
            "matched_terms": [detail["term"] for detail in matches[0][6]],
            "match_details": matches[0][6],
            "match_score": matches[0][2],
            "dependency_closure": [],
        },
        "candidates": candidates,
    }
    return [selected_target], trace


def _targets_for_request_embedding(
    request: str,
    source: Any,
    targets: List[IRTarget],
    *,
    embedder: Optional[Any],
    cache_path: Optional[Path],
    top_k: int,
    diagnostics: Diagnostics,
) -> tuple[List[IRTarget], Dict[str, Any]]:
    """Pure embedding selector. Builds (or loads) a `SkillIndex` over
    the source's skills, ranks by cosine, and returns the IRTarget whose
    name matches the rank-1 skill's `skill.<name>` target.

    Gracefully degrades to the keyword selector when the source has no
    skills to index (hand-written makefiles with only targets, like
    most superpowers / oh-my-openagent modules). Trace records
    `mode="embedding"` with `winner_source="keyword_fallback_no_skills"`
    so the caller can tell the embedding path was a no-op.
    """
    if not source.skills:
        selected, trace = _targets_for_request(request, targets, diagnostics)
        if trace:
            trace["mode"] = "embedding"
            trace["embedding_fallback"] = "keyword_fallback_no_skills"
        return selected, trace

    index, embedder_meta = _load_routing_index(source, embedder, cache_path, diagnostics)
    if index is None:
        # Embedder dep missing or load failure — degrade to keyword too.
        selected, trace = _targets_for_request(request, targets, Diagnostics())
        if trace:
            trace["mode"] = "embedding"
            trace["embedding_fallback"] = "keyword_fallback_index_unavailable"
        return selected, trace
    matches = index.query(request, top_k=max(int(top_k), 1))
    if not matches:
        diagnostics.error("AMF118", "no skill matched request via embedding", "request")
        return [], {}
    targets_by_name = {target.name: target for target in targets}
    # For openclaw-style auto-generated modules each skill has an
    # auto-created `skill.<name>` target. Hand-written modules (e.g.
    # superpowers) bundle skills under higher-level targets like
    # `methodology.code_change` instead. Build a skill → owning-targets
    # map so the matcher works in both shapes.
    skill_to_targets: Dict[str, List[IRTarget]] = {}
    for target in targets:
        for skill in target.skills:
            for key in (skill.name, skill.qualified_name):
                if key:
                    skill_to_targets.setdefault(key, []).append(target)
    selected_target = None
    for match in matches:
        # First try the SkillIndex's auto-generated `skill.<name>` target.
        candidate = targets_by_name.get(match.target_name)
        if candidate is not None:
            selected_target = candidate
            break
        # Fall back: any target that explicitly binds this skill.
        binding_targets = (
            skill_to_targets.get(match.skill_name)
            or skill_to_targets.get(match.skill_name.split(".")[-1])
        )
        if binding_targets:
            selected_target = max(binding_targets, key=lambda t: t.priority)
            break
    if selected_target is None:
        diagnostics.error(
            "AMF118",
            f"embedding rank-1 skill {matches[0].skill_name!r} has no bound target in the IR",
            "request",
        )
        return [], {}
    trace = {
        "mode": "embedding",
        "algorithm": "embedding_cosine_top_k",
        "request": request,
        "embedder": embedder_meta,
        "selected": {
            "target": selected_target.name,
            "priority": selected_target.priority,
            "matched_terms": [],
            "match_details": [],
            "match_score": matches[0].score,
            "dependency_closure": [],
        },
        "candidates": [
            {
                "rank": m.rank,
                "target": m.target_name,
                "priority": targets_by_name[m.target_name].priority if m.target_name in targets_by_name else None,
                "matched_terms": [],
                "match_details": [{"term": m.skill_name, "source": "embedding", "score": m.score}],
                "match_score": m.score,
                "selected": m.target_name == selected_target.name,
                "reason": f"embedding cosine={m.score:.4f}",
            }
            for m in matches
        ],
    }
    return [selected_target], trace


# Picked via parameter sweep against benchmarks/routing/openclaw-skills.yaml:
# at α=0.85 hybrid ties pure embedding (7/8) while still using keyword as a
# tiebreaker on close cosine calls. α=0.7 (the initial default) gave 30% of
# its vote to a noisy keyword layer and lost 1 case to a 2-char acronym
# spuriously matching at score=100. The 15% keyword share is small enough
# that a single false-positive keyword hit can't flip a confident cosine
# decision, but large enough that `blended_agree` (both signals concur)
# still wins ties.
HYBRID_EMBEDDING_WEIGHT = 0.85
HYBRID_KEYWORD_WEIGHT = 0.15


def _targets_for_request_hybrid(
    request: str,
    source: Any,
    targets: List[IRTarget],
    *,
    embedder: Optional[Any],
    cache_path: Optional[Path],
    top_k: int,
    diagnostics: Diagnostics,
) -> tuple[List[IRTarget], Dict[str, Any]]:
    """Hybrid recall + precision via a **blended score** rather than a
    hard keyword tiebreak (the latter was worse than pure embedding on
    bench because it amplified keyword-precision regressions whenever
    the user_intent layer was over-pruned).

    Algorithm:
      1. Embed the request, take top-K skill matches → candidate target pool.
      2. For each candidate target compute keyword match details against
         the request (may be empty).
      3. Final score = HYBRID_EMBEDDING_WEIGHT * cosine
                     + HYBRID_KEYWORD_WEIGHT * (keyword_score / 100)
         Targets without any keyword match get only the cosine
         contribution; targets with strong keyword overlap get boosted.
      4. Rank by (priority desc, blended desc, cosine desc, name asc).
         Priority is respected so user-declared important targets win
         when both embedding and keyword judgements are close.

    Graceful fallbacks (unchanged):
      - No skills in source → pure keyword on the full target pool.
      - Index unbuildable → pure keyword on the full target pool.
      - Embedding produced matches but no candidate target exists →
        pure keyword on the full target pool.

    The trace records `winner_source` so consumers can tell which
    signal dominated:
      - `blended_keyword_boost`: winner has non-zero keyword score AND
        keyword_norm contribution flipped the order vs cosine-only.
      - `embedding_rank_1`: winner is the cosine rank-1 target.
      - `blended_keyword_only`: winner has keyword overlap; embedding
        rank-1 had no keyword overlap and got demoted by the blend.
      - `keyword_fallback_*`: one of the three fallback paths.
    """
    if not source.skills:
        selected, trace = _targets_for_request(request, targets, diagnostics)
        if trace:
            trace["mode"] = "hybrid"
            trace["hybrid"] = {
                "embedding_top_k": [],
                "rerank_pool": [t.name for t in targets],
                "winner_source": "keyword_fallback_no_skills",
                "embedding_weight": HYBRID_EMBEDDING_WEIGHT,
                "keyword_weight": HYBRID_KEYWORD_WEIGHT,
            }
        return selected, trace

    sub_diagnostics = Diagnostics()
    index, embedder_meta = _load_routing_index(source, embedder, cache_path, sub_diagnostics)
    if index is None:
        diagnostics.extend(sub_diagnostics.items)
        selected, trace = _targets_for_request(request, targets, diagnostics)
        if trace:
            trace["mode"] = "hybrid"
            trace["hybrid"] = {
                "embedding_top_k": [],
                "rerank_pool": [t.name for t in targets],
                "winner_source": "keyword_fallback_index_unavailable",
                "embedding_weight": HYBRID_EMBEDDING_WEIGHT,
                "keyword_weight": HYBRID_KEYWORD_WEIGHT,
            }
        return selected, trace

    matches = index.query(request, top_k=max(int(top_k), 1))
    targets_by_name = {target.name: target for target in targets}
    profile = build_request_profile(request)
    embedding_top_k_payload = [
        {"rank": m.rank, "skill": m.skill_name, "target": m.target_name, "score": m.score}
        for m in matches
    ]

    pool: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for match in matches:
        target = targets_by_name.get(match.target_name)
        if target is None or target.name in seen:
            continue
        seen.add(target.name)
        keyword_details = _match_details(target, profile)
        keyword_score = _match_score(keyword_details) if keyword_details else 0
        keyword_norm = min(float(keyword_score) / 100.0, 1.0)
        blended = HYBRID_EMBEDDING_WEIGHT * float(match.score) + HYBRID_KEYWORD_WEIGHT * keyword_norm
        pool.append(
            {
                "target": target,
                "embedding_rank": match.rank,
                "embedding_score": float(match.score),
                "keyword_details": keyword_details,
                "keyword_score": int(keyword_score),
                "blended": blended,
            }
        )

    if not pool:
        selected, trace = _targets_for_request(request, targets, diagnostics)
        if trace:
            trace["mode"] = "hybrid"
            trace["hybrid"] = {
                "embedder": embedder_meta,
                "embedding_top_k": embedding_top_k_payload,
                "rerank_pool": [],
                "winner_source": "keyword_fallback_no_pool",
                "embedding_weight": HYBRID_EMBEDDING_WEIGHT,
                "keyword_weight": HYBRID_KEYWORD_WEIGHT,
            }
        return selected, trace

    pool.sort(key=lambda entry: (-entry["target"].priority, -entry["blended"], -entry["embedding_score"], entry["target"].name))
    winner = pool[0]
    winner_target: IRTarget = winner["target"]
    # winner_source classification.
    if winner["embedding_rank"] == 1 and winner["keyword_score"] == 0:
        winner_source = "embedding_rank_1"
    elif winner["embedding_rank"] == 1 and winner["keyword_score"] > 0:
        winner_source = "blended_agree"
    elif winner["keyword_score"] == 0:
        winner_source = "embedding_promoted"  # not rank-1 but no keyword help
    else:
        winner_source = "blended_keyword_boost"

    trace = {
        "mode": "hybrid",
        "algorithm": "embedding_cosine_top_k+blended_keyword_score",
        "request": request,
        "normalized_request": profile.normalized,
        "expanded_request_terms": profile.expanded_terms,
        "selected": {
            "target": winner_target.name,
            "priority": winner_target.priority,
            "matched_terms": [detail["term"] for detail in winner["keyword_details"]],
            "match_details": winner["keyword_details"],
            "match_score": winner["blended"],
            "dependency_closure": [],
        },
        "candidates": [
            {
                "rank": idx + 1,
                "target": entry["target"].name,
                "priority": entry["target"].priority,
                "matched_terms": [d["term"] for d in entry["keyword_details"]],
                "match_details": entry["keyword_details"],
                "match_score": entry["blended"],
                "embedding_score": entry["embedding_score"],
                "embedding_rank": entry["embedding_rank"],
                "keyword_score": entry["keyword_score"],
                "selected": entry["target"].name == winner_target.name,
                "reason": (
                    f"blended={entry['blended']:.4f} "
                    f"(cos={entry['embedding_score']:.4f}, kw={entry['keyword_score']})"
                ),
            }
            for idx, entry in enumerate(pool)
        ],
        "hybrid": {
            "embedder": embedder_meta,
            "embedding_top_k": embedding_top_k_payload,
            "rerank_pool": [entry["target"].name for entry in pool],
            "winner_source": winner_source,
            "embedding_weight": HYBRID_EMBEDDING_WEIGHT,
            "keyword_weight": HYBRID_KEYWORD_WEIGHT,
        },
    }
    return [winner_target], trace


def _load_routing_index(
    source: Any,
    embedder: Optional[Any],
    cache_path: Optional[Path],
    diagnostics: Diagnostics,
) -> tuple[Optional[Any], Dict[str, Any]]:
    """Build (or cache-load) a SkillIndex for the source. Returns
    (None, {}) and reports an AMF124 diagnostic when the index cannot
    be constructed (e.g. embedder dep missing). Otherwise returns
    (index, {name, dim, cache_status}) so callers can surface the
    embedder metadata in their trace.
    """
    try:
        from agentmf.embedder import get_default_embedder
        from agentmf.skill_index import SkillIndex
    except ImportError as exc:  # pragma: no cover - numpy is a hard dep
        diagnostics.error(
            "AMF124",
            f"embedding matcher dependencies missing: {exc}",
            "matcher.embedding",
        )
        return None, {}

    emb = embedder or get_default_embedder()
    cache_status = "skipped"
    if cache_path is not None and cache_path.exists():
        try:
            index = SkillIndex.load(cache_path, embedder=emb)
            cache_status = "hit"
        except ValueError as exc:
            cache_status = f"miss ({exc})"
            index = None
        if index is not None:
            return index, {
                "name": emb.name,
                "dim": emb.dim,
                "cache_status": cache_status,
                "cache_path": str(cache_path),
            }
    try:
        index = SkillIndex.from_source(source, embedder=emb)
    except Exception as exc:  # pragma: no cover - defensive
        diagnostics.error(
            "AMF124",
            f"could not build SkillIndex: {exc}",
            "matcher.embedding",
        )
        return None, {}
    return index, {
        "name": emb.name,
        "dim": emb.dim,
        "cache_status": cache_status if cache_path else "skipped",
        "cache_path": str(cache_path) if cache_path else None,
    }


def _target_matches_request(target: IRTarget, request: str) -> bool:
    return bool(_match_details(target, build_request_profile(request)))


def _match_details(target: IRTarget, profile: RequestProfile) -> List[dict]:
    details = []
    seen = set()
    _append_match_details(
        details,
        seen,
        target.match.values(),
        profile,
        source=None,
    )
    for skill in target.skills:
        _append_match_details(
            details,
            seen,
            skill.match.values(),
            profile,
            source=f"skill:{skill.qualified_name}",
        )
    details.sort(key=lambda item: (-item["score"], _detail_source_rank(item), item["term"]))
    return details


def _append_match_details(
    details: List[dict],
    seen: set,
    candidates: Iterable[Any],
    profile: RequestProfile,
    *,
    source: Optional[str],
) -> None:
    for candidate in _match_strings(candidates):
        detail = match_term(profile, candidate)
        if detail is None:
            continue
        key = (detail["term"], detail["method"])
        if key in seen:
            continue
        seen.add(key)
        if source is not None:
            detail = dict(detail)
            detail["source"] = source
        details.append(detail)


def _match_score(match_details: List[dict]) -> int:
    if not match_details:
        return 0
    return max(detail["score"] for detail in match_details)


def _best_term_length(match_details: List[dict], top_score: int) -> int:
    """Length of the longest matched term among details that hit the top score.

    Used as a tie-break in target ranking: when two targets both reach the
    same max score, the one whose matched term is more specific (longer)
    wins. Without this, broad single-word match.user_intent entries like
    `Create` always beat narrow phrases at the same score on name order.
    """
    if not match_details:
        return 0
    return max(
        (len(detail.get("term", "")) for detail in match_details if detail.get("score") == top_score),
        default=0,
    )


def _detail_source_rank(detail: dict) -> int:
    return 1 if "source" in detail else 0


def _candidate_source_rank(match_details: List[dict]) -> int:
    return min(_detail_source_rank(detail) for detail in match_details)


def _reason(match_details: List[dict]) -> str:
    if not match_details:
        return "no match"
    method = match_details[0]["method"]
    if method == "substring":
        return "matched request substring(s)"
    if method == "normalized_substring":
        return "matched normalized request term(s)"
    if method == "translated_substring":
        return "matched translated request term(s)"
    return "matched semantic token overlap"


def _match_strings(values: Iterable[Any]) -> Iterable[str]:
    for value in values:
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            yield from _match_strings(value)
        elif isinstance(value, dict):
            yield from _match_strings(value.values())


def _target_closure(selected_targets: List[IRTarget], targets_by_name: Dict[str, IRTarget]) -> List[IRTarget]:
    closure: List[IRTarget] = []
    visited = set()

    def visit(target: IRTarget) -> None:
        if target.name in visited:
            return
        visited.add(target.name)
        for dep_name in target.deps:
            dep = targets_by_name.get(dep_name)
            if dep is not None:
                visit(dep)
        closure.append(target)

    for target in selected_targets:
        visit(target)
    return closure


def _explicit_selection_trace(selected_targets: List[IRTarget], requested_targets: List[str]) -> Dict[str, Any]:
    candidates = [
        {
            "rank": index,
            "target": target.name,
            "priority": target.priority,
            "matched_terms": [],
            "selected": True,
            "reason": "explicit target",
        }
        for index, target in enumerate(selected_targets, start=1)
    ]
    return {
        "mode": "explicit_target",
        "algorithm": "explicit_target_order",
        "request": None,
        "requested_targets": requested_targets,
        "selected": {
            "target": selected_targets[0].name if selected_targets else None,
            "targets": [target.name for target in selected_targets],
            "dependency_closure": [],
        },
        "candidates": candidates,
    }


def _with_dependency_closure(
    selection_trace: Dict[str, Any],
    selected_targets: List[IRTarget],
    closure: List[IRTarget],
) -> Dict[str, Any]:
    if not selection_trace:
        return selection_trace
    trace = dict(selection_trace)
    selected = dict(trace.get("selected") or {})
    selected["dependency_closure"] = [target.name for target in closure]
    if selected_targets and "target" not in selected:
        selected["target"] = selected_targets[0].name
    trace["selected"] = selected
    return trace


def _pipeline_trace(selected_targets: List[IRTarget], closure: List[IRTarget]) -> Dict[str, Any]:
    return {
        "selected_target": selected_targets[0].name if selected_targets else None,
        "target_closure": [target.name for target in closure],
        "operation_counts": _aggregate_operation_counts(target.pipeline for target in closure),
        "targets": [
            {
                "target": target.name,
                "operation_counts": _operation_counts(target.pipeline),
            }
            for target in closure
        ],
    }


def _aggregate_operation_counts(pipelines: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts = _empty_operation_counts()
    for pipeline in pipelines:
        target_counts = _operation_counts(pipeline)
        for key, value in target_counts.items():
            counts[key] += value
    return counts


def _operation_counts(pipeline: Dict[str, Any]) -> Dict[str, int]:
    return {
        "operations": len(pipeline.get("operations", [])),
        "context_ops": len(pipeline.get("context_ops", [])),
        "prompt_ops": len(pipeline.get("prompt_ops", [])),
        "action_ops": len(pipeline.get("action_ops", [])),
        "guard_ops": len(pipeline.get("guard_ops", [])),
        "permission_ops": len(pipeline.get("permission_ops", [])),
        "fallback_ops": len(pipeline.get("fallback_ops", [])),
    }


def _empty_operation_counts() -> Dict[str, int]:
    return {
        "operations": 0,
        "context_ops": 0,
        "prompt_ops": 0,
        "action_ops": 0,
        "guard_ops": 0,
        "permission_ops": 0,
        "fallback_ops": 0,
    }


def _fragment_file_name(target_name: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in target_name)
