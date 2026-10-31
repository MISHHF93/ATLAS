// Resolve a Python command for the Node host.
// On Windows a venv Scripts/python.exe is a redirector that spawns the base
// interpreter and waits (PC/venvlauncher.c). Spawning the base interpreter with
// __PYVENV_LAUNCHER__ set is the same activation, with one process instead of two.
import path from "node:path";

export function parsePyvenvCfg(text) {
  const cfg = {};
  for (const line of String(text).split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    cfg[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1).trim();
  }
  return cfg;
}

export function resolveVenvPython(python, { platform = process.platform, exists = () => false, readFile = () => "" } = {}) {
  if (platform !== "win32" || !python) return { command: python, env: {} };
  // path.win32 so a test on Linux exercises the same joins the Windows host uses.
  const paths = path.win32;
  const cfgPath = paths.resolve(paths.dirname(python), "..", "pyvenv.cfg");
  if (!exists(cfgPath)) return { command: python, env: {} };
  let text = "";
  try { text = readFile(cfgPath); } catch { return { command: python, env: {} }; }
  const cfg = parsePyvenvCfg(text);
  let base = cfg.executable || "";
  if (!base && cfg.home) base = paths.join(cfg.home, "python.exe");
  if (!base || !exists(base)) return { command: python, env: {} };
  return { command: base, env: { __PYVENV_LAUNCHER__: paths.resolve(python) } };
}
