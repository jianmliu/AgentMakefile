from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Set


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "can",
    "do",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "please",
    "run",
    "the",
    "this",
    "to",
    "use",
    "when",
    "with",
    "work",
}

SYNONYMS = {
    "add": "implement",
    "adding": "implement",
    "build": "implement",
    "building": "implement",
    "built": "implement",
    "complete": "complete",
    "completed": "complete",
    "completion": "complete",
    "create": "implement",
    "creating": "implement",
    "debugging": "debug",
    "done": "complete",
    "feature": "feature",
    "features": "feature",
    "finish": "complete",
    "finished": "complete",
    "finishing": "complete",
    "fixing": "fix",
    "implemented": "implement",
    "implementing": "implement",
    "installs": "install",
    "installed": "install",
    "installing": "install",
    "skills": "skill",
    "tasks": "task",
    "verification": "verify",
    "verified": "verify",
    "verifying": "verify",
}

TRANSLATION_PHRASES = [
    ("实现这个功能", "implement this feature"),
    ("实现功能", "implement feature"),
    ("实现这个特性", "implement this feature"),
    ("添加这个功能", "implement this feature"),
    ("添加功能", "implement feature"),
    ("加这个功能", "implement this feature"),
    ("加功能", "implement feature"),
    ("做这个功能", "implement this feature"),
    ("开发这个功能", "implement this feature"),
    ("修复这个bug", "fix bug"),
    ("修复 bug", "fix bug"),
    ("修复bug", "fix bug"),
    ("修 bug", "fix bug"),
    ("调试", "debug"),
    ("排查失败", "debug failing test"),
    ("写计划", "write plan"),
    ("实现计划", "execute plan"),
    ("执行计划", "execute plan"),
    ("分解spec", "break down spec"),
    ("分解 spec", "break down spec"),
    ("审查代码", "review code"),
    ("重新审查", "review"),
    ("审查", "review"),
    ("安装一个技能", "install skill"),
    ("安装技能", "install skill"),
    ("安装一个skill", "install skill"),
    ("安装skill", "install skill"),
    ("技能选择", "skill selection"),
    ("优化skill", "optimize skill selection"),
    ("优化技能", "optimize skill selection"),
    ("自举测试", "self hosting test"),
    ("自举", "self hosting"),
    ("验证完成", "verify completion"),
    ("完成前验证", "verify before completion"),
]


@dataclass(frozen=True)
class RequestProfile:
    original: str
    normalized: str
    expanded_terms: List[str]
    searchable_texts: List[str]
    semantic_tokens: Set[str]


def build_request_profile(request: str) -> RequestProfile:
    normalized = normalize_text(request)
    expanded_terms = _expanded_terms(request, normalized)
    searchable_texts = _unique([normalized, *expanded_terms, " ".join(expanded_terms)])
    semantic_tokens: Set[str] = set()
    for text in searchable_texts:
        semantic_tokens.update(canonical_tokens(text))
    return RequestProfile(
        original=request,
        normalized=normalized,
        expanded_terms=expanded_terms,
        searchable_texts=searchable_texts,
        semantic_tokens=semantic_tokens,
    )


def match_term(profile: RequestProfile, term: str) -> dict | None:
    normalized_term = normalize_text(term)
    if not normalized_term:
        return None
    if not canonical_tokens(normalized_term):
        return None
    if term.lower() in profile.original.lower():
        return _detail(term, "substring", 100, term)
    if normalized_term in profile.normalized:
        return _detail(term, "normalized_substring", 95, normalized_term)

    for expanded in profile.expanded_terms:
        if normalized_term in normalize_text(expanded):
            return _detail(term, "translated_substring", 90, normalized_term)

    request_tokens = set(profile.semantic_tokens)
    term_tokens = set(canonical_tokens(normalized_term))
    if not request_tokens or not term_tokens:
        return None
    overlap = request_tokens.intersection(term_tokens)
    strong_single = _strong_single_token_overlap(overlap, request_tokens, term_tokens)
    if len(overlap) < 2 and not strong_single:
        return None
    coverage = len(overlap) / max(1, len(term_tokens))
    if coverage < 0.34 and len(overlap) < 2 and not strong_single:
        return None
    evidence = "complete task" if strong_single else " ".join(sorted(overlap))
    return _detail(term, "semantic_token_overlap", 60, evidence)


def normalize_text(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[_\-/]+", " ", value)
    value = re.sub(r"[^\w\u4e00-\u9fff]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def canonical_tokens(value: str) -> List[str]:
    tokens = []
    for token in normalize_text(value).split():
        canonical = SYNONYMS.get(token, token)
        if canonical in STOPWORDS or len(canonical) <= 1:
            continue
        tokens.append(canonical)
    return tokens


def _expanded_terms(original: str, normalized: str) -> List[str]:
    terms = list(normalized.split())
    for phrase, translation in TRANSLATION_PHRASES:
        if phrase in original or normalize_text(phrase) in normalized:
            terms.append(translation)
    joined = " ".join(terms)
    if "implement" in terms and "feature" in terms:
        terms.append("implement this feature")
    if "install" in terms and "skill" in terms:
        terms.append("install skill")
    if "complete" in terms and "task" in terms:
        terms.append("complete task")
    if "complete" in terms and "report" in terms:
        terms.append("complete task")
    if "finish" in joined or "completion" in joined:
        terms.append("complete task")
    if ("report" in terms or "claim" in terms) and ("completion" in terms or "complete" in terms):
        terms.append("about to claim work is complete")
    return _unique(terms)


def _strong_single_token_overlap(overlap: Set[str], request_tokens: Set[str], term_tokens: Set[str]) -> bool:
    if overlap != {"complete"}:
        return False
    return bool({"task", "report"}.intersection(request_tokens) and {"claim", "complete"}.intersection(term_tokens))


def _detail(term: str, method: str, score: int, evidence: str) -> dict:
    return {
        "term": term,
        "method": method,
        "score": score,
        "evidence": evidence,
    }


def _unique(values: Iterable[str]) -> List[str]:
    result = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
