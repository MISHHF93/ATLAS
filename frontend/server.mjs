// A single TCP listener. FastAPI runs over the child's stdio, never on another port.
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { createRequire } from "node:module";
import next from "next";

const require = createRequire(import.meta.url);
const { WebSocketServer } = require("next/dist/compiled/ws");
const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(directory, "..");
// ATLAS_PYTHON wins; else the repo's .venv, else a sibling .atlas-venv, else python3/python on PATH.
const { existsSync: venvExists } = await import("node:fs");
const venvBin = process.platform === "win32" ? "Scripts/python.exe" : "bin/python";
const python = process.env.ATLAS_PYTHON
  ?? [path.join(root, ".venv", venvBin), path.join(root, "..", ".atlas-venv", venvBin)].find((p) => venvExists(p))
  ?? (process.platform === "win32" ? "python" : "python3");
const child = spawn(python, ["-B", "-u", path.join(directory, "scripts/asgi_stdio.py")], {
  cwd: root, stdio: ["pipe", "pipe", "inherit"], windowsHide: true,
  env: { ...process.env, PYTHONPATH: path.join(root, "src") },
});
const channels = new Map();
let sequence = 0;
let available = true;
function send(message) {
  if (!available || child.stdin.destroyed) throw new Error("Backend unavailable");
  if (child.stdin.writableLength > 4 * 1024 * 1024) throw new Error("Backend overloaded");
  child.stdin.write(JSON.stringify(message) + "\n");
}
createInterface({ input: child.stdout }).on("line", (line) => {
  try {
    const message = JSON.parse(line);
    channels.get(message.id)?.(message);
  } catch (error) { console.error("Invalid backend response:", error.message); }
});
child.on("error", (error) => { console.error(error); available = false; });
child.on("exit", () => {
  available = false;
  for (const callback of channels.values()) callback({ type: "bridge.error" });
  channels.clear();
});

const production = process.argv.includes("--production");
if (production) {
  // A stale .next build serves new routes as "That page is not in ATLAS". Rebuild when any page is missing.
  const { existsSync, readFileSync, readdirSync } = await import("node:fs");
  const manifest = path.join(directory, ".next", "server", "app-paths-manifest.json");
  const built = existsSync(manifest) ? Object.keys(JSON.parse(readFileSync(manifest, "utf8"))) : [];
  const pages = [];
  const walk = (dir, rel) => { for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.isDirectory()) walk(path.join(dir, e.name), `${rel}/${e.name}`); else if (e.name === "page.tsx") pages.push(`${rel}/page`); } };
  walk(path.join(directory, "app"), "");
  const missing = pages.filter((p) => !built.includes(p));
  if (missing.length) {
    console.error(`ATLAS: production build is stale (missing ${missing.join(", ")}); running next build...`);
    const { spawnSync } = await import("node:child_process");
    const r = spawnSync(process.execPath, [require.resolve("next/dist/bin/next"), "build"], { cwd: directory, stdio: "inherit" });
    if (r.status !== 0) { console.error("ATLAS: next build failed"); process.exit(1); }
  }
}
// ---- Security headers for every response served from Node (pages and static assets). The API bridge's responses carry their own
// (src/atlas/accounts/security_headers.py). Pages get a per-request nonce CSP: Next reads the nonce from the REQUEST's CSP header and
// stamps it on its inline scripts, so no 'unsafe-inline' for scripts. Pages are rendered dynamically for that reason (app/layout.tsx).
const { randomBytes } = await import("node:crypto");
const publicUrl = (process.env.ATLAS_PUBLIC_URL ?? "").trim();
const trustedProxies = (process.env.ATLAS_TRUSTED_PROXIES ?? "").split(",").map((x) => x.trim()).filter(Boolean);
const peerOf = (req) => (req.socket.remoteAddress ?? "").replace(/^::ffff:/, "");
function isHttps(req) {
  if (publicUrl.toLowerCase().startsWith("https://")) return true;
  // X-Forwarded-Proto is believed only from a configured proxy (exact IP match; CIDRs are handled on the Python side).
  return trustedProxies.includes(peerOf(req)) && String(req.headers["x-forwarded-proto"] ?? "").split(",").pop().trim().toLowerCase() === "https";
}
function pageCsp(nonce) {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}'${production ? "" : " 'unsafe-eval'"}`,
    "style-src 'self' 'unsafe-inline'",           // React inline style attributes (charts, layout); script injection stays blocked
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self' ws: wss:",
    "worker-src 'self' blob:",
    "object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'",
  ].join("; ");
}
function applySecurityHeaders(req, res, csp) {
  res.setHeader("Content-Security-Policy", csp);
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("X-Frame-Options", "DENY");
  res.setHeader("Referrer-Policy", "no-referrer");   // verify / reset / invite tokens ride in URLs
  res.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()");
  res.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  if (isHttps(req)) res.setHeader("Strict-Transport-Security", "max-age=63072000; includeSubDomains");
}
const app = next({ dev: !production, dir: directory });
await app.prepare();
const handle = app.getRequestHandler();
const server = http.createServer(async (req, res) => {
  if (!req.url?.startsWith("/api/")) {
    const csp = pageCsp(randomBytes(16).toString("base64"));
    req.headers["content-security-policy"] = csp;       // Next extracts the nonce from this request header
    applySecurityHeaders(req, res, csp);
    return handle(req, res);
  }
  if (!available) { res.writeHead(503).end("Backend unavailable"); return; }
  const id = String(++sequence);
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 1024 * 1024) { res.writeHead(413).end(); return; }
    chunks.push(chunk);
  }
  const timeout = setTimeout(() => {
    channels.delete(id);
    if (!res.headersSent) res.writeHead(504);
    res.end("Backend timeout");
    try { send({ id, type: "cancel" }); } catch {}
  }, 60_000);
  channels.set(id, (message) => {
    if (message.type === "http.response.start") res.writeHead(message.status, message.headers.flat());
    if (message.type === "http.response.body") {
      res.write(Buffer.from(message.body ?? "", "base64"));
      if (!message.more_body) { clearTimeout(timeout); channels.delete(id); res.end(); }
    }
    if (message.type === "bridge.error") {
      clearTimeout(timeout); channels.delete(id);
      if (!res.headersSent) res.writeHead(503);
      res.end("Backend unavailable");
    }
  });
  try {
    send({ id, type: "http", url: req.url, method: req.method, headers: { ...req.headers, "x-atlas-client-ip": req.socket.remoteAddress ?? "" }, body: Buffer.concat(chunks).toString("base64") });
  } catch {
    clearTimeout(timeout); channels.delete(id); res.writeHead(503).end("Backend unavailable");
  }
});
const sockets = new WebSocketServer({ noServer: true, maxPayload: 64 * 1024 });
server.on("upgrade", (req, socket, head) => {
  if (!req.url?.startsWith("/ws/market-stream")) { app.getUpgradeHandler()(req, socket, head); return; }
  if (!available) { socket.destroy(); return; }
  sockets.handleUpgrade(req, socket, head, (ws) => {
    const id = String(++sequence);
    channels.set(id, (message) => {
      if (message.type === "websocket.send" && ws.readyState === 1) {
        if (ws.bufferedAmount > 1024 * 1024) { ws.close(1013, "Slow consumer"); return; }
        ws.send(message.text ?? Buffer.from(message.bytes ?? "", "base64"));
      }
      if (message.type === "websocket.close" || message.type === "bridge.error") ws.close(1011);
    });
    ws.on("message", (data) => {
      try { send({ id, type: "websocket.receive", text: data.toString() }); }
      catch { ws.close(1013); }
    });
    ws.on("close", () => {
      channels.delete(id);
      try { send({ id, type: "websocket.disconnect", code: 1000 }); } catch {}
    });
    send({ id, type: "websocket", url: req.url, headers: { ...req.headers, "x-atlas-client-ip": req.socket.remoteAddress ?? "" } });
  });
});
server.on("error", (error) => { console.error(error); child.kill(); process.exitCode = 1; });
const port = Number(process.env.PORT ?? 3000);
server.listen(port, "127.0.0.1", () => console.log(`ATLAS http://localhost:${port}`+" (HTTP + WebSocket; Python over stdio)"));
function shutdown() { for (const ws of sockets.clients) ws.terminate(); child.kill(); server.close(); }
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
