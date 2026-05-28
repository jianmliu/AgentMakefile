// Local smoke test for @agentmf/opencode-plugin.
// Drives the plugin without OpenCode: fakes chat.message + system.transform
// + event, asserts injection happens via the cache, and that no-op contracts
// hold when agentmf is missing or input is empty.

import { AgentmfPlugin } from "../index.js";
import { fileURLToPath } from "node:url";
import { mkdtempSync, copyFileSync, symlinkSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const PREFIX_HEADER = "## Routed Guidance (AgentMakefile)";

// Stand up a throwaway project dir so the event-hook subprocess writes its
// evidence record under /tmp instead of into the repo tree we live in.
function makeSandbox() {
  const dir = mkdtempSync(path.join(tmpdir(), "agentmf-plugin-smoke-"));
  const srcMakefile = path.join(REPO_ROOT, "AgentMakefile");
  const srcModules = path.join(REPO_ROOT, "modules");
  if (existsSync(srcMakefile)) copyFileSync(srcMakefile, path.join(dir, "AgentMakefile"));
  if (existsSync(srcModules)) symlinkSync(srcModules, path.join(dir, "modules"), "dir");
  return dir;
}

const SANDBOX = makeSandbox();
process.on("exit", () => {
  try { rmSync(SANDBOX, { recursive: true, force: true }); } catch {}
});

let failures = 0;
function check(label, cond, detail) {
  if (cond) {
    process.stdout.write(`  ok  ${label}\n`);
  } else {
    failures += 1;
    process.stdout.write(`  FAIL ${label}\n`);
    if (detail !== undefined) process.stdout.write(`       ${detail}\n`);
  }
}

function makeUserMessage(sessionID, text) {
  return {
    message: { id: "m1", sessionID, role: "user", time: { created: Date.now() } },
    parts: [{ id: "p1", sessionID, messageID: "m1", type: "text", text }],
  };
}

async function testRoutedInjection() {
  process.stdout.write("\n[chat.message + system.transform] inject routed prefix\n");
  const hooks = await AgentmfPlugin({ directory: SANDBOX });
  const sessionID = "smoke-sess-1";

  const userMsg = makeUserMessage(sessionID, "fix a flaky test in the selector module");
  await hooks["chat.message"]({ sessionID }, userMsg);

  const sysOut = { system: ["base system prompt"] };
  await hooks["experimental.chat.system.transform"]({ sessionID, model: {} }, sysOut);

  const agentmfInjected = sysOut.system.length > 1;
  if (!agentmfInjected) {
    process.stdout.write("  (agentmf not on PATH or selected nothing — verifying no-op contract)\n");
    check("system list unchanged when agentmf returns nothing", sysOut.system.length === 1);
    return;
  }
  check("system list grew by exactly one entry", sysOut.system.length === 2);
  const injected = sysOut.system[1];
  check(
    "injected entry tagged with routed-guidance header",
    typeof injected === "string" && injected.startsWith(PREFIX_HEADER),
    `got: ${typeof injected === "string" ? injected.slice(0, 80) : typeof injected}`
  );
  check("base system prompt preserved", sysOut.system[0] === "base system prompt");

  // Idempotence within a session
  await hooks["experimental.chat.system.transform"]({ sessionID, model: {} }, sysOut);
  check("idempotent injection across re-call (still 2 entries)", sysOut.system.length === 2);
}

async function testEventCapture() {
  process.stdout.write("\n[event] session.idle ships evidence\n");
  const hooks = await AgentmfPlugin({ directory: SANDBOX });
  let threw = null;
  try {
    await hooks.event({
      event: {
        type: "session.idle",
        properties: { sessionID: "smoke-sess-evt", title: "smoke" },
      },
    });
  } catch (err) { threw = err; }
  check("event hook does not throw on session.idle", threw === null, threw && String(threw));

  threw = null;
  try {
    await hooks.event({ event: { type: "unrelated.event", properties: {} } });
  } catch (err) { threw = err; }
  check("event hook ignores unrelated event types", threw === null, threw && String(threw));
}

async function testDiffCapture() {
  process.stdout.write("\n[event] session.diff accumulates per-session\n");
  const hooks = await AgentmfPlugin({ directory: SANDBOX });
  const sessionID = "smoke-sess-diff";

  // Two session.diff events covering an overlapping + a new file.
  await hooks.event({
    event: {
      type: "session.diff",
      properties: {
        sessionID,
        diff: [
          { file: "src/a.py", before: "old", after: "new1", additions: 1, deletions: 1 },
          { file: "src/b.py", before: "", after: "hello\n", additions: 1, deletions: 0 },
        ],
      },
    },
  });
  await hooks.event({
    event: {
      type: "session.diff",
      properties: {
        sessionID,
        diff: [
          { file: "src/a.py", before: "old", after: "new2", additions: 2, deletions: 1 },
          { file: "src/c.py", before: "", after: "x\n", additions: 1, deletions: 0 },
        ],
      },
    },
  });

  // session.idle should drain + ship; we can't inspect the spawned subprocess
  // directly, but we can verify the hook does not throw and the in-memory
  // bucket was emptied by triggering session.idle and then probing internal
  // behavior indirectly via a second idle (should drain empty).
  let threw = null;
  try {
    await hooks.event({
      event: { type: "session.idle", properties: { sessionID } },
    });
  } catch (err) { threw = err; }
  check("session.idle does not throw with diff bucket populated", threw === null, threw && String(threw));

  threw = null;
  try {
    await hooks.event({
      event: { type: "session.idle", properties: { sessionID } },
    });
  } catch (err) { threw = err; }
  check("second session.idle (empty bucket) also no-throws", threw === null, threw && String(threw));
}

async function testSlashCommand() {
  process.stdout.write("\n[command.execute.before] /agentmf intercept\n");
  const hooks = await AgentmfPlugin({ directory: SANDBOX });

  // Ignored: not our command.
  const otherOut = { parts: [] };
  await hooks["command.execute.before"](
    { command: "other", sessionID: "s1", arguments: "" },
    otherOut,
  );
  check("non-/agentmf commands are ignored", otherOut.parts.length === 0);

  // Our command — should emit at least one text part.
  const out = { parts: [] };
  await hooks["command.execute.before"](
    { command: "agentmf", sessionID: "s2", arguments: "--help" },
    out,
  );
  check("/agentmf emits exactly one part", out.parts.length === 1, `got ${out.parts.length}`);
  const part = out.parts[0];
  check("/agentmf part is type=text", part?.type === "text");
  check("/agentmf part text is non-empty", typeof part?.text === "string" && part.text.length > 0);
}

async function testGuards() {
  process.stdout.write("\n[chat.message] guards\n");
  const hooks = await AgentmfPlugin({ directory: SANDBOX });

  // No parts — should not crash, should not populate cache
  await hooks["chat.message"]({ sessionID: "g1" }, { message: {}, parts: [] });
  const sysOut1 = { system: ["base"] };
  await hooks["experimental.chat.system.transform"]({ sessionID: "g1", model: {} }, sysOut1);
  check("system.transform no-op when chat.message had no text", sysOut1.system.length === 1);

  // Short text — guard against trivially-short requests
  await hooks["chat.message"](
    { sessionID: "g2" },
    makeUserMessage("g2", "ok"),
  );
  const sysOut2 = { system: ["base"] };
  await hooks["experimental.chat.system.transform"]({ sessionID: "g2", model: {} }, sysOut2);
  check("system.transform no-op when request is < 3 chars", sysOut2.system.length === 1);
}

async function testModuleShape() {
  process.stdout.write("\n[module] export shape\n");
  const mod = await import("../index.js");
  check("named export AgentmfPlugin is a function", typeof mod.AgentmfPlugin === "function");
  check("server export is a function", typeof mod.server === "function");
  check("default export has server property", typeof mod.default?.server === "function");
}

async function main() {
  await testModuleShape();
  await testGuards();
  await testRoutedInjection();
  await testEventCapture();
  await testDiffCapture();
  await testSlashCommand();
  process.stdout.write(failures ? `\n${failures} failure(s)\n` : "\nall green\n");
  process.exit(failures ? 1 : 0);
}

main().catch((err) => {
  process.stderr.write(`smoke harness crashed: ${err && err.stack ? err.stack : err}\n`);
  process.exit(2);
});
