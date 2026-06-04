"""agentmf serve — a local JSON engine API (see docs/agentmf_serve_api_spec.md).

A thin, stateless HTTP wrapper over the existing payload builders so a GUI, a
host adapter, or a future MCP server can drive AgentMakefile without shelling
out per command or reimplementing logic. ``dispatch()`` is pure (no sockets) and
is the unit-tested core; the ``http.server`` shell only calls it.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from aigg_memory.memory import MemoryUnit, memory_domain, consolidate as _mem_consolidate
from aigg_memory.store import EvidenceStore

from agentmf.ask import create_ask_payload
from agentmf.backends import SUPPORTED_BACKENDS
from agentmf.compiler import compile_agentmakefile
from agentmf.guidance_scanner import scan_guidance_files
from agentmf.loader import load_source_with_diagnostics
from agentmf.plugin import create_plugin_payload
from agentmf.selector import DEFAULT_N_BEST, SUPPORTED_MATCHERS, create_link_plan
from agentmf.tool_loop import create_exec_payload

SERVE_API_VERSION = 1

Envelope = Dict[str, Any]


def _source_path(root: Union[Path, str]) -> Path:
    """root is a project dir (use root/AgentMakefile) or a source file directly."""
    p = Path(root)
    return p if p.is_file() else p / "AgentMakefile"


def _ok(data: Any, status: int = 200) -> Tuple[int, Envelope]:
    return status, {"ok": True, "diagnostics": [], "data": data}


def _err(code: str, message: str, location: Optional[str] = None, status: int = 400) -> Tuple[int, Envelope]:
    d: Dict[str, Any] = {"severity": "error", "code": code, "message": message}
    if location:
        d["location"] = location
    return status, {"ok": False, "diagnostics": [d], "data": None}


def _result_data(result: Any) -> Any:
    """Builders carry their payload under .payload (plugin/ask/exec) or .plan
    (link plan); compile exposes .to_dict()."""
    for attr in ("payload", "plan"):
        data = getattr(result, attr, None)
        if data is not None:
            return data
    if hasattr(result, "to_dict"):
        return result.to_dict()
    return None


def _from_result(result: Any) -> Tuple[int, Envelope]:
    """Envelope from a payload-builder Result (.diagnostics + payload/plan)."""
    ok = not result.diagnostics.has_errors
    return (200 if ok else 422), {
        "ok": ok,
        "diagnostics": result.diagnostics.to_list(),
        "data": _result_data(result),
    }


def _load(root: Union[Path, str]):
    return load_source_with_diagnostics(_source_path(root))


# --- handlers -------------------------------------------------------------

def _h_healthz(body: dict, root: Path) -> Tuple[int, Envelope]:
    return _ok({
        "version": SERVE_API_VERSION,
        "root": str(root),
        "agentmakefile_present": _source_path(root).exists(),
    })


def _h_backends(body: dict, root: Path) -> Tuple[int, Envelope]:
    return _ok(sorted(SUPPORTED_BACKENDS.keys()))


def _h_matchers(body: dict, root: Path) -> Tuple[int, Envelope]:
    return _ok(sorted(SUPPORTED_MATCHERS))


def _h_targets(body: dict, root: Path) -> Tuple[int, Envelope]:
    source, diags = _load(root)
    if source is None:
        return 422, {"ok": False, "diagnostics": diags.to_list(), "data": None}
    data = [
        {"name": name, "priority": t.priority, "match": t.match, "skills": t.skills, "cost": t.cost}
        for name, t in source.targets.items()
    ]
    return _ok(data)


def _h_models(body: dict, root: Path) -> Tuple[int, Envelope]:
    source, diags = _load(root)
    if source is None:
        return 422, {"ok": False, "diagnostics": diags.to_list(), "data": None}
    data = [
        {"name": name, "family": m.family, "cost": m.cost, "capabilities": m.capabilities,
         "priority": m.priority, "default": m.default}
        for name, m in source.models.items()
    ]
    return _ok(data)


def _h_validate(body: dict, root: Path) -> Tuple[int, Envelope]:
    source, diags = _load(root)
    ok = source is not None and not diags.has_errors
    return (200 if ok else 422), {"ok": ok, "diagnostics": diags.to_list(), "data": {"valid": ok}}


def _h_select(body: dict, root: Path) -> Tuple[int, Envelope]:
    return _from_result(create_link_plan(
        _source_path(root),
        request=body.get("request"),
        target_names=body.get("targets"),
        backend=body.get("backend", "agents-fragments"),
        matcher=body.get("matcher", "keyword"),
        n_best=body.get("n_best", DEFAULT_N_BEST),
        budget=body.get("budget"),
        pricing_table=body.get("pricing_table"),
    ))


def _h_plugin_payload(body: dict, root: Path) -> Tuple[int, Envelope]:
    return _from_result(create_plugin_payload(
        _source_path(root),
        host=body.get("host", "generic"),
        request=body.get("request"),
        target_names=body.get("targets"),
        context_files=body.get("context_files"),
        include_git_status=body.get("include_git_status", False),
        include_git_diff=body.get("include_git_diff", False),
        token_budget=body.get("token_budget"),
        max_output_per_call=body.get("max_output_per_call", 1024),
        pricing_table=body.get("pricing_table"),
    ))


def _h_ask(body: dict, root: Path) -> Tuple[int, Envelope]:
    return _from_result(create_ask_payload(
        _source_path(root),
        request=body.get("request"),
        target_names=body.get("targets"),
        context_files=body.get("context_files"),
        provider=body.get("provider", "echo"),
        model=body.get("model"),
        temperature=body.get("temperature"),
        max_output_tokens=body.get("max_output_tokens"),
        token_budget=body.get("token_budget"),
    ))


def _h_exec(body: dict, root: Path) -> Tuple[int, Envelope]:
    return _from_result(create_exec_payload(
        _source_path(root),
        request=body.get("request"),
        target_names=body.get("targets"),
        tool_calls=body.get("tool_calls"),
        apply=body.get("apply", False),
        cwd=body.get("cwd"),
        sandbox_profile=body.get("sandbox_profile", "workspace-write"),
        token_budget=body.get("token_budget"),
        max_per_call_tokens=body.get("max_per_call_tokens"),
        max_per_call_usd=body.get("max_per_call_usd"),
        pricing_table=body.get("pricing_table"),
    ))


def _h_compile(body: dict, root: Path) -> Tuple[int, Envelope]:
    result = compile_agentmakefile(
        _source_path(root),
        targets=body.get("targets"),
        all_backends=body.get("all_backends", False),
        write=body.get("write", False),
    )
    ok = not result.diagnostics.has_errors
    return (200 if ok else 422), {
        "ok": ok, "diagnostics": result.diagnostics.to_list(), "data": _result_data(result),
    }


def _h_guidance_scan(body: dict, root: Path) -> Tuple[int, Envelope]:
    files = [Path(f) for f in (body.get("files") or [])]
    records = scan_guidance_files(files)
    data = [r.to_dict() if hasattr(r, "to_dict") else getattr(r, "__dict__", {}) for r in records]
    return _ok(data)


# ---------------------------------------------------------------------------
# Memory endpoints — typed agent-memory over aigg_memory.memory domain.
#
# A *corpus* is a directory (relative to root) that holds one sub-directory per
# memory unit, each containing a SKILL.md file:
#   <root>/<corpus>/<slug>/SKILL.md
# An *evidence* path (relative to root) is the append-only JSONL store for
# that corpus. Evidence is recorded online (observe); consolidation (Dream) is
# an offline batch pass that promotes repeated observations into typed units.
# ---------------------------------------------------------------------------

_UNIT_SUFFIX = "/SKILL.md"
_DEFAULT_CORPUS = "memory"
_DOMAIN_PREFIX = "memory/"   # aigg_memory.memory.unit_path() always emits this prefix


def _load_workspace(root: Path, corpus: str) -> Dict[str, str]:
    """Load all SKILL.md files under corpus_dir, normalising workspace keys to the
    domain's expected format (``memory/<slug>/SKILL.md``) regardless of the actual
    corpus path on disk.  This lets serve handlers use any corpus directory with the
    aigg_memory.memory domain unchanged."""
    corpus_dir = root / corpus
    if not corpus_dir.exists():
        return {}
    ws: Dict[str, str] = {}
    for f in sorted(corpus_dir.glob("*/SKILL.md")):
        slug = f.parent.name
        key = f"{_DOMAIN_PREFIX}{slug}{_UNIT_SUFFIX}"   # domain-normalised key
        ws[key] = f.read_text(encoding="utf-8")
    return ws


def _save_workspace(root: Path, corpus: str, workspace: Dict[str, str]) -> None:
    """Write unit files back to disk, translating domain-normalised keys
    (``memory/<slug>/SKILL.md``) to the real corpus location on disk."""
    for key, content in workspace.items():
        if not (key.startswith(_DOMAIN_PREFIX) and key.endswith(_UNIT_SUFFIX)):
            continue
        slug = Path(key).parent.name
        target = root / corpus / slug / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _unit_summaries(workspace: Dict[str, str]) -> List[Dict[str, Any]]:
    """Extract a summary dict from every unit in the workspace."""
    out = []
    for path, content in sorted(workspace.items()):
        if not path.endswith(_UNIT_SUFFIX):
            continue
        unit = MemoryUnit.from_text(content)
        if not unit.name:
            continue
        out.append({
            "path": path,
            "name": unit.name,
            "kind": unit.kind or "semantic",
            "description": unit.frontmatter.get("description", ""),
            "status": unit.frontmatter.get("status", "active"),
            "observations": unit.frontmatter.get("observations", 1),
            "confidence": unit.frontmatter.get("confidence", "medium"),
            "match_terms": unit.match_terms,
        })
    return out


def _keyword_select(workspace: Dict[str, str], request: str, n_best: int = 5,
                    kinds: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Keyword scan over match.user_intent — no agentmf import needed."""
    req_lower = request.lower()
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for path, content in workspace.items():
        if not path.endswith(_UNIT_SUFFIX):
            continue
        unit = MemoryUnit.from_text(content)
        if not unit.name:
            continue
        kind = unit.kind or "semantic"
        if kinds and kind not in kinds:
            continue
        if unit.frontmatter.get("status") == "archived":
            continue
        terms = unit.match_terms
        score = sum(1 for t in terms if t.lower() in req_lower)
        if score > 0:
            scored.append((score, {
                "path": path,
                "name": unit.name,
                "kind": kind,
                "description": unit.frontmatter.get("description", ""),
                "body": unit.body.strip(),
                "match_terms": terms,
                "score": score,
            }))
    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:n_best]]


def _h_memory_observe(body: dict, root: Path) -> Tuple[int, Envelope]:
    """Record one observation into the evidence store (online, cheap).
    Body: { corpus?, evidence, source?, payload, outcome? }"""
    evidence_path = body.get("evidence")
    if not evidence_path:
        return _err("AM_MEM_400", "evidence path required")
    source = body.get("source", "observation")
    payload = body.get("payload")
    if not isinstance(payload, dict):
        return _err("AM_MEM_400", "payload must be a JSON object")
    outcome = body.get("outcome")

    ev_abs = root / evidence_path
    domain = memory_domain()
    store = EvidenceStore(ev_abs, domain=domain)
    try:
        record = store.record(source, payload, outcome=outcome)
    except Exception as exc:
        return _err("AM_MEM_500", f"{type(exc).__name__}: {exc}", status=500)
    return _ok(record.to_dict())


def _h_memory_consolidate(body: dict, root: Path) -> Tuple[int, Envelope]:
    """Offline consolidation (Dream): promote repeated observations into typed
    units, merge duplicates, archive obsolete. Gates block promotion on failures.
    Body: { corpus?, evidence, write? }"""
    evidence_path = body.get("evidence")
    if not evidence_path:
        return _err("AM_MEM_400", "evidence path required")
    corpus = body.get("corpus", _DEFAULT_CORPUS)
    write = bool(body.get("write", False))

    ev_abs = root / evidence_path
    domain = memory_domain()
    store = EvidenceStore(ev_abs, domain=domain)
    try:
        records = store.load()
        workspace = _load_workspace(root, corpus)
        result = _mem_consolidate(workspace, records, domain=domain)
    except Exception as exc:
        return _err("AM_MEM_500", f"{type(exc).__name__}: {exc}", status=500)

    written = False
    if write and result.gates_ok and result.new_workspace != workspace:
        _save_workspace(root, corpus, result.new_workspace)
        written = True

    data: Dict[str, Any] = {
        "proposals": [p.to_dict() for p in result.proposals],
        "gates": [{"name": g.name, "passed": g.passed, "detail": g.detail} for g in result.gates],
        "gates_ok": result.gates_ok,
        "diffs": result.patch.diffs,
        "diagnostics": result.patch.diagnostics.to_list(),
        "written": written,
        "units_after": _unit_summaries(result.new_workspace),
    }
    status = 200 if result.gates_ok else 422
    return status, {"ok": result.gates_ok, "diagnostics": [], "data": data}


def _h_memory_select(body: dict, root: Path) -> Tuple[int, Envelope]:
    """Keyword retrieval of relevant memory units for a request (online, cheap).
    Body: { corpus?, request, n_best?, kinds? }"""
    request = body.get("request", "")
    corpus = body.get("corpus", _DEFAULT_CORPUS)
    n_best = int(body.get("n_best", 5))
    kinds: Optional[List[str]] = body.get("kinds")

    workspace = _load_workspace(root, corpus)
    try:
        units = _keyword_select(workspace, request, n_best=n_best, kinds=kinds)
    except Exception as exc:
        return _err("AM_MEM_500", f"{type(exc).__name__}: {exc}", status=500)

    # kind-aware bundle for direct context injection into a prompt
    bundle_lines: List[str] = []
    for kind_label, kind_key in [("## Procedures", "procedural"), ("## Facts", "semantic"),
                                  ("## History", "episodic")]:
        group = [u for u in units if u["kind"] == kind_key]
        if group:
            bundle_lines.append(kind_label)
            for u in group:
                prefix = f"- apply `{u['name']}` — " if kind_key == "procedural" else "- "
                bundle_lines.append(prefix + (u["body"] or u["description"]))
            bundle_lines.append("")
    bundle = "\n".join(bundle_lines).rstrip("\n") + "\n" if bundle_lines else ""

    return _ok({"units": units, "bundle": bundle, "total_in_corpus": len(workspace)})


def _h_memory_units(body: dict, root: Path) -> Tuple[int, Envelope]:
    """List all (non-archived) typed units in a corpus.
    Body / query: { corpus? }"""
    corpus = body.get("corpus", _DEFAULT_CORPUS)
    workspace = _load_workspace(root, corpus)
    return _ok({
        "corpus": corpus,
        "units": _unit_summaries(workspace),
        "total": sum(1 for p in workspace if p.endswith(_UNIT_SUFFIX)),
    })


_ROUTES = {
    ("GET", "/healthz"): _h_healthz,
    ("GET", "/backends"): _h_backends,
    ("GET", "/matchers"): _h_matchers,
    ("GET", "/targets"): _h_targets,
    ("GET", "/models"): _h_models,
    ("POST", "/validate"): _h_validate,
    ("POST", "/select"): _h_select,
    ("POST", "/plugin/payload"): _h_plugin_payload,
    ("POST", "/ask"): _h_ask,
    ("POST", "/exec"): _h_exec,
    ("POST", "/compile"): _h_compile,
    ("POST", "/guidance/scan"): _h_guidance_scan,
    # --- typed agent-memory (aigg_memory.memory domain) ---
    ("POST", "/memory/observe"): _h_memory_observe,
    ("POST", "/memory/consolidate"): _h_memory_consolidate,
    ("POST", "/memory/select"): _h_memory_select,
    ("POST", "/memory/units"): _h_memory_units,
}


_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentMakefile</title>
<style>
  :root { color-scheme: light dark; --b:#3b82f6; --mut:#888; --bd:#8884; }
  * { box-sizing: border-box; }
  body { font: 14px/1.5 ui-sans-serif, system-ui, sans-serif; margin: 0; padding: 1.5rem;
         max-width: 1100px; margin-inline: auto; }
  h1 { font-size: 1.4rem; margin: 0 0 1rem; }
  h1 small { color: var(--mut); font-weight: 400; font-size: .8rem; }
  h2 { font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; color: var(--mut); margin: 1.2rem 0 .4rem; }
  .bar { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
  input, select, button { font: inherit; padding: .5rem .6rem; border: 1px solid var(--bd); border-radius: 6px; background: transparent; color: inherit; }
  #request { flex: 1 1 320px; }
  button { background: var(--b); color: #fff; border: 0; cursor: pointer; }
  button:active { opacity: .8; }
  .grid { display: grid; grid-template-columns: 1fr 240px; gap: 1.5rem; margin-top: 1rem; }
  @media (max-width: 720px) { .grid { grid-template-columns: 1fr; } }
  pre { background: #8881; padding: 1rem; border-radius: 8px; overflow: auto; max-height: 60vh; margin: 0; white-space: pre-wrap; word-break: break-word; }
  ul { margin: 0; padding-left: 1.1rem; }
  li { margin: .15rem 0; }
  .tok { margin-top: 1.5rem; }
  .tok input { width: 280px; }
  .err { color: #ef4444; }
  .budget-panel { margin: 0 0 1rem; padding: .75rem .9rem; border: 1px solid var(--bd); border-radius: 8px; }
  .budget-panel.hidden { display: none; }
  .budget-panel h3 { margin: 0 0 .5rem; font-size: .72rem; text-transform: uppercase; letter-spacing: .05em; color: var(--mut); }
  .cost-bar { display: flex; height: 22px; border-radius: 5px; overflow: hidden; background: #8881; }
  .cost-bar .seg-prefix { background: #9ca3af; }
  .cost-bar .seg-call { background: var(--b); }
  .cost-bar.over .seg-call { background: #ef4444; }
  .budget-meta { display: flex; gap: .25rem 1rem; flex-wrap: wrap; margin-top: .55rem; font-size: .8rem; color: var(--mut); }
  .budget-meta b { color: inherit; font-weight: 600; }
  .ok-badge { color: #10b981; } .bad-badge { color: #ef4444; }
  .budget-policy { margin-top: .4rem; font-size: .76rem; color: var(--mut); }
</style>
</head>
<body>
  <h1>AgentMakefile <small id="health">connecting…</small></h1>
  <div class="bar">
    <input id="request" placeholder="Describe a task — e.g. review this code for bugs" autofocus>
    <select id="matcher" title="matcher"></select>
    <select id="backend" title="backend"></select>
    <input id="budget" type="number" min="0" placeholder="budget (opt)" style="width:120px">
    <button id="run">Select</button>
  </div>
  <div class="grid">
    <section>
      <div id="budget-panel" class="budget-panel hidden">
        <h3>Token budget · POST /plugin/payload</h3>
        <div id="cost-bar" class="cost-bar">
          <div class="seg-prefix" id="seg-prefix" title="stable prefix tokens"></div>
          <div class="seg-call" id="seg-call" title="per-call ceiling"></div>
        </div>
        <div id="budget-meta" class="budget-meta"></div>
        <div id="budget-policy" class="budget-policy"></div>
      </div>
      <h2>Selection result · POST /select</h2>
      <pre id="result">Enter a request and press Select.</pre>
    </section>
    <aside>
      <h2>Targets</h2><ul id="targets"></ul>
      <h2>Models</h2><ul id="models"></ul>
    </aside>
  </div>
  <div class="tok"><input id="token" placeholder="bearer token (only if server set --token)"></div>
<script>
const $ = (id) => document.getElementById(id);
const authHeaders = () => { const t = $("token").value.trim(); return t ? { Authorization: "Bearer " + t } : {}; };
async function api(method, path, body) {
  const headers = { ...authHeaders() };
  if (body) headers["Content-Type"] = "application/json";
  const r = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, env: await r.json() };
}
function options(id, items) { $(id).innerHTML = items.map((i) => `<option>${i}</option>`).join(""); }
function bullets(id, items) { $(id).innerHTML = items.map((i) => `<li>${i}</li>`).join(""); }
async function boot() {
  try {
    const h = await api("GET", "/healthz");
    const d = h.env.data || {};
    $("health").textContent = "· " + (d.agentmakefile_present ? d.root : "no AgentMakefile at " + d.root);
    const [mt, bk, tg, md] = await Promise.all([
      api("GET", "/matchers"), api("GET", "/backends"), api("GET", "/targets"), api("GET", "/models"),
    ]);
    options("matcher", mt.env.data);
    options("backend", bk.env.data);
    bullets("targets", (tg.env.data || []).map((t) => `${t.name} · p${t.priority}`));
    bullets("models", (md.env.data || []).map((m) => m.name + (m.default ? " (default)" : "")));
    if (bk.env.data.includes("agents-fragments")) $("backend").value = "agents-fragments";
  } catch (e) {
    $("health").innerHTML = '<span class="err">· server offline</span>';
  }
}
function renderBudget(tb) {
  const panel = $("budget-panel");
  if (!tb) { panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");
  const total = tb.total || 0;
  const prefix = tb.stable_prefix_tokens || 0;
  const ceiling = tb.per_call_ceiling || 0;
  const pct = (n) => Math.max(0, Math.min(100, total ? (n / total) * 100 : 0));
  $("seg-prefix").style.width = pct(prefix) + "%";
  $("seg-call").style.width = pct(Math.max(0, ceiling - prefix)) + "%";
  $("cost-bar").classList.toggle("over", tb.fits_first_call === false);
  const badge = tb.fits_first_call ? "ok-badge" : "bad-badge";
  $("budget-meta").innerHTML = [
    `total <b>${total}</b>`,
    `stable_prefix_tokens <b>${prefix}</b>`,
    `per_call_ceiling <b>${ceiling}</b>`,
    `headroom_after_first_call <b>${tb.headroom_after_first_call}</b>`,
    `fits_first_call <b class="${badge}">${tb.fits_first_call}</b>`,
  ].map((s) => `<span>${s}</span>`).join("");
  $("budget-policy").textContent = "halt_policy: " + (tb.halt_policy || "");
}
async function run() {
  const body = { request: $("request").value, matcher: $("matcher").value, backend: $("backend").value };
  const b = $("budget").value; if (b) body.budget = Number(b);
  $("result").textContent = "…";
  try {
    const { status, env } = await api("POST", "/select", body);
    const head = `# status ${status} · ok=${env.ok}\\n`;
    $("result").textContent = head + JSON.stringify(env.diagnostics.length ? { diagnostics: env.diagnostics, data: env.data } : env.data, null, 2);
    // budget panel: the host-enforceable A/B/C contract lives in /plugin/payload
    if (b) {
      const pp = await api("POST", "/plugin/payload", { request: $("request").value, token_budget: Number(b) });
      renderBudget(pp.env.data && pp.env.data.token_budget);
    } else {
      renderBudget(null);
    }
  } catch (e) { $("result").innerHTML = '<span class="err">request failed: ' + e + "</span>"; }
}
$("run").addEventListener("click", run);
$("request").addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
boot();
</script>
</body>
</html>
"""

_STATIC_PATHS = {"/", "/ui", "/index.html"}


def render_index() -> str:
    """The single self-contained web UI page (no build step, no dependencies)."""
    return _INDEX_HTML


def static_response(path: str) -> Optional[Tuple[str, bytes]]:
    """Return (content_type, body) for a static UI path, or None for API/unknown
    paths (which the JSON dispatch owns)."""
    if path in _STATIC_PATHS:
        return "text/html; charset=utf-8", _INDEX_HTML.encode("utf-8")
    return None


def dispatch(method: str, path: str, body: Optional[dict], root: Union[Path, str]) -> Tuple[int, Envelope]:
    """Pure request dispatch — the unit-tested core. Returns (http_status, envelope)."""
    handler = _ROUTES.get((method, path))
    if handler is None:
        return _err("AMF_SERVE_404", f"no route: {method} {path}", status=404)
    try:
        return handler(body or {}, Path(root))
    except Exception as exc:  # never crash the server on a handler error
        return _err("AMF_SERVE_500", f"{type(exc).__name__}: {exc}", status=500)


def run_server(root: Union[Path, str], port: int = 8787, token: Optional[str] = None) -> None:
    """Start the localhost JSON server. Thin shell over dispatch()."""
    root_path = Path(root)

    class _Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, env: Envelope) -> None:
            body = json.dumps(env).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle(self, method: str) -> None:
            if token and self.headers.get("Authorization", "") != f"Bearer {token}":
                self._send(401, _err("AMF_SERVE_401", "unauthorized", status=401)[1])
                return
            parsed = {}
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                raw = self.rfile.read(length)
                try:
                    parsed = json.loads(raw)
                except Exception:
                    self._send(400, _err("AMF_SERVE_400", "invalid JSON body", status=400)[1])
                    return
            status, env = dispatch(method, self.path, parsed, root_path)
            self._send(status, env)

        def do_GET(self) -> None:  # noqa: N802
            static = static_response(self.path)
            if static is not None:
                content_type, body = static
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

        def do_PUT(self) -> None:  # noqa: N802
            self._handle("PUT")

        def do_DELETE(self) -> None:  # noqa: N802
            self._handle("DELETE")

        def do_PATCH(self) -> None:  # noqa: N802
            self._handle("PATCH")

        def log_message(self, *args: Any) -> None:  # quiet
            pass

    ThreadingHTTPServer(("127.0.0.1", port), _Handler).serve_forever()
