import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { parsePyvenvCfg, resolveVenvPython } from "./python_cmd.mjs";

const cfg = [
  "home = C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python312",
  "include-system-site-packages = false",
  "version = 3.12.8",
  "executable = C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
].join("\n");

test("pyvenv.cfg keys are parsed without the comment lines", () => {
  const parsed = parsePyvenvCfg("# note\nhome = C:\\Python312\nexecutable = C:\\Python312\\python.exe\n");
  assert.equal(parsed.home, "C:\\Python312");
  assert.equal(parsed.executable, "C:\\Python312\\python.exe");
  assert.equal(parsed["# note"], undefined);
});

test("Windows venv redirector is replaced by the base interpreter", () => {
  const launcher = "C:\\repo\\.venv\\Scripts\\python.exe";
  const base = "C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python312\\python.exe";
  const cfgPath = path.win32.resolve(path.win32.dirname(launcher), "..", "pyvenv.cfg");
  const files = new Set([cfgPath, base]);
  const resolved = resolveVenvPython(launcher, {
    platform: "win32",
    exists: (p) => files.has(p),
    readFile: () => cfg.replace("C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python312\\python.exe", base),
  });
  assert.equal(resolved.command, base);
  assert.equal(resolved.env.__PYVENV_LAUNCHER__, path.win32.resolve(launcher));
});

test("Linux and a missing pyvenv.cfg keep the selected interpreter", () => {
  assert.deepEqual(resolveVenvPython("/repo/.venv/bin/python", { platform: "linux" }), {
    command: "/repo/.venv/bin/python", env: {},
  });
  const plain = resolveVenvPython("C:\\Python312\\python.exe", {
    platform: "win32", exists: () => false, readFile: () => "",
  });
  assert.equal(plain.command, "C:\\Python312\\python.exe");
  assert.deepEqual(plain.env, {});
});
