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
from typing import Any, Dict, Optional, Tuple, Union

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
}


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
