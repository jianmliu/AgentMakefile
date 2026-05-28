// AgentMakefile <-> OpenCode plugin bridge.
//
// Three wires (all implemented in v0.0.3):
//   1. chat.message + experimental.chat.system.transform
//                   — on each user turn, call `agentmf prompt --request <text>`
//                     and push the routed stable_prefix into the system prompt list.
//   2. command.execute.before
//                   — intercept `/agentmf <subcommand>`, shell to `agentmf` CLI,
//                     emit stdout as a text part. Requires the user to define an
//                     `agentmf` command stub in opencode.json (see README).
//   3. event        — on `session.diff` capture FileDiff[] per session; on
//                     `session.idle` ship a redacted trace including the
//                     accumulated diff to `agentmf evo evidence add --source
//                     plugin_payload`.
//
// The plugin is a thin adapter: all logic lives in the `agentmf` CLI. If
// `agentmf` is not on PATH the plugin no-ops rather than failing the session.
//
// OpenCode hook reference: @opencode-ai/plugin (PluginInput, Hooks).

import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const AGENTMF_BIN = process.env.AGENTMF_BIN || "agentmf";
const AGENTMF_TIMEOUT_MS = Number(process.env.AGENTMF_TIMEOUT_MS || "5000");
const PREFIX_HEADER = "## Routed Guidance (AgentMakefile)";
const SLASH_COMMAND = process.env.AGENTMF_SLASH_COMMAND || "agentmf";
const MIN_REQUEST_CHARS = 3;
const MAX_DIFF_BYTES_PER_FILE = Number(process.env.AGENTMF_MAX_DIFF_BYTES || "16384");
const DEBUG = !!process.env.AGENTMF_PLUGIN_DEBUG;

function dbg(...parts) {
  if (DEBUG) process.stderr.write("[agentmf-plugin] " + parts.join(" ") + "\n");
}

function runAgentmf(args, { input, timeoutMs = AGENTMF_TIMEOUT_MS, cwd } = {}) {
  return new Promise((resolve) => {
    const child = spawn(AGENTMF_BIN, args, { stdio: ["pipe", "pipe", "pipe"], cwd });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      resolve({ ok: false, code: null, stdout, stderr: stderr + "\n[agentmf-plugin] timeout" });
    }, timeoutMs);
    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ ok: false, code: null, stdout, stderr: stderr + "\n" + String(err) });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ ok: code === 0, code, stdout, stderr });
    });
    if (input !== undefined) child.stdin.end(input); else child.stdin.end();
  });
}

function extractTextFromParts(parts) {
  if (!Array.isArray(parts)) return null;
  const chunks = [];
  for (const part of parts) {
    if (part && part.type === "text" && typeof part.text === "string") {
      chunks.push(part.text);
    }
  }
  const joined = chunks.join("\n").trim();
  return joined.length ? joined : null;
}

async function fetchRoutedPrefix(requestText, cwd) {
  const result = await runAgentmf(["prompt", "--request", requestText, "--format", "json"], { cwd });
  if (!result.ok) return null;
  let parsed;
  try { parsed = JSON.parse(result.stdout); } catch { return null; }
  const payload = parsed?.prompt_payload;
  const prefix = payload?.stable_prefix?.content;
  if (typeof prefix !== "string" || !prefix.trim()) return null;
  const routing = payload?.routing_summary || null;
  const targetName = routing?.primary?.target;
  const chars = payload?.stable_prefix?.chars ?? prefix.length;
  const header = targetName
    ? `${PREFIX_HEADER}\n\n> Routed target: \`${targetName}\` (chars=${chars})\n\n`
    : `${PREFIX_HEADER}\n\n`;
  const selectedTargets = [];
  if (typeof targetName === "string" && targetName) selectedTargets.push(targetName);
  // closure[] carries the dependency chain we'd also count as "selected"
  if (Array.isArray(routing?.closure)) {
    for (const node of routing.closure) {
      if (node && typeof node.target === "string" && !selectedTargets.includes(node.target)) {
        selectedTargets.push(node.target);
      }
    }
  }
  return {
    content: header + prefix,
    routing,
    selected_targets: selectedTargets,
    request_text: requestText,
  };
}

function redactDiff(diffs) {
  if (!Array.isArray(diffs)) return [];
  return diffs.map((d) => {
    const out = {
      file: d?.file,
      additions: d?.additions ?? 0,
      deletions: d?.deletions ?? 0,
    };
    // Keep full before/after only up to the cap so we can replay/diff later
    // in dream loop. Larger files truncate to a marker.
    const beforeLen = typeof d?.before === "string" ? d.before.length : 0;
    const afterLen = typeof d?.after === "string" ? d.after.length : 0;
    if (beforeLen + afterLen <= MAX_DIFF_BYTES_PER_FILE) {
      out.before = d.before;
      out.after = d.after;
    } else {
      out.before_truncated = true;
      out.after_truncated = true;
      out.before_bytes = beforeLen;
      out.after_bytes = afterLen;
    }
    return out;
  });
}

function snapshotGitDiff(cwd) {
  // Fallback patch capture: ask git for an unstaged + untracked summary
  // synchronously. OpenCode's `session.diff` events arrive empty
  // ({diff: []} notifications, not data carriers), so this is the
  // reliable source of "what changed during this session." Works for
  // any git project; no-ops gracefully if we're not in one.
  if (!cwd) return null;
  try {
    const stat = spawnSync("git", ["diff", "--numstat"], {
      cwd, timeout: AGENTMF_TIMEOUT_MS, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"],
    });
    if (stat.status !== 0 || !stat.stdout) return null;
    const rows = stat.stdout
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
      .map((line) => {
        const [addStr, delStr, ...fileParts] = line.split(/\s+/);
        const additions = Number.parseInt(addStr, 10);
        const deletions = Number.parseInt(delStr, 10);
        const file = fileParts.join(" ");
        return {
          file,
          additions: Number.isFinite(additions) ? additions : 0,
          deletions: Number.isFinite(deletions) ? deletions : 0,
        };
      })
      .filter((row) => row.file);
    if (rows.length === 0) return [];
    // Pull the full unified patch capped to ~64KB so dream loop can replay.
    const patch = spawnSync("git", ["diff"], {
      cwd, timeout: AGENTMF_TIMEOUT_MS, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"],
      maxBuffer: 1024 * 1024,
    });
    const fullPatch = patch.status === 0 ? (patch.stdout || "") : "";
    return rows.map((row) => ({
      ...row,
      patch_truncated: fullPatch.length > MAX_DIFF_BYTES_PER_FILE * rows.length,
      // We don't tear the unified patch apart per file here; one combined
      // patch is included separately so the dream loop can split it.
    })).concat([{ file: "<combined-patch>", patch: fullPatch.slice(0, 4 * MAX_DIFF_BYTES_PER_FILE), full_bytes: fullPatch.length }]);
  } catch {
    return null;
  }
}

function shipTraceEvidence({ event, cwd, diffs, diffSource, routing }) {
  // OpenCode's `run` mode does NOT wait for the event-hook promise to
  // resolve before disposing the instance and exiting the process. So
  // we must:
  //   1. Use SYNC file I/O — async APIs yield to the event loop and
  //      OpenCode's dispose handler races ahead of us.
  //   2. Spawn the agentmf subprocess `detached + stdio:ignore + unref`
  //      so it survives parent exit. spawn() returns synchronously once
  //      the kernel fork completes; the child then runs independently.
  const payload = {
    plugin: "@agentmf/opencode-plugin",
    event_type: event?.type || "unknown",
    session_id: event?.properties?.session?.id || event?.properties?.sessionID || null,
    summary: event?.properties?.title || event?.properties?.summary || null,
    captured_at: new Date().toISOString(),
    diff: redactDiff(diffs),
    diff_files: Array.isArray(diffs) ? diffs.length : 0,
    diff_source: diffSource || null,
    // Routing decision pulled from chat.message cache. Surface so the
    // dream loop can attribute the diff to the agentmf target that
    // actually steered the session (and not count it as a routing gap).
    selected_targets: routing?.selected_targets || [],
    request: routing?.request_text || null,
  };
  try {
    const tmp = mkdtempSync(path.join(tmpdir(), "agentmf-plugin-"));
    const file = path.join(tmp, "payload.json");
    writeFileSync(file, JSON.stringify(payload, null, 2));
    const child = spawn(
      AGENTMF_BIN,
      [
        "evo", "evidence", "add",
        "--source", "plugin_payload",
        "--payload-file", file,
        "--write",
        "--format", "json",
      ],
      { cwd, detached: true, stdio: "ignore" }
    );
    child.unref();
  } catch {
    // best-effort; never break the session over evidence capture
  }
}

// Run `agentmf <args...>` synchronously for the /agentmf slash command. We
// can't use async runAgentmf here because OpenCode awaits command hooks
// but with a short window — and spawnSync is what produces the predictable
// output. Caller passes already-parsed args from input.arguments.
function runAgentmfSync(args, cwd) {
  try {
    const result = spawnSync(AGENTMF_BIN, args, {
      cwd,
      timeout: AGENTMF_TIMEOUT_MS,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    return {
      ok: result.status === 0 && !result.error,
      stdout: result.stdout || "",
      stderr: result.stderr || "",
      code: result.status,
    };
  } catch (err) {
    return { ok: false, stdout: "", stderr: String(err), code: null };
  }
}

function parseSlashArgs(rawArgs) {
  // Naive whitespace split; agentmf args don't need shell escaping here.
  return (rawArgs || "")
    .trim()
    .split(/\s+/)
    .filter((token) => token.length > 0);
}

function formatSlashResult(args, result) {
  const argsLine = args.length ? `\`agentmf ${args.join(" ")}\`` : "`agentmf`";
  if (!result.ok) {
    const detail = result.stderr.trim() || `(exit code ${result.code})`;
    return `**agentmf failed**\n\nRan: ${argsLine}\n\n\`\`\`\n${detail}\n\`\`\``;
  }
  const body = result.stdout.trimEnd() || "(no output)";
  return `**${argsLine}**\n\n\`\`\`\n${body}\n\`\`\``;
}

export const AgentmfPlugin = async ({ directory } = {}) => {
  const projectCwd = typeof directory === "string" && directory ? directory : undefined;
  dbg("init", `directory=${projectCwd || "(none)"}`, `bin=${AGENTMF_BIN}`,
      `slash=/${SLASH_COMMAND}`);
  // sessionID -> { content, selected_targets, request_text }. Populated by
  // chat.message; the prefix is consumed by experimental.chat.system.transform
  // and the routing metadata is folded into the session.idle evidence payload.
  // Bounded LRU isn't worth it for a single-session terminal.
  const cacheBySession = new Map();
  // sessionID -> Map<file, FileDiff>. We dedupe by file so the latest
  // session.diff for a file overwrites earlier ones (session.diff is
  // cumulative per session).
  const diffsBySession = new Map();

  function captureDiffEvent(event) {
    const sessionID = event?.properties?.sessionID;
    const diffs = event?.properties?.diff;
    if (DEBUG && diffs !== undefined && !Array.isArray(diffs)) {
      dbg("event: session.diff non-array properties.diff",
          `type=${typeof diffs}`);
    }
    if (!sessionID || !Array.isArray(diffs)) return;
    let bucket = diffsBySession.get(sessionID);
    if (!bucket) {
      bucket = new Map();
      diffsBySession.set(sessionID, bucket);
    }
    for (const fileDiff of diffs) {
      if (fileDiff && typeof fileDiff.file === "string") {
        bucket.set(fileDiff.file, fileDiff);
      }
    }
    dbg("event: captured diff", `sessionID=${sessionID}`,
        `files_in_event=${diffs.length}`, `total_files=${bucket.size}`);
  }

  function drainDiffs(sessionID) {
    const bucket = diffsBySession.get(sessionID);
    if (!bucket) return [];
    const out = Array.from(bucket.values());
    diffsBySession.delete(sessionID);
    return out;
  }

  return {
    "chat.message": async (input, output) => {
      const sessionID = input?.sessionID || output?.message?.sessionID;
      if (!sessionID) { dbg("chat.message: no sessionID"); return; }
      const text = extractTextFromParts(output?.parts);
      if (!text || text.length < MIN_REQUEST_CHARS) {
        dbg("chat.message: no usable text", `sessionID=${sessionID}`);
        return;
      }
      dbg("chat.message: calling agentmf", `sessionID=${sessionID}`, `chars=${text.length}`);
      const routed = await fetchRoutedPrefix(text, projectCwd);
      if (!routed) { dbg("chat.message: agentmf produced no prefix"); return; }
      cacheBySession.set(sessionID, {
        content: routed.content,
        selected_targets: routed.selected_targets,
        request_text: routed.request_text,
      });
      dbg("chat.message: cached prefix",
          `target=${routed.routing?.primary?.target || "?"}`,
          `bytes=${routed.content.length}`);
    },

    "experimental.chat.system.transform": async (input, output) => {
      if (!output || !Array.isArray(output.system)) {
        dbg("system.transform: output.system missing"); return;
      }
      const sessionID = input?.sessionID;
      if (!sessionID) { dbg("system.transform: no sessionID"); return; }
      const cached = cacheBySession.get(sessionID);
      if (!cached) {
        dbg("system.transform: cache miss", `sessionID=${sessionID}`);
        return;
      }
      if (output.system.some((entry) => typeof entry === "string" && entry.startsWith(PREFIX_HEADER))) {
        dbg("system.transform: already injected, skip"); return;
      }
      output.system.push(cached.content);
      dbg("system.transform: injected", `bytes=${cached.content.length}`, `system_count=${output.system.length}`);
    },

    "command.execute.before": async (input, output) => {
      if (!input || input.command !== SLASH_COMMAND) return;
      if (!output || !Array.isArray(output.parts)) {
        dbg("command: output.parts missing"); return;
      }
      const args = parseSlashArgs(input.arguments);
      dbg("command: running", `argv=${JSON.stringify(args)}`);
      const result = runAgentmfSync(args, projectCwd);
      const text = formatSlashResult(args, result);
      output.parts.push({ type: "text", text });
      dbg("command: emitted parts", `ok=${result.ok}`, `chars=${text.length}`);
    },

    event: async ({ event } = {}) => {
      if (!event) return;
      if (event.type === "session.diff") {
        if (DEBUG) {
          // One-line snapshot of the raw payload so the install can verify
          // OpenCode is actually publishing FileDiff[] (some versions emit
          // empty arrays during streaming; the LAST event before idle is
          // usually the one with the populated diff).
          const keys = Object.keys(event.properties || {}).join(",");
          const len = Array.isArray(event.properties?.diff) ? event.properties.diff.length : "n/a";
          dbg("event: session.diff raw", `keys=[${keys}]`, `diff.length=${len}`);
        }
        captureDiffEvent(event);
        return;
      }
      const shipKinds = new Set([
        "session.idle",
        "session.completed",
        "message.completed",
      ]);
      if (!shipKinds.has(event.type)) return;
      const sessionID = event?.properties?.sessionID || event?.properties?.session?.id || null;
      let diffs = sessionID ? drainDiffs(sessionID) : [];
      let diffSource = "session.diff bucket";
      if (diffs.length === 0) {
        const gitDiffs = snapshotGitDiff(projectCwd);
        if (Array.isArray(gitDiffs)) {
          diffs = gitDiffs;
          diffSource = "git diff";
        }
      }
      const routing = sessionID ? cacheBySession.get(sessionID) : null;
      if (sessionID) cacheBySession.delete(sessionID);
      dbg("event: shipping evidence", `type=${event.type}`,
          `diff_files=${diffs.length}`, `source=${diffSource}`,
          `targets=${(routing?.selected_targets || []).join(",") || "(none)"}`);
      shipTraceEvidence({ event, cwd: projectCwd, diffs, diffSource, routing });
      dbg("event: ship spawn returned", `type=${event.type}`);
    },
  };
};

// OpenCode loads `server` from the plugin module (PluginModule.server).
// Re-export under all three names so the same package works whether the
// loader imports `default`, the named export, or `server`.
export const server = AgentmfPlugin;
export default { server: AgentmfPlugin };
